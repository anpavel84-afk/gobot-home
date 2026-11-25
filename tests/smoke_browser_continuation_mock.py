"""One complete in-memory MOCK follow-up turn through actual HostCore+Vosk.

Simulates an already verified initial Monika wake and browser speaker ACK.
Then local PCM speech -> local VAD -> same A CloudTranscriber mock protocol ->
fallback browser speech -> second in-dialogue listening window. No paid API.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import numpy as np

A=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(A/"services"/"voice"))
sys.path.insert(0,str(A/"tools"))
from host_a_browser_voice_lab import (
    BrowserVoiceSession, B_ROOT, MODELS, B_SITE)
from host_monika_runtime import make_owner_authorized_factory
from host_wake_contract import WakeEvent


class FakeBrowser:
    def __init__(self):
        self.messages=[]
    async def send_json(self, message):
        self.messages.append(message)
    async def send_bytes(self, data):
        pass


async def run():
    ws=FakeBrowser()
    factory=make_owner_authorized_factory(B_ROOT,MODELS,B_SITE)
    s=BrowserVoiceSession(ws,factory=factory)
    assert await s.on_hello({
        "type":"hello", "source":"BROWSER_MIC",
        "sink":"BROWSER_AUDIO", "mode":"MOCK",
        "sample_rate":16000,
    })
    original=WakeEvent(
        stream_epoch=s.epoch,end_sample_index=960,
        phrase_id="monika",detector_id="vosk-fake-original",
        detected_monotonic_ns=100,
    )
    s.original_wake_event=original
    s.conversation_verified=True
    s.reply_completed=True
    s.playback_active=True
    s.current_turn_kind="wake"
    s.core.playback(True,s.core.output_epoch)
    await s.handle_control({"type":"playback_drained"})
    assert s.state=="followup" and s.followup_vad is not None
    s.followup_vad.armed_at -= 1.0  # waive 400ms speaker echo guard
    s.followup_vad.deadline -= 1.0

    voiced=np.full(960,2500,dtype="<i2").tobytes()
    for _ in range(7):
        await s._process_one(bytes(1920))
    for _ in range(20):
        await s._process_one(voiced)
    for _ in range(20):
        await s._process_one(bytes(1920))
    await asyncio.sleep(1.0)
    steps=[v.get("type") for v in ws.messages]
    print("MOCK_CONTINUATION_EVENTS",[
        t for t in steps if t in (
            "followup_wait", "followup_speech_start",
            "followup_audio_commit","cloud_partial", "cloud_final",
            "mock_speaker","error","wake"
        )])
    if any(v.get("type")=="error" for v in ws.messages):
        print("MOCK_CONTINUATION_ERRORS",[
            v.get("code") for v in ws.messages if v.get("type")=="error"])
    assert "followup_speech_start" in steps
    assert "followup_audio_commit" in steps
    assert "mock_speaker" in steps
    assert "error" not in steps
    assert s.turn_count==1
    await s.handle_control({"type":"playback_drained"})
    await asyncio.sleep(.05)
    assert s.state=="followup"
    assert s.followup_permit is not None and not s.followup_permit.consumed
    # Silence eventually returns to wake-only without closing mic.
    s.followup_vad.deadline=s.followup_vad.armed_at+.50
    await asyncio.sleep(.6)
    await s._process_one(bytes(1920))
    steps=[v.get("type") for v in ws.messages]
    assert "followup_expired" in steps
    assert s.state=="ready"
    assert s.followup_vad is None
    s.core.close()
    await s.journal.close()
    print("MOCK_FOLLOWUP_VAD_CLOUD_BRAIN_QUEUE_PASS")


if __name__=="__main__":
    asyncio.run(run())
