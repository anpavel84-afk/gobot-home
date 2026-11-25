"""Offline, private support packet. No API keys, audio, transcripts or network calls."""
import hashlib,json,os,sqlite3
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def utc(value):return datetime.fromtimestamp(value,timezone.utc).isoformat() if value is not None else None
def collect(root=ROOT):
    root=Path(root)
    policy=json.loads((root/'run/owner-testing/policy.json').read_text(encoding='utf8'))
    origin='hardware:'+policy['hardware_voice']['grant_id']
    with sqlite3.connect((root/'run/live/usage.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        rows=db.execute('SELECT id,provider,reserved,seconds,cleanup_attempted FROM calls WHERE origin=? AND final=0',(origin,)).fetchall()
        confirmed=db.execute('SELECT coalesce(sum(seconds),0) FROM calls WHERE origin=? AND final=1',(origin,)).fetchone()[0]
    if len(rows)!=1:raise ValueError('exactly_one_unconfirmed_board_session_required')
    ident,provider,reserved,seconds,attempted=rows[0]
    with sqlite3.connect((root/'run/debug-journal/journal.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        first,last=db.execute('SELECT min(created),max(created) FROM events WHERE session=?',(ident,)).fetchone()
    project=os.environ.get('OPENAI_PROJECT_ID') or os.environ.get('OPENAI_PROJECT')
    if not project or not project.startswith('proj_'):project=None
    packet={'created_utc':datetime.now(timezone.utc).isoformat(),'provider':'OpenAI','model':'gpt-live-1',
        'provider_session_id':provider,'application_session_id':ident,'project_id':project,
        'project_id_source':'configured_environment' if project else 'not_recorded; owner must verify API project',
        'journal_first_event_utc':utc(first),'journal_last_event_utc':utc(last),
        'last_cumulative_usage_seconds':seconds,'provider_close_ack_received':False,
        'reserved_seconds_not_final_usage':reserved,'confirmed_other_sessions_seconds':confirmed,
        'failure':'live_sideband_disconnected; original exception detail was not recorded',
        'administrative_cleanup_observation':{'http_status':503,'exception_kind':'InvalidStatus',
            'request_id':None,'observed_at_utc':None,
            'missing_fields_reason':'prior bounded attempt did not persist response headers or its exact UTC timestamp'},
        'cleanup_already_attempted':bool(attempted),'store':False,'ledger_modified':False,
        'request':'Please confirm terminal state and final cumulative billable duration for this session; explain sideband attach HTTP 503.'}
    directory=root/'data/hardware/gobot-v1/support'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'case.json').write_text(json.dumps(packet,indent=2),encoding='utf8')
    (directory/'SUPPORT_DRAFT.txt').write_text(
        'DRAFT FOR OWNER REVIEW — NOT SENT\n\n'+packet['request']+'\n\n'
        'See case.json for private session identifiers, UTC journal bounds and observed usage.\n'
        'Project ID and failed-request ID were not retained: verify them in the matching API project/provider diagnostics.\n'
        'Do not include API keys, raw household audio or full conversations.\n'
        'No terminal ACK has been received; local timers/reservations and HTTP 503 are not final billing evidence.\n',encoding='utf8')
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    return directory
if __name__=='__main__':print(collect())
