"""Free existing Brain -> existing voiced_events fixture; no API/COM3."""
import asyncio
import tempfile
from pathlib import Path
import sys
import os
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "services" / "voice"))
from host_a_browser_brain_voice import BrowserBrainVoice


class FakeNaturalSpeech:
    async def synthesize(self, text, provider, voice, *, paid_consent=False):
        assert provider == "openai" and voice == "marin" and paid_consent
        assert len(text) <= 180
        yield bytes(24000), 24000


async def main():
    bridge = BrowserBrainVoice(key_loader=lambda: "sk-fake-not-external")
    bridge.speech = FakeNaturalSpeech()
    try:
        kind_count = {}
        first_audio = False
        final = None
        async for ev in bridge.response(
            question="Который час?", device_id="browser-smoke-test",
            conversation_id="browser-smoke-conversation",
            turn_id="browser-smoke-one"):
            kind = ev.get("type")
            kind_count[kind] = kind_count.get(kind, 0) + 1
            if kind == "audio_chunk":
                first_audio = True
            if kind == "error":
                raise RuntimeError("Existing Brain fixture returned error " +
                                   str(ev.get("data")))
            if kind == "final":
                final = ev.get("data") or {}
        print("EXISTING_BRAIN_VOICED_EVENTS", kind_count)
        print("EXISTING_BRAIN_LOCAL_CLOCK_FINAL", bool(final),
              final.get("provider") if final else None,
              "NATURAL_TTS_TEST_CHUNK", first_audio)
        if not final or not first_audio:
            raise RuntimeError("existing_brain_voice_fixture_incomplete")
    finally:
        bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
