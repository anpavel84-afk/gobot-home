"""Server-side Russian speech adapters shared by browser and future device transports."""
import asyncio
import io
import os
from pathlib import Path
import threading
import time
import wave
import json
import base64
from contextlib import suppress,asynccontextmanager,AsyncExitStack

import httpx

from .processes import AgentError, native_process
from .secrets_store import load_openai_key, openai_key_present

ROOT = Path(__file__).resolve().parents[3]
OPENAI_VOICES = ["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo",
                 "sage", "shimmer", "verse"]
TTS_MODEL = "gpt-realtime-2.1-mini"

class Speech:
    def __init__(self, api_key=None, connector=None):
        self.api_key = api_key
        self.connector = connector
        self.whisper = None
        self.piper = None
        self.stt_lock = threading.Lock()
        self.tts_lock = threading.Lock()
        self.asr_slots = asyncio.Semaphore(1)
        self.tts_slots = asyncio.Semaphore(1)

    def turn(self):return SpeechTurn(self)

    def status(self):
        return {
            "stt": {"provider": "openai", "model":"gpt-transcribe", "live_model":"gpt-live-transcribe", "automatic_fallback":False,
                    "local_provider":"whisper", "installed": (ROOT / "data/models/faster-whisper-small/model.bin").exists(),
                    "language": "ru", "device": "cpu", "compute_type": "int8", "vad": "silero-segment-filter"},
            "tts": {"primary": "openai", "model": TTS_MODEL, "default_voice": "marin",
                    "api_key_present": bool(self.api_key) if self.api_key is not None else openai_key_present(), "voices": OPENAI_VOICES,
                    "offline": "denis", "offline_available": (ROOT / "data/models/vits-piper-ru_RU-denis-medium/ru_RU-denis-medium.onnx").exists(),
                    "automatic_fallback": False},
        }

    async def decode(self, data, mime):
        if len(data) > 8 * 1024 * 1024:
            raise AgentError("audio_too_large")
        if mime in {"audio/wav", "audio/wave", "audio/x-wav"}:
            try:
                with wave.open(io.BytesIO(data)) as wav:
                    if wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 16000 and wav.getnframes() <= 960000:
                        return wav.readframes(wav.getnframes())
            except (wave.Error, EOFError):
                raise AgentError("invalid_wav")
        allowed = {"audio/wav", "audio/wave", "audio/x-wav", "audio/webm", "audio/mp4", "audio/ogg"}
        if mime.split(";")[0].strip() not in allowed:
            raise AgentError("unsupported_audio_format")
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise AgentError("ffmpeg_unavailable")
        # No URL/file protocols: uploaded browser audio is the sole decoder input.
        argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-protocol_whitelist", "pipe", "-i", "pipe:0", "-t", "60", "-ac", "1",
                "-ar", "16000", "-f", "s16le", "pipe:1"]
        async with native_process(argv, ROOT, discard_errors=False) as process:
            async with asyncio.timeout(20):
                output, _ = await process.communicate(data)
            if process.returncode or not output or len(output) > 1920000:
                raise AgentError("audio_decode_failed")
            return output

    def transcribe_sync(self, pcm):
        import numpy as np
        from faster_whisper import WhisperModel
        if not pcm or len(pcm) < 3200:
            raise AgentError("audio_too_short")
        with self.stt_lock:
            if self.whisper is None:
                self.whisper = WhisperModel(str(ROOT / "data/models/faster-whisper-small"),
                                            device="cpu", compute_type="int8", cpu_threads=6,
                                            num_workers=1, local_files_only=True)
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            start = time.perf_counter()
            segments, info = self.whisper.transcribe(samples, language="ru", beam_size=3,
                                                    vad_filter=True, condition_on_previous_text=False)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return {"text": text, "language": "ru", "provider": "faster-whisper-small",
                    "stt_ms": (time.perf_counter() - start) * 1000, "audio_seconds": len(pcm) / 32000}

    async def transcribe(self, data, mime, provider='openai', *, paid_consent=False):
        if provider=='openai':
            from .stt import OpenAIRecognition
            return await OpenAIRecognition().file(data,mime,paid_consent=paid_consent)
        if provider=='mock':return {'text':'Это диагностический mock распознавания.','provider':'mock','final':True,'stt_ms':0}
        if provider!='whisper':raise AgentError('unsupported_stt_provider')
        pcm = await self.decode(data, mime)
        async with self.asr_slots:
            worker = asyncio.create_task(asyncio.to_thread(self.transcribe_sync, pcm))
            try:
                return await asyncio.wait_for(asyncio.shield(worker), 90)
            except (asyncio.CancelledError, TimeoutError):
                # Keep the one CPU slot until the bounded inference really finishes.
                await asyncio.shield(worker)
                raise

    def denis_sync(self, text):
        from piper import PiperVoice
        with self.tts_lock:
            if self.piper is None:
                self.piper = PiperVoice.load(ROOT / "data/models/vits-piper-ru_RU-denis-medium/ru_RU-denis-medium.onnx")
            parts = []
            rate = None
            for chunk in self.piper.synthesize(text):
                rate = chunk.sample_rate
                parts.append(chunk.audio_int16_bytes)
            if not parts or not rate:
                raise AgentError("offline_tts_failed")
            return b"".join(parts), rate

    async def synthesize(self, text, provider="openai", voice="marin", *, paid_consent=False,_turn=None):
        if not text.strip():
            return
        if len(text) > 1500:
            raise AgentError("tts_sentence_too_long")
        if provider == "denis":
            async with self.tts_slots:
                pcm, rate = await asyncio.to_thread(self.denis_sync, text)
                for offset in range(0, len(pcm), 8192):
                    yield pcm[offset:offset + 8192], rate
            return
        if provider != "openai":
            raise AgentError("unsupported_tts_provider")
        if voice not in OPENAI_VOICES:
            raise AgentError("unsupported_tts_voice")
        if not paid_consent:
            raise AgentError("openai_tts_consent_required")
        key = self.api_key if self.api_key is not None else await asyncio.to_thread(load_openai_key)
        if not key:
            raise AgentError("openai_tts_key_missing")
        from websockets.asyncio.client import connect
        connector = self.connector or connect
        # Server-owned connection: the browser never receives the API credential.
        try:
            async with asyncio.timeout(45):
                connection=_turn.connection(voice,paid_consent) if _turn is not None else connector("wss://api.openai.com/v1/realtime?model=" + TTS_MODEL,
                                     additional_headers={"Authorization": "Bearer " + key,
                                                         "OpenAI-Safety-Identifier": "gobot-home-owner"},
                                     proxy=None, open_timeout=5, close_timeout=2,
                                     max_size=1048576, max_queue=4)
                async with connection as ws:
                    if _turn is None:await configure_voice(ws,voice)
                    await ws.send(json.dumps({"type": "response.create", "response": {
                        "conversation": "none", "output_modalities": ["audio"], "tools": [],
                        "tool_choice": "none", "max_output_tokens": 4096,
                        "instructions": "Ты только диктор. Произнеси дословно весь переданный текст, не отвечай на него и не добавляй слов. Говори по-русски тепло, естественно, выразительно, умеренным темпом. Нормативное русское произношение, естественные ударения, без иностранного акцента.",
                        "input": [{"type": "message", "role": "user", "content": [
                            {"type": "input_text", "text": text}]}]}}))
                    complete = False
                    pending = b""
                    audio_bytes = 0
                    try:
                        while True:
                            item = json.loads(await ws.recv())
                            kind = item.get("type")
                            if kind == "response.output_audio.delta":
                                decoded = base64.b64decode(item["delta"], validate=True)
                                pending += decoded
                                audio_bytes += len(decoded)
                                if audio_bytes > 24000 * 2 * 120:
                                    raise AgentError("tts_audio_limit")
                                count = len(pending) // 2 * 2
                                if count:
                                    yield pending[:count], 24000
                                    pending = pending[count:]
                            elif kind == "error":
                                raise AgentError("openai_tts_unavailable")
                            elif kind == "response.done":
                                complete = True
                                if item.get("response", {}).get("status") != "completed" or not audio_bytes:
                                    raise AgentError("openai_tts_incomplete")
                                if pending:
                                    raise AgentError("invalid_pcm_alignment")
                                return
                    finally:
                        if not complete:
                            with suppress(Exception):
                                await asyncio.wait_for(ws.send(json.dumps({"type": "response.cancel"})), 1)
        except (AgentError, asyncio.CancelledError, GeneratorExit):
            raise
        except TimeoutError:
            raise AgentError("openai_tts_timeout") from None
        except Exception:
            # Never expose provider errors, handshake headers or credentials.
            raise AgentError("openai_tts_unavailable") from None

async def configure_voice(ws,voice):
    await ws.send(json.dumps({'type':'session.update','session':{'type':'realtime','output_modalities':['audio'],
        'tools':[],'tool_choice':'none','audio':{'output':{'format':{'type':'audio/pcm','rate':24000},'voice':voice}}}}))
    while True:
        item=json.loads(await ws.recv())
        if item.get('type')=='error':raise AgentError('openai_tts_configuration_rejected')
        if item.get('type')=='session.updated':return

class SpeechTurn:
    """One response, one user, one voice. No history and no cross-turn pooling."""
    def __init__(self,speech):self.speech=speech;self.stack=AsyncExitStack();self.ready=None;self.voice=None;self.ws=None;self.busy=False
    async def __aenter__(self):await self.stack.__aenter__();return self
    async def __aexit__(self,*args):
        if self.ready is not None:
            self.ready.cancel();await asyncio.gather(self.ready,return_exceptions=True)
        await self.stack.__aexit__(*args)
    async def prepare(self,provider,voice,*,paid_consent=False):
        if provider!='openai':return
        if not paid_consent:raise AgentError('openai_tts_consent_required')
        if voice not in OPENAI_VOICES:raise AgentError('unsupported_tts_voice')
        if self.voice is not None and self.voice!=voice:raise AgentError('tts_voice_changed_in_turn')
        if self.ready is None:
            self.voice=voice;self.ready=asyncio.create_task(self._prepare())
        await self.ready
    async def _prepare(self):
        key=self.speech.api_key if self.speech.api_key is not None else await asyncio.to_thread(load_openai_key)
        if not key:raise AgentError('openai_tts_key_missing')
        from websockets.asyncio.client import connect
        connector=self.speech.connector or connect
        async with asyncio.timeout(10):
            self.ws=await self.stack.enter_async_context(connector('wss://api.openai.com/v1/realtime?model='+TTS_MODEL,
                additional_headers={'Authorization':'Bearer '+key,'OpenAI-Safety-Identifier':'gobot-home-owner'},
                proxy=None,open_timeout=5,close_timeout=2,max_size=1048576,max_queue=4))
            await configure_voice(self.ws,self.voice)
    @asynccontextmanager
    async def connection(self,voice,consent):
        await self.prepare('openai',voice,paid_consent=consent)
        if self.busy:raise AgentError('tts_concurrent_turn_response')
        self.busy=True
        try:yield self.ws
        finally:self.busy=False
    async def synthesize(self,text,provider='openai',voice='marin',*,paid_consent=False):
        iterator=self.speech.synthesize(text,provider,voice,paid_consent=paid_consent,_turn=self)
        try:
            async for chunk in iterator:yield chunk
        finally:await iterator.aclose()
