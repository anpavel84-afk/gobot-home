"""Free, real existing Brain multi-turn scenario switch (clock -> timer).

Uses exactly the same Service+voiced_events adapter as Browser Voice Lab,
but fake local TTS PCM and no external OpenAI calls or production DB.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services"/"voice"))
from host_a_browser_brain_voice import BrowserBrainVoice
from gobot.models import VoiceRequest


class FakeSpeech:
    async def synthesize(self, text, provider, voice, *, paid_consent=False):
        if (provider,voice,paid_consent)!=("openai","marin",True):
            raise AssertionError("wrong speech route")
        yield bytes(24000),24000


async def main():
    brain=BrowserBrainVoice(key_loader=lambda:"sk-NO-NET-MOCK")
    brain.speech=FakeSpeech()
    try:
        turns=(
            ("Который час?","same-convo-clock"),
            ("Поставь таймер на две минуты","same-convo-timer"),
        )
        events={}
        for question,turn in turns:
            seen=set()
            async for item in brain.response(
                question=question, device_id="free-isolated-owner",
                conversation_id="same-conversation",
                turn_id=turn):
                seen.add(item["type"])
                if item["type"]=="error":
                    raise RuntimeError("brain rejected local scenario: "+
                                       str((item["data"]).get("code")))
            events[turn]=seen
            print("EXISTING_BRAIN_SCENARIO",turn,sorted(seen))
            assert "final" in seen, seen
        # Follow-up context is scoped to same authenticated owner/conversation
        # and remains available to the original GoBot Service (last 6 turns).
        probe=VoiceRequest(
            text="А что дальше?",device_id="free-isolated-owner",
            conversation_id="same-conversation",turn_id="probe-three",
            remember=False)
        context=brain.brain.memory.context(probe)
        joined=" ".join(x["content"] for x in context["messages"])
        assert "Который час" in joined
        assert "Поставь таймер" in joined
        print("EXISTING_BRAIN_MULTITURN_CONTEXT",len(context["messages"]))
        print("EXISTING_BRAIN_SCENARIO_SWITCH_PASS")
    finally:
        brain.close()

if __name__=="__main__":
    asyncio.run(main())
