"""Local operator recovery. Default: read-only checks; never opens an OpenAI session.

Stop the hardware gateway for maintenance before applying. No service is stopped
by this script. --apply records local orphan status only. A separate explicit
--accept-unknown-provider-cost grants bounded new starts from the EXISTING quota.
"""
import argparse,asyncio,json,re,socket,sqlite3,sys,time
from datetime import datetime,timezone
from pathlib import Path
import httpx,jwt

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/brain'))

def backup_sqlite(source,target):
    # SQLite backup includes committed WAL pages, unlike copying the .sqlite file.
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:src.backup(dst)

async def verify_local(root,ident,*,client=None,listener=None,close_old_room=False):
    private=root/'data/hardware/gobot-v1'
    config=json.loads((private/'gateway.json').read_text(encoding='utf8'))
    if config['brain_url']!='http://127.0.0.1:18781' or config['port']!=18789:raise ValueError('unreviewed_local_endpoints')
    def listening():
        with socket.socket() as sock:
            sock.settimeout(1)
            return sock.connect_ex((config['bind'],18789))==0
    if (listener or listening)():raise ValueError('stop_gateway_for_maintenance_first')
    token=json.loads((root/'run/keys.json').read_text(encoding='utf8'))['api_token']
    kit=json.loads((private/'livekit/private.json').read_text(encoding='utf8'))
    if kit['url']!='ws://127.0.0.1:17880':raise ValueError('livekit_loopback_required')
    owned=client is None
    client=client or httpx.AsyncClient(trust_env=False,timeout=5,follow_redirects=False)
    try:
        async def brain_idle():
            response=await client.get(config['brain_url']+'/api/v1/live/status',headers={'Authorization':'Bearer '+token})
            response.raise_for_status()
            if response.json().get('active_sessions')!=0:raise ValueError('brain_sessions_still_active')
        await brain_idle()
        room='gobot-'+ident
        now=int(time.time())
        # Official RoomService ListRooms/DeleteRoom, loopback only; never OpenAI.
        def headers(grant):return {'Authorization':'Bearer '+jwt.encode(
            {'iss':kit['key'],'nbf':now-3,'exp':now+30,'video':grant},kit['secret'],algorithm='HS256')}
        async def rooms():
            response=await client.post('http://127.0.0.1:17880/twirp/livekit.RoomService/ListRooms',
                headers=headers({'roomList':True}),json={'names':[room]})
            response.raise_for_status();body=response.json()
            values=body.get('rooms',[])
            if not isinstance(values,list) or any(not isinstance(r,dict) or r.get('name')!=room for r in values):
                raise ValueError('unexpected_room_response')
            return values
        old=await rooms()
        if old and close_old_room:
            response=await client.post('http://127.0.0.1:17880/twirp/livekit.RoomService/DeleteRoom',
                headers=headers({'roomCreate':True}),json={'room':room})
            response.raise_for_status()
            old=await rooms()
        if old:raise ValueError('old_relay_still_present')
        await brain_idle()
        if (listener or listening)():raise ValueError('gateway_restarted_during_verification')
        return dict(gateway_idle=True,brain_idle=True,old_relay_absent=True)
    finally:
        if owned:await client.aclose()

async def main(args):
    root=ROOT
    policy=json.loads((root/'run/owner-testing/policy.json').read_text(encoding='utf8'))
    grant=policy['hardware_voice']
    with sqlite3.connect((root/'run/live/usage.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT scope,final FROM calls WHERE id=? AND origin=?',
            (args.session,'hardware:'+grant['grant_id'])).fetchone()
    if not row or row[1]:raise ValueError('unconfirmed_board_session_required')
    if args.accept_unknown_provider_cost and not args.apply:raise ValueError('approval_requires_apply')
    evidence=await verify_local(root,args.session,close_old_room=args.apply)
    if not args.apply:
        print(json.dumps({'verified_local_resources':evidence,'ledger_changed':False,'provider_close_confirmed':False}));return
    directory=root/'data/hardware/gobot-v1/recovery'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True,exist_ok=False)
    for name in ('live','owner-testing'):
        backup_sqlite(root/f'run/{name}/usage.sqlite',directory/f'{name}-usage.sqlite')
    from gobot.owner_testing import OwnerTesting
    from gobot.live_budget import LiveBudget
    budget=LiveBudget(root/'run/live',OwnerTesting(root/'run/owner-testing'))
    budget.recovery.orphan(args.session,row[0],local_evidence=evidence)
    if args.accept_unknown_provider_cost:
        budget.recovery.approve(args.session,row[0],owner_binding=policy['allowed_client_id'],risk_ack=True,
            max_new_sessions=args.max_new_sessions,expires_at=time.time()+(args.minutes*60 if args.minutes else args.hours*3600))
    print(json.dumps({'orphaned_unconfirmed':True,'provider_close_confirmed':False,'final_usage':False,
        'new_starts_authorized':args.max_new_sessions if args.accept_unknown_provider_cost else 0,
        'existing_quota_increased':False,'backup_directory':str(directory)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--accept-unknown-provider-cost',action='store_true')
    parser.add_argument('--max-new-sessions',type=int,choices=range(1,51),default=1)
    parser.add_argument('--hours',type=int,choices=range(1,25),default=24)
    parser.add_argument('--minutes',type=int,choices=range(1,61),help='Short recovery window; overrides --hours')
    try:asyncio.run(main(parser.parse_args()))
    except Exception as error:
        # Raw HTTP exceptions/headers/configuration must never reach the console.
        code=str(error) if type(error) in (ValueError,PermissionError) and re.fullmatch(r'[a-z_]{1,100}',str(error)) else 'local_recovery_check_failed'
        print(json.dumps({'ok':False,'error_kind':type(error).__name__,'reason':code,
            'action':'recovery_not_applied_or_incomplete; inspect local resources'}))
        sys.exit(1)
