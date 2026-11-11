"""One opt-in bounded real C transport/tool canary. Never uses household microphone/audio.

Requires current server-side Owner Full Test developer Live admission. No retry loop.
Decoded PCM is transport evidence, not physical-device or pronunciation acceptance.
"""
import argparse,asyncio,json,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/brain'))

async def run():
    import httpx,numpy as np
    from aiortc import RTCPeerConnection,RTCSessionDescription,AudioStreamTrack
    from gobot.owner_testing import OwnerTesting
    policy=OwnerTesting(ROOT/'run/owner-testing').policy()
    if not policy.enabled or not policy.live_enabled or policy.developer_live_limit<1:raise SystemExit('Developer Live admission required')
    keys=json.loads((ROOT/'run/keys.json').read_text());headers={'Authorization':'Bearer '+keys['api_token']}
    appid='live-canary-'+uuid4().hex;clientid='live-canary-device';owner='browser-live-canary'
    base='http://127.0.0.1:18781/api/v1/live';pc=RTCPeerConnection();pc.addTrack(AudioStreamTrack());pc.createDataChannel('oai-events')
    report={'synthetic_only':True,'requested_model':'gpt-live-1','requested_version':'1.1','actual_model':None,
        'session_started':False,'physical_iphone':False,'acoustic_quality_verified':False,'auto_retries':0,'separate_stt_tts_calls':0}
    events=[];received=[];tasks=[];sse=None;session_created=False
    @pc.on('track')
    def track(remote):
        async def drain():
            try:
                while True:
                    frame=await remote.recv();a=frame.to_ndarray().astype('float64')
                    if np.sqrt(np.mean(a*a))>50:received.append(time.monotonic())
            except Exception:pass
        tasks.append(asyncio.create_task(drain()))
    async with httpx.AsyncClient(trust_env=False,timeout=60,headers=headers) as c:
        async def command(action,**extra):
            r=await c.post(base+'/sessions/'+appid+'/command',json={'command_id':uuid4().hex,'action':action,'device_id':owner,'client_id':clientid,'profile_epoch':None,**extra})
            if r.status_code!=200:raise RuntimeError('canary_command_http_'+str(r.status_code))
            return r.json()
        async def read_events():
            async with c.stream('GET',base+'/sessions/'+appid+'/events',params={'device_id':owner,'client_id':clientid}) as r:
                async for line in r.aiter_lines():
                    if line.startswith('data: '):events.append(json.loads(line[6:]))
        try:
            await pc.setLocalDescription(await pc.createOffer());start=time.monotonic()
            r=await c.post(base+'/sessions',json={'session_id':appid,'conversation_id':'synthetic-'+uuid4().hex,'sdp':pc.localDescription.sdp,
                'consent':True,'device_id':owner,'client_id':clientid,'owner_test_binding':policy.allowed_client_id,
                'developer_acceptance':True,'requested_model':'gpt-live-1','speaker_consent':False,'expert_quota_consent':True,'remember':False})
            report['create_http']=r.status_code;report['cold_setup_ms']=round((time.monotonic()-start)*1000,2)
            if r.status_code!=200:
                report['failure_code']=r.json().get('detail','unknown');return report
            session_created=True;answer=r.json();report['actual_model']=answer['model'];report['session_started']=answer['configuration_confirmed'];report['voice']=answer['voice']
            await pc.setRemoteDescription(RTCSessionDescription(type='answer',sdp=answer['sdp']));sse=asyncio.create_task(read_events())
            for _ in range(150):
                if pc.connectionState=='connected':break
                await asyncio.sleep(.1)
            if pc.connectionState!='connected':raise RuntimeError('canary_webrtc_not_connected')
            report['webrtc_connected']=True
            tool_start=time.monotonic();await command('text',text='Поставь таймер на пять секунд')
            report['timer_command_ms']=round((time.monotonic()-tool_start)*1000,2)
            await asyncio.sleep(9)
            report['timer_widget']=any(e['type']=='visual_response' and e.get('data',{}).get('presentation',{}).get('type')=='timer_widget' for e in events)
            report['timer_expired']=any(e['type']=='timer_expired' for e in events)
            report['decoded_audible_frames']=len(received)
            report['first_decoded_audio_after_tool_ms']=round((received[0]-tool_start)*1000,2) if received else None
            report['heard_useful_word_ms']=None
            report['event_types']=sorted({e['type'] for e in events})
        except Exception as error:
            report['failure_code']=str(error) if isinstance(error,RuntimeError) else type(error).__name__
        finally:
            if session_created:
                try:report['close']=await command('end',reason='user_stop')
                except Exception:report['close']={'final_usage_confirmed':False}
            await pc.close()
            if sse:sse.cancel()
            for t in tasks:t.cancel()
            await asyncio.gather(*tasks,*([sse] if sse else []),return_exceptions=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--real',action='store_true');args=parser.parse_args()
    if not args.real:raise SystemExit('Use --real only with owner-approved bounded developer budget')
    result=asyncio.run(run())
    target=ROOT/'docs/live-acceptance.json';target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
