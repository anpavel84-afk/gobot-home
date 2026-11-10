"""One Brain iterator and an ordered sentence/audio queue for every client transport."""
import asyncio
import base64
import time
from uuid import uuid4

from .processes import AgentError
from .speech_formatter import SpeechFormatter

async def voiced_events(service, speech, request, *, speak=True, tts_provider="openai",
                        tts_voice="marin", paid_tts_consent=False,replay=None,prepared=False):
    if not prepared:replay = await service.prepare(request)
    output = asyncio.Queue(maxsize=16)
    sentences = asyncio.Queue(maxsize=4)
    start = time.perf_counter()
    text_final = None
    seq = 0
    audio_id = str(uuid4())
    tts_failed = False
    audio_cancel = asyncio.Event()
    measurements={}
    formatter=SpeechFormatter()
    def audio_event(kind, **data):
        return {'type':kind,'data':data,**{name:getattr(request,name) for name in
                ('correlation_id','device_id','conversation_id','turn_id')}}

    async def produce_text():
        nonlocal text_final
        sentences_closed=False
        iterator = service.events(request, replay)
        try:
            async for item in iterator:
                if item.type=='tool_status' and item.data.get('status')=='speech_input_complete':
                    if not sentences_closed:await sentences.put(None);sentences_closed=True
                    continue
                if item.type == "final":
                    text_final = item.model_dump()
                else:
                    await output.put(item.model_dump())
                if item.type == "sentence_ready" and speak and not tts_failed and not replay and not sentences_closed:
                    measurements.setdefault('first_sentence_ready',(time.perf_counter()-start)*1000)
                    await sentences.put(item.data["text"])
                if item.type in {"error", "cancelled"}:
                    audio_cancel.set()
                    await output.put(audio_event('audio_stop',audio_id=audio_id,reason=item.type))
            if not sentences_closed:await sentences.put(None)
        finally:
            await iterator.aclose()

    async def consume_audio(synthesizer):
        nonlocal seq, tts_failed
        first = True;segment_sequence=0
        while True:
            text = await sentences.get()
            if text is None:
                break
            if tts_failed or audio_cancel.is_set():
                continue
            segment_id=None
            try:
                text=formatter.format(text)
                if not text:continue
                segment_id=audio_id+':'+str(segment_sequence);segment_sequence+=1
                service.memory.archive.speech(request,segment_id,segment_sequence,text,'submitted_to_tts')
                synthesis_started=time.perf_counter()
                if first:await output.put(audio_event('tts_status',status='preparing',provider=tts_provider))
                async for pcm, rate in synthesizer.synthesize(text, tts_provider, tts_voice, paid_consent=paid_tts_consent):
                    if audio_cancel.is_set():
                        break
                    if first:
                        measurements['tts_first_chunk']=(time.perf_counter()-synthesis_started)*1000
                        measurements['first_audio_server']=(time.perf_counter()-start)*1000
                        await output.put(audio_event('audio_start',audio_id=audio_id,provider=tts_provider,
                                                    voice=tts_voice,first_chunk_ms=(time.perf_counter()-start)*1000))
                        first = False
                    await output.put(audio_event('audio_chunk',audio_id=audio_id,segment_id=segment_id,segment_sequence=segment_sequence,seq=seq,sample_rate=rate,
                                                 format='pcm_s16le',pcm=base64.b64encode(pcm).decode()))
                    seq += 1
                service.memory.archive.speech(request,segment_id,segment_sequence,text,'generated' if not audio_cancel.is_set() else 'interrupted')
            except AgentError as error:
                if segment_id:service.memory.archive.speech(request,segment_id,segment_sequence,text,'failed')
                tts_failed = True
                await output.put(audio_event('tts_error',provider=tts_provider,code=error.code,fallback_used=False))
            except Exception:
                if segment_id:service.memory.archive.speech(request,segment_id,segment_sequence,text,'failed')
                tts_failed = True
                await output.put(audio_event('tts_error',provider=tts_provider,code='tts_failed',fallback_used=False))
            except asyncio.CancelledError:
                if segment_id:service.memory.archive.speech(request,segment_id,segment_sequence,text,'interrupted')
                raise
        if speak:
            await output.put(audio_event('audio_stop',audio_id=audio_id,reason='finished' if not tts_failed else 'tts_error'))

    async def produce_audio():
        if not hasattr(speech,'turn'):return await consume_audio(speech)
        async with speech.turn() as synthesizer:
            # Handshake only: no response.create, no placeholder speech, no retries.
            # It is allowed solely for this owner's explicit per-request speech consent.
            prepare=None
            if speak and paid_tts_consent and not replay and tts_provider=='openai':
                prepare=asyncio.create_task(synthesizer.prepare(tts_provider,tts_voice,paid_consent=True))
            try:await consume_audio(synthesizer)
            finally:
                if prepare is not None:prepare.cancel();await asyncio.gather(prepare,return_exceptions=True)

    async def run():
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(produce_text())
                group.create_task(produce_audio())
            if text_final:
                text_final['data']['speech_metrics']=dict(measurements)
                await output.put(text_final)
        finally:
            service.memory.record_metrics(request.turn_id,tts_provider,measurements)
            if asyncio.current_task().cancelling():
                while not output.empty():
                    output.get_nowait()
                output.put_nowait(None)
            else:
                await output.put(None)

    service.active_voice_streams=getattr(service,'active_voice_streams',0)+1
    worker = asyncio.create_task(run())
    try:
        while (item := await output.get()) is not None:
            yield item
        await worker
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        service.active_voice_streams-=1
