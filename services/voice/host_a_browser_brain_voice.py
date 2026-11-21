"""HOST-A Browser Voice Lab adapter for the EXISTING GoBot Brain and Speech.

No second Brain implementation: imports exactly gobot.brain.Service,
gobot.models.VoiceRequest and gobot.pipeline.voiced_events.
Existing local tools/ACL via Service.events in auto mode; chat goes via
existing fast_stream when no deterministic tool applies.

Isolated temporary Brain sqlite + archive is deleted on server shutdown.
Only numeric stage measurements are persisted by Browser Lab. The user
text/audio is never logged by this adapter.
"""
from __future__ import annotations

from dataclasses import replace
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time

MAIN = Path(__file__).resolve().parents[3] / "GoBotHome"
if not (MAIN / "services" / "brain" / "gobot" / "brain.py").is_file():
    raise RuntimeError("existing_gobot_brain_import_root_missing")
sys.path.insert(0, str(MAIN / "services" / "brain"))

from gobot.config import load
from gobot.brain import Service
from gobot.audio import Speech
from gobot.models import VoiceRequest
from gobot.pipeline import voiced_events
from gobot.quick_intents import resolve_quick
from host_a_browser_usage_probe import RealtimeUsageTap

CHAT_MODEL = "gpt-4.1-mini"
TTS_MODEL = "gpt-realtime-2.1-mini"
MAX_TTS_CHARACTERS = 180
MAX_BRAIN_TTS_SECONDS = 36


class BrowserBrainVoice:
    def __init__(self, *, key_loader):
        self.key_loader = key_loader
        self.private = tempfile.TemporaryDirectory(
            prefix="gobot-host-a-browser-real-", ignore_cleanup_errors=True)
        original = Path.cwd()
        # The existing GoBot Brain uses ROOT-relative controlled resources.
        # This changes cwd only within the isolated Browser Lab process.
        os.chdir(MAIN)
        try:
            loaded = load()
            api_key = key_loader()
            if not api_key or not api_key.startswith("sk-"):
                raise PermissionError("browser_openai_key_not_configured")
            settings = replace(
                loaded,
                db=str(Path(self.private.name) / "brain.sqlite"),
                fast_provider="openai",
                api_model=CHAT_MODEL,
                api_key=api_key,
                allow_paid=True,
                timeout=30,
            )
            self.brain = Service(settings)
            self.tts_meter = RealtimeUsageTap()
            # Existing Speech/SpeechTurn stay the official audio engine.
            # A-only transparent socket adapter only observes response.done.
            self.speech = Speech(
                api_key=api_key, connector=self.tts_meter.connector)
            self.current_chat_input_est = 0
            self.current_chat_output_est = 0
            self.current_model_provider = "unknown"
            self.ready = True
        except BaseException:
            os.chdir(original)
            self.private.cleanup()
            raise

    async def response(self, *, question: str, device_id: str,
                       conversation_id: str, turn_id: str):
        if (not isinstance(question, str) or
                not 1 <= len(question) <= 300):
            raise ValueError("brain_question_outside_bounds")
        # Route deterministic clock/timers/settings through EXISTING
        # SmartRouter and LocalTools. Other free-form questions use the
        # existing fast_stream OpenAI Chat Completions integration.
        # No bridge/expert fallback and no other third-party executors.
        quick = resolve_quick(question, {})
        req = VoiceRequest(
            text=question,
            device_id=device_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            correlation_id=turn_id,
            utterance_id=turn_id,
            provider="openai",
            route="fast",
            mode="auto" if quick is not None else None,
            remember=False,
            new_topic=False,
            usage_consent=True,
            paid_chat_consent=True,
            expensive_fallback_approved=False,
            paid_tts_consent=True,
            tts_provider="openai",
            tts_voice="marin",
            tts_character_limit=MAX_TTS_CHARACTERS,
            speak=True,
            client_kind="device",
        )
        self.tts_meter.begin_turn()
        self.current_chat_input_est = 0
        self.current_chat_output_est = 0
        self.current_model_provider = "unknown"
        # Estimate Chat Completions tokens from the original Brain prompt;
        # the existing streaming provider does NOT surface token usage.
        # This is clearly labeled an estimate, not an API billing record.
        try:
            import tiktoken
            from gobot.context_manager import RUNTIME
            encoding = tiktoken.encoding_for_model(CHAT_MODEL)
            c = self.brain.memory.context(req)
            context = "\n".join(str(msg.get("content",""))
                                for msg in c.get("messages",[]))
            context += "\n"+str(c.get("summary",""))
            self.current_chat_input_est = len(
                encoding.encode(RUNTIME+"\n"+context+"\n"+question))
        except Exception:
            # Safe fallback overstates the likely short prompt cost.
            self.current_chat_input_est = 10000
        replay = await self.brain.prepare(req)
        started = time.monotonic()
        generator = voiced_events(
            self.brain, self.speech, req,
            speak=True, tts_provider="openai", tts_voice="marin",
            paid_tts_consent=True,
            replay=replay, prepared=True,
            tts_character_limit=MAX_TTS_CHARACTERS,
        )
        try:
            async with asyncio.timeout(MAX_BRAIN_TTS_SECONDS):
                async for item in generator:
                    if item.get("type") == "final":
                        data=item.get("data") or {}
                        self.current_model_provider=str(
                            data.get("provider") or "unknown")
                        if self.current_model_provider=="openai":
                            try:
                                import tiktoken
                                encoding=tiktoken.encoding_for_model(CHAT_MODEL)
                                self.current_chat_output_est=len(encoding.encode(
                                    str(data.get("text") or "")))
                            except Exception:
                                self.current_chat_output_est=700
                        else:
                            self.current_chat_input_est=0
                            self.current_chat_output_est=0
                    yield item
        finally:
            await generator.aclose()

    def usage_snapshot(self):
        return {
            "tts_reports": self.tts_meter.usage(),
            "chat_input_estimated_tokens": self.current_chat_input_est,
            "chat_output_estimated_tokens": self.current_chat_output_est,
            "chat_provider": self.current_model_provider,
        }

    def close(self):
        self.private.cleanup()
