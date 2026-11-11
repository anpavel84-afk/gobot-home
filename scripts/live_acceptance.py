"""One opt-in bounded real C transport/tool canary. Never uses household microphone/audio.

Requires current server-side Owner Full Test developer Live admission. No retry loop.
Decoded PCM is transport evidence, not physical-device or pronunciation acceptance.
"""
import argparse,asyncio,json,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/brain'))

async def run(voice_expert=False,tool_case=None):
    import httpx,numpy as np
    from aiortc import RTCPeerConnection,RTCSessionDescription,AudioStreamTrack
    from av import AudioFrame
    from fractions import Fraction
    from gobot.owner_testing import OwnerTesting
    from gobot.device_store import DeviceStore
    policy=OwnerTesting(ROOT/'run/owner-testing').policy()
    if not policy.enabled or not policy.live_enabled or policy.developer_live_limit<1:raise SystemExit('Developer Live admission required')
    keys=json.loads((ROOT/'run/keys.json').read_text());headers={'Authorization':'Bearer '+keys['api_token']}
    synthetic_task='Спроси Сол: сравни очередь и стек. Дай короткий вывод из двух предложений.'
    if tool_case:
        synthetic_task={'timer':'Можешь засечь таймер на пять секунд?',
            'forecast':'Какая будет погода завтра?',
            'continuity':'Засеки таймер на одну минуту.'}[tool_case]
    samples=None
    if voice_expert or tool_case:
        from gobot.audio import Speech
        pcm,rate=await asyncio.to_thread(Speech().denis_sync,synthetic_task)
        original=np.frombuffer(pcm,dtype=np.int16)
        samples=np.interp(np.arange(int(len(original)*48000/rate))*rate/48000,np.arange(len(original)),original).astype(np.int16)
    class CanaryInput(AudioStreamTrack):
        def __init__(self):super().__init__();self.pcm=np.zeros(0,dtype=np.int16);self.pts=0;self.clock=None
        async def recv(self):
            if self.clock is None:self.clock=time.monotonic()
            await asyncio.sleep(max(0,self.clock+self.pts/48000-time.monotonic()))
            data=np.zeros(960,dtype=np.int16);count=min(len(self.pcm),960);data[:count]=self.pcm[:count];self.pcm=self.pcm[count:]
            frame=AudioFrame.from_ndarray(data.reshape(1,-1),format='s16',layout='mono');frame.sample_rate=48000;frame.pts=self.pts;frame.time_base=Fraction(1,48000);self.pts+=960;return frame
    microphone=CanaryInput()
    appid='live-canary-'+uuid4().hex;owner='browser-live-tools-canary' if tool_case else 'browser-live-canary'
    devices=DeviceStore(ROOT/'data/browser-devices')
    profile=devices.profile(owner+'@127.0.0.1')
    if tool_case:
        # Use the already-confirmed weather place without logging coordinates.
        import sqlite3
        from gobot.device_contract import DeviceProfile
        with sqlite3.connect(devices.db) as db:profiles=[DeviceProfile.model_validate_json(row[0]) for row in db.execute('SELECT profile FROM profiles')]
        matches=[p for p in profiles if p.client_id==policy.allowed_client_id]
        if len(matches)!=1 or not matches[0].weather.enabled:raise SystemExit('Confirmed weather place required before paid canary')
        profile=devices.update(owner+'@127.0.0.1',{'weather':matches[0].weather.model_dump(),'screen':{'automatic_illustrations':False,'generation_allowed':False,'generation_mode':'off'}})
    clientid=profile.client_id
    base='http://127.0.0.1:18781/api/v1/live';pc=RTCPeerConnection();pc.addTrack(microphone);pc.createDataChannel('oai-events')
    report={'synthetic_only':True,'requested_model':'gpt-live-1','requested_version':'1.1','actual_model':None,
        'session_started':False,'physical_iphone':False,'acoustic_quality_verified':False,'auto_retries':0,'separate_stt_tts_calls':0,
        'setup_measurement_scope':'backend_create_and_attach_excludes_local_ICE_and_microphone',
        'test_kind':'synthetic_voice_'+tool_case if tool_case else 'synthetic_voice_expert' if voice_expert else 'typed_timer'}
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
                'developer_acceptance':True,'requested_model':'gpt-live-1','speaker_consent':False,'expert_quota_consent':not bool(tool_case),'remember':False})
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
            if tool_case:
                async def heartbeat():
                    while pc.connectionState=='connected':
                        await command('activity',input_active=bool(len(microphone.pcm)),playback_active=bool(received and time.monotonic()-received[-1]<.8))
                        await asyncio.sleep(.7)
                tasks.append(asyncio.create_task(heartbeat()))
                requested=time.monotonic();microphone.pcm=samples
                deadline=requested+38
                def cards():return [e.get('data',{}).get('presentation',{}) for e in events if e['type']=='visual_response']
                while time.monotonic()<deadline:
                    ready=any(e['type']=='timer_expired' for e in events) if tool_case=='timer' else any((f.get('metadata',{}).get('weather') or {}).get('kind')=='forecast' for f in cards()) if tool_case=='forecast' else any(f.get('type')=='timer_widget' for f in cards())
                    if ready:break
                    await asyncio.sleep(.2)
                await asyncio.sleep(4)
                if tool_case=='continuity' and ready:
                    for phrase,tool in [('Сколько осталось на таймере?','timer_status'),('Отмени таймер.','timer')]:
                        pcm,rate=await asyncio.to_thread(Speech().denis_sync,phrase)
                        original=np.frombuffer(pcm,dtype=np.int16)
                        microphone.pcm=np.interp(np.arange(int(len(original)*48000/rate))*rate/48000,np.arange(len(original)),original).astype(np.int16)
                        seen=len(events);until=time.monotonic()+9
                        while time.monotonic()<until:
                            if any(e['type']=='local_tool_status' and e.get('data',{}).get('state')=='completed' and e['data'].get('tool')==tool for e in events[seen:]):break
                            await asyncio.sleep(.2)
                        await asyncio.sleep(2)
                report['input_transcript']=''.join(e.get('data',{}).get('text','') for e in events if e['type']=='live_input_delta')
                output=''.join(e.get('data',{}).get('text','') for e in events if e['type']=='text_delta')
                report['output_transcript']=output.replace(profile.weather.location_name,'<configured location>')[:1800]
                report['timer_widget']=any(f.get('type')=='timer_widget' for f in cards())
                report['timer_expired']=any(e['type']=='timer_expired' for e in events)
                report['forecast_card']=any((f.get('metadata',{}).get('weather') or {}).get('kind')=='forecast' for f in cards())
                report['forecast_days']=[len((f.get('metadata',{}).get('weather') or {}).get('days',[])) for f in cards() if f.get('type')=='weather_card']
                report['cancel_confirmed']=any(e['type']=='timer_state' and e.get('data',{}).get('cancelled_ids') for e in events)
                report['tool_stages']=[e['data'] for e in events if e['type']=='local_tool_status']
                report['expert_jobs']=sum(e['type']=='expert_job' for e in events)
                report['backend_calls_started']=sum(e['type']=='backend_status' and e['data'].get('state')=='running' for e in events)
                report['decoded_audible_frames']=len(received)
                report['first_decoded_audio_after_input_ms']=round((received[0]-requested)*1000,2) if received else None
                report['useful_word_ms']=None
                report['event_types']=sorted({e['type'] for e in events})
                return report
            if voice_expert:
                requested=time.monotonic();microphone.pcm=samples
                deadline=requested+65
                while time.monotonic()<deadline:
                    jobs=[e.get('data',{}).get('job',{}) for e in events if e['type']=='expert_job']
                    if any(j.get('state') in {'completed','failed','timed_out'} for j in jobs):break
                    await asyncio.sleep(.2)
                jobs=[e.get('data',{}).get('job',{}) for e in events if e['type']=='expert_job']
                report['expert_unique_jobs']=len({j.get('job_id') for j in jobs})
                report['expert_states']=list(dict.fromkeys(j.get('state') for j in jobs))
                report['expert_actual']=jobs[-1].get('expert') if jobs else None
                report['native_input_transcript']=''.join(e.get('data',{}).get('text','') for e in events if e['type']=='live_input_delta')
                result_events=[e for e in events if e['type']=='expert_result']
                report['expert_result_card']=bool(result_events)
                report['expert_elapsed_ms']=round((time.monotonic()-requested)*1000,2)
                await asyncio.sleep(8)
                report['decoded_audible_frames']=len(received)
                report['event_types']=sorted({e['type'] for e in events})
                return report
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
    parser=argparse.ArgumentParser();parser.add_argument('--real',action='store_true');parser.add_argument('--voice-expert',action='store_true');parser.add_argument('--tool-case',choices=['timer','forecast','continuity']);args=parser.parse_args()
    if not args.real:raise SystemExit('Use --real only with owner-approved bounded developer budget')
    result=asyncio.run(run(args.voice_expert,args.tool_case))
    target=ROOT/('docs/live-tool-'+args.tool_case+'.json' if args.tool_case else 'docs/live-expert-acceptance.json' if args.voice_expert else 'docs/live-acceptance.json');target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
