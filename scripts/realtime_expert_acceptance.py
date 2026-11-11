"""One bounded owner-authorized B -> real CLI -> B synthetic text canary.
No microphone, credentials output, retries or default configuration changes.
"""
import argparse,asyncio,json,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))

async def run():
    import httpx,numpy as np
    from aiortc import RTCPeerConnection,RTCSessionDescription,AudioStreamTrack
    from gobot.owner_testing import OwnerTesting
    from gobot.device_store import DeviceStore
    policy=OwnerTesting(ROOT/'run/owner-testing').policy()
    if not policy.enabled or not policy.experts_enabled or policy.developer_expert_limit<1:raise SystemExit('Developer expert admission required')
    token=json.loads((ROOT/'run/keys.json').read_text())['api_token']
    profile=DeviceStore(ROOT/'data/browser-devices').profile('browser-expert-canary@127.0.0.1')
    scope={'device_id':'browser-expert-canary','client_id':profile.client_id,'profile_epoch':None}
    ident='expert-canary-'+uuid4().hex;base='http://127.0.0.1:18781/api/v1/realtime'
    pc=RTCPeerConnection();pc.addTrack(AudioStreamTrack());events=[];audible=[];workers=[];sse=None;created=False
    report={'synthetic_only':True,'input_path':'typed_text_no_STT','requested_expert':'SOL_HIGH','auto_retries':0,'physical_iphone':False}
    @pc.on('track')
    def remote(track):
        async def drain():
            try:
                while True:
                    a=(await track.recv()).to_ndarray().astype('float64')
                    if np.sqrt(np.mean(a*a))>50:audible.append(time.monotonic())
            except Exception:pass
        workers.append(asyncio.create_task(drain()))
    async with httpx.AsyncClient(trust_env=False,headers={'Authorization':'Bearer '+token},timeout=60) as client:
        async def command(action,**extra):
            r=await client.post(base+'/sessions/'+ident+'/command',json={**scope,'command_id':uuid4().hex,'action':action,**extra})
            if r.status_code!=200:raise RuntimeError('canary_command_http_'+str(r.status_code))
            return r.json()
        async def stream():
            async with client.stream('GET',base+'/sessions/'+ident+'/events',params={k:v or '' for k,v in scope.items()}) as r:
                async for line in r.aiter_lines():
                    if line.startswith('data: '):events.append(json.loads(line[6:]))
        try:
            await pc.setLocalDescription(await pc.createOffer())
            r=await client.post(base+'/sessions',json={**scope,'session_id':ident,'conversation_id':'synthetic-'+uuid4().hex,'sdp':pc.localDescription.sdp,
                'consent':True,'expert_quota_consent':True,'owner_test_binding':policy.allowed_client_id,'developer_acceptance':True,'remember':False,'speak':True,
                'requested_model':'gpt-realtime-2.1-mini','requested_voice':'marin','requested_expert_profile':'SOL_HIGH'})
            report['create_http']=r.status_code
            if r.status_code!=200:report['failure_code']=r.json().get('detail','unknown');return report
            created=True;answer=r.json();report['model']=answer['model']
            await pc.setRemoteDescription(RTCSessionDescription(type='answer',sdp=answer['sdp']));sse=asyncio.create_task(stream())
            started=time.monotonic()
            await command('text',text='Спроси Sol High: проверь, верно ли, что семнадцать умножить на девятнадцать равно 323. Дай один короткий вывод.')
            while time.monotonic()-started<85:
                jobs=[e.get('data',{}).get('job',{}) for e in events if e['type']=='expert_job']
                if any(j.get('state') in {'completed','failed','timed_out'} for j in jobs):break
                await asyncio.sleep(.2)
            jobs=[e.get('data',{}).get('job',{}) for e in events if e['type']=='expert_job']
            report['expert_unique_jobs']=len({j.get('job_id') for j in jobs});report['expert_states']=list(dict.fromkeys(j.get('state') for j in jobs))
            report['expert_actual']=jobs[-1].get('expert') if jobs else None
            report['expert_elapsed_ms']=round((time.monotonic()-started)*1000,2)
            results=[e for e in events if e['type']=='expert_result'];report['expert_result_card']=bool(results)
            report['result_contains_323']=any('323' in e['data']['result']['display_text'] for e in results)
            frames_before=len(audible);await asyncio.sleep(6);report['decoded_frames_after_result']=len(audible)-frames_before
            report['usage_estimated_usd']=sum(e.get('data',{}).get('estimated_usd',0) for e in events if e['type']=='usage')
            report['blocked_reasons']=[e.get('data',{}).get('error') for e in events if e['type']=='expert_blocked']
            report['stage_events']=[e.get('data',{}) for e in events if e['type']=='expert_progress']
            report['event_types']=sorted({e['type'] for e in events})
        except Exception as error:report['failure_code']=str(error) if isinstance(error,RuntimeError) else type(error).__name__
        finally:
            if created:
                try:report['close']=await command('close',close_reason='user_stop')
                except Exception:report['close']={'confirmed':False}
            await pc.close()
            if sse:sse.cancel()
            for task in workers:task.cancel()
            await asyncio.gather(*workers,*([sse] if sse else []),return_exceptions=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--real',action='store_true');args=parser.parse_args()
    if not args.real:raise SystemExit('Explicit bounded developer admission and --real required')
    result=asyncio.run(run());(ROOT/'docs/realtime-expert-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
