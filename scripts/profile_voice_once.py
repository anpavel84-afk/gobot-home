"""One explicitly approved real cycle. No consent file => no API/CLI calls.

This HTTP driver measures receipt, not iPhone playback. No retries or heavy fallback.
Owner permission is recorded by the operator in ignored run/profiling-consent-v02.json.
"""
import asyncio,hashlib,json,os,sys,time,wave
from pathlib import Path
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]
BASE='https://plan.tailffc57c.ts.net:18786'

async def main():
    consent=ROOT/'run/profiling-consent-v02.json';lock=ROOT/'run/profiling-v02.lock'
    if not consent.exists():raise SystemExit('No explicit profiling budget recorded; zero paid calls made')
    fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    try:
        budget=json.loads(consent.read_text())
        if budget.get('owner_approved') is not True or budget.get('remaining_runs',0)<1 or budget.get('scope')!='openai-stt-agy-flash-openai-tts':raise SystemExit('No remaining approved cycle; zero paid calls made')
        budget['remaining_runs']-=1;temp=consent.with_suffix('.tmp');temp.write_text(json.dumps(budget));temp.replace(consent)
        sys.path.insert(0,str(ROOT/'services/brain'))
        from gobot.audio import Speech
        raw,rate=Speech().denis_sync('Привет. Ответь одним коротким предложением по-русски.')
        import io
        wav=io.BytesIO()
        with wave.open(wav,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(raw)
        ident='approved-profile-'+str(uuid4());turn=str(uuid4());started=time.perf_counter();received={};final=None;text_length=0;sentence_count=0
        async with httpx.AsyncClient(trust_env=False,timeout=60) as client:
            response=await client.post(BASE+'/api/audio/transcribe',params={'provider':'openai','paid_consent':'true','trace_id':ident},headers={'Origin':BASE,'Content-Type':'audio/wav'},content=wav.getvalue());response.raise_for_status()
            stt=response.json();received['stt_final_received_ms']=(time.perf_counter()-started)*1000
            assert stt.get('text','').strip() and stt.get('provider')=='openai'
            async with client.stream('POST',BASE+'/api/chat/stream',headers={'Origin':BASE},json={'text':stt['text'],'mode':'auto','trace_id':ident,'remember':False,'conversation_id':ident,'turn_id':turn,'request_id':turn,'utterance_id':ident,'usage_consent':True,'speak':True,'paid_tts_consent':True,'tts_provider':'openai','tts_voice':'marin','expensive_fallback_approved':False}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):continue
                    item=json.loads(line[6:]);kind=item['type'];data=item.get('data',{})
                    if kind=='text_delta':
                        received.setdefault('first_text_received_ms',(time.perf_counter()-started)*1000);text_length+=len(data.get('text',''))
                        if text_length>300:raise RuntimeError('Short-probe text cap exceeded; disconnected, no retry')
                    if kind=='sentence_ready':
                        sentence_count+=1
                        if sentence_count>2:raise RuntimeError('Short-probe sentence cap exceeded; disconnected, no retry')
                    if kind=='audio_chunk':received.setdefault('first_audio_payload_received_ms',(time.perf_counter()-started)*1000)
                    if kind in {'error','tts_error','cancelled'}:raise RuntimeError('Probe stopped: '+str(data.get('code',kind)))
                    if kind=='final':final=data
            assert final and final.get('model')=='gemini-3.8-flash-low' and 'first_audio_payload_received_ms' in received
            traces=(await client.get(BASE+'/api/telemetry/'+ident)).json()['traces']
        received['cycle_complete_ms']=(time.perf_counter()-started)*1000
        report={'kind':'approved real STT/Flash/TTS, HTTP driver, no acoustic output','route':final.get('provider'),'model':final.get('model'),'question_audio_seconds':len(raw)/(rate*2),'question_sha256':hashlib.sha256(raw).hexdigest(),'response_characters':text_length,'timings':received,'traces':traces,'first_answer_audible_ms':None,'iphone_verified':False,'remaining_budget_runs':budget['remaining_runs'],'retries':0}
        output=ROOT/'docs'/('real-latency-v02-'+str(int(time.time()))+'.json');output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps({'report':output.name,'timings':received,'audible_latency':'not measured','remaining_runs':budget['remaining_runs']}))
    finally:lock.unlink(missing_ok=True)

if __name__=='__main__':asyncio.run(main())
