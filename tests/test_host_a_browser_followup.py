"""HOST-A Browser Voice Lab natural follow-up tests, ZERO API calls/COM3."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "voice"))
sys.path.insert(0, str(ROOT / "tools"))

from host_a_browser_followup_vad import (
    LocalFollowupVAD, DIALOGUE_IDLE_SECONDS)
from host_a_browser_wake_policy import (
    BrowserAddressMatcher, address_candidate)
from host_a_cloud_transcribe import (
    CloudResult, CloudTranscriber, FollowupPermit, FollowupPosition,
    TranscriptionFault, verify_address)
from host_wake_contract import WakeEvent
from host_a_browser_voice_lab import BrowserVoiceSession


def _wake(epoch="aabbccdd", at=960):
    return WakeEvent(
        stream_epoch=epoch, end_sample_index=at,
        phrase_id="monika", detector_id="vosk-test",
        detected_monotonic_ns=123,
    )


@pytest.mark.parametrize("spoken,expect", [
    ("Моника сколько времени", ("strong", "моника", 0)),
    ("Окей Моника скажи", ("strong", "моника", 1)),
    ("О кей Моника скажи", ("strong", "моника", 2)),
    ("слушай Моника подскажи", ("strong", "моника", 1)),
    ("привет Моника", ("strong", "моника", 1)),
    ("модников скажи пожалуйста", ("weak", "модников", 0)),
    ("маньяка сколько времени", ("weak", "маньяка", 0)),
    ("Окей модика привет", ("weak", "модика", 1)),
    ("По телевизору показывали фильм про Монику", None),
    ("Обрати внимание там модников в середине текста", None),
    ("расскажи про Монику из сериала", None),
    ("на мониторе открыта Моника", None),
    ("монитор сколько времени", None),
    ("модификатор сколько времени", None),
])
def test_browser_first_address_flexible_but_not_arbitrary_mention(spoken,expect):
    assert address_candidate(spoken)==expect


def test_weak_address_two_updates_and_bounded_cloud_probes():
    m = BrowserAddressMatcher(weak_limit=2)
    assert m.feed(text="модников",sample_cursor=960,
                  stream_epoch="ep",updated=True,suppressed=False) is False
    assert m.feed(text="модников скажи",sample_cursor=2880,
                  stream_epoch="ep",updated=True,suppressed=False) is True
    assert m.weak_total == 1
    assert m.feed(text="модников скажи сколько",sample_cursor=3840,
                  stream_epoch="ep",updated=True,suppressed=False) is False
    m.reset()
    m.feed(text="маньяка",sample_cursor=5760,
           stream_epoch="ep",updated=True,suppressed=False)
    assert m.feed(text="маньяка привет",sample_cursor=7680,
                  stream_epoch="ep",updated=True,suppressed=False) is True
    assert m.weak_total == 2
    m.reset()
    m.feed(text="модика",sample_cursor=9000,
           stream_epoch="ep",updated=True,suppressed=False)
    assert m.feed(text="модика сколько",sample_cursor=12000,
                  stream_epoch="ep",updated=True,suppressed=False) is False
    assert m.weak_total == 2


def test_browser_address_suppressed_during_reply():
    m = BrowserAddressMatcher()
    assert m.feed(text="окей моника",sample_cursor=960,
                  stream_epoch="ep",updated=True,suppressed=True) is False
    assert m.feed(text="окей моника продолжи",sample_cursor=2880,
                  stream_epoch="ep",updated=True,suppressed=True) is False


def _vad_frame(level):
    return np.full(960,level,dtype="<i2").tobytes()


def test_local_speech_starts_only_in_idle_window_then_commits_after_silence():
    now=10.0
    vad=LocalFollowupVAD(
        armed_at=now,deadline=now+DIALOGUE_IDLE_SECONDS,
        sample_cursor=0)
    index=0
    def feed(level):
        nonlocal index,now
        now+=.060
        event=vad.feed(pcm=_vad_frame(level),index=index,
                       now=now,rms=abs(level))
        index+=960
        return event
    for _ in range(9):
        assert feed(0) is None
    assert feed(800) is None
    assert feed(800) is None
    start=feed(800)
    assert start is not None and start.kind=="start"
    assert start.replay_start>=0
    assert start.replay_start + len(start.replay_pcm)//2 == index
    for _ in range(8):
        assert feed(800) is None
    for _ in range(13):
        assert feed(0) is None
    stop=feed(0)
    assert stop is not None and stop.kind=="commit_silence"
    assert vad.complete


def test_followup_timeout_leaves_wake_only_without_paid_stt():
    vad=LocalFollowupVAD(
        armed_at=5.0,deadline=5.0+DIALOGUE_IDLE_SECONDS,
        sample_cursor=0)
    frames=0
    decision=None
    while frames <= 275:
        decision=vad.feed(pcm=bytes(1920),index=frames*960,
                          now=5.0+(frames+1)*.06,rms=0.)
        frames+=1
        if decision:break
    assert decision is not None and decision.kind=="expired"
    assert vad.complete and not vad.active


def test_followup_no_stale_or_replayed_paid_permission():
    original=_wake(epoch="ep")
    permit=FollowupPermit(
        initial_wake=original,conversation_id="c1",
        expires_monotonic=100.)
    permit.claim("ep","c1",now=90.)
    with pytest.raises(TranscriptionFault):
        permit.claim("ep","c1",now=91.)
    with pytest.raises(TranscriptionFault):
        FollowupPermit(
            initial_wake=original,conversation_id="c1",
            expires_monotonic=100.).claim("other","c1",now=90.)
    with pytest.raises(TranscriptionFault):
        FollowupPermit(
            initial_wake=original,conversation_id="c1",
            expires_monotonic=100.).claim("ep","c1",now=101.)


def test_true_followup_text_without_name_is_a_separate_verdict():
    assert verify_address("сколько еще частей вышло?")[0] != "CONFIRMED"
    # No unauthenticated convenience path should ever allow this as initial.
    assert verify_address("Моника сколько времени")[0] == "CONFIRMED"


def test_browser_followup_is_armed_only_after_verified_and_playback_ack():
    class Sink:
        def __init__(self): self.messages=[]
        async def send_json(self, msg): self.messages.append(msg)
    class Core:
        sample_cursor=9600
        output_epoch=0
        def playback(self, value,epoch): self.speaking=value
        def __init__(self): self.speaking=True
    class Detector:
        def reset(self):pass
    async def run():
        session=BrowserVoiceSession(Sink(),factory=lambda: None)
        session.core=Core()
        session.detector=Detector()
        session.mode="REAL"
        session.original_wake_event=_wake(epoch=session.epoch)
        session.conversation_verified=True
        session.reply_completed=False
        session.playback_active=True
        session.response_task=asyncio.get_running_loop().create_future()
        await session.handle_control({"type":"playback_drained"})
        assert session.followup_vad is None
        assert session.pending_browser_audio_ack
        assert session.core.speaking is False
        session.response_task=None
        session.reply_completed=True
        assert await session._arm_followup_after_playback()
        assert session.state=="followup"
        assert session.followup_vad is not None
        assert session.followup_permit is not None
        assert session.followup_permit.initial_wake == session.original_wake_event
        assert session.followup_permit.expires_monotonic > time.monotonic()
    asyncio.run(run())


def test_browser_followup_never_arms_without_prior_wake():
    class Sink:
        async def send_json(self, msg):pass
    async def run():
        s=BrowserVoiceSession(Sink(),factory=lambda: None)
        s.mode="REAL"
        s.reply_completed=True
        s.playback_drained_seen=True
        assert not await s._arm_followup_after_playback()
        assert s.followup_vad is None
    asyncio.run(run())

def test_real_stt_followup_without_name_uses_same_parser_and_shared_budget(tmp_path):
    """Fake OpenAI WS, actual A CloudTranscriber; external API is not called."""
    import json
    from host_a_paid_budget import HostPaidTrialBudget

    class FakeWS:
        def __init__(self):
            self.incoming = asyncio.Queue()
            self.config=None
        async def send(self, raw):
            obj=json.loads(raw)
            if obj["type"]=="session.update":
                self.config=obj
                await self.incoming.put(json.dumps({"type":"session.updated"}))
            elif obj["type"]=="input_audio_buffer.append":
                pass
            elif obj["type"]=="input_audio_buffer.commit":
                await self.incoming.put(json.dumps({
                    "type":"input_audio_buffer.committed","item_id":"follow-1"
                }))
                await self.incoming.put(json.dumps({
                    "type":"conversation.item.input_audio_transcription.completed",
                    "item_id":"follow-1","transcript":"А сколько лет главному герою?"
                },ensure_ascii=False))
            else:
                raise AssertionError(obj["type"])
        async def recv(self):
            return await self.incoming.get()

    fake=FakeWS()
    class Connector:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return fake
        async def __aexit__(self,*args):return False

    async def frames():
        if False:
            yield 1

    async def run():
        budget=HostPaidTrialBudget(tmp_path)
        ws=CloudTranscriber(budget,key_loader=lambda: "sk-FAKE",
                            connector=Connector)
        permit=FollowupPermit(
            initial_wake=_wake(epoch="e1"),conversation_id="session-1",
            expires_monotonic=time.monotonic()+16.)
        result=await ws.transcribe_followup(
            permit=permit, conversation_id="session-1", epoch="e1",
            replay_start=1920,replay_pcm16=bytes(1920*3),
            next_frames=frames(), max_session_seconds=20)
        assert result.verdict == "FOLLOWUP"
        assert result.question == "А сколько лет главному герою?"
        assert fake.config["session"]["audio"]["input"]["transcription"]["keywords"] == []
        assert budget.status()["reserved_seconds"] == 20
        assert budget.status()["sessions"][0]["status"] == "COMPLETE"
        with pytest.raises(TranscriptionFault):
            await ws.transcribe_followup(
                permit=permit, conversation_id="session-1", epoch="e1",
                replay_start=1920,replay_pcm16=bytes(1920*3),
                next_frames=frames(), max_session_seconds=20)
        assert len(budget.status()["sessions"])==1
    asyncio.run(run())

@pytest.mark.parametrize("phrase,accepted", [
    ("Окей, Моника, скажи сколько времени", True),
    ("О кей, Моника, сколько времени", True),
    ("Слушай, Моника, какой сегодня день", True),
    ("Моника, сколько времени", True),
    ("По телевизору показывали фильм про Монику", False),
    ("Обрати внимание там модников в середине текста", False),
    ("Модников сколько времени", False),
])
def test_cloud_confirmed_first_name_can_follow_salutation(phrase, accepted):
    verdict, question = verify_address(phrase)
    assert (verdict=="CONFIRMED")==accepted
    if accepted:
        assert question and "моника" not in question

@pytest.mark.parametrize("phrase, expected", [
    ("Привет, Моник, из по этому времени",
     ("weak","моник",1)),
    ("Привет моник сколько времени",
     ("weak","моник",1)),
    ("Привет мой ник сколько времени",
     ("weak","мой ник",1)),
    ("Мой ник сколько времени",
     ("weak","мой ник",0)),
    ("мойка сколько времени",
     ("weak","мойка",0)),
    ("мой сколько времени",
     ("weak","мой",0)),
    ("мой",
     ("weak","мой",0)),
    ("моички сколько времени",
     None),
    ("мойне сколько сейчас",
     ("weak","мойне",0)),
    ("мойник а сколько времени",
     ("weak","мойник",0)),
    ("Привет мойка",
     ("weak","мойка",1)),
    ("расскажи про мой автомобиль",
     None),
    ("по телевизору сказали мой номер",
     None),
    ("проверяем слово модников в середине текста",
     None),
    ("монитор мойка открылась",
     None),
])
def test_owner_monik_moy_aliases_sent_as_weak_candidates(phrase, expected):
    assert address_candidate(phrase) == expected


def test_vosk_same_partial_and_final_must_still_open_weak_candidate():
    m=BrowserAddressMatcher(weak_limit=3)
    phrase="привет моник из по этому времени"
    assert m.feed(text=phrase,sample_cursor=9600,
                  stream_epoch="p",updated=True,
                  suppressed=False,endpoint=False) is False
    # The previous version suppressed this identical FINAL altogether.
    assert m.feed(text=phrase,sample_cursor=10560,
                  stream_epoch="p",updated=True,
                  suppressed=False,endpoint=True) is True
    assert m.last_strength == "weak"
    assert m.last_name == "моник"
    assert m.weak_total == 1


def test_vosk_single_final_only_moy_and_split_moy_nik_are_candidates():
    m=BrowserAddressMatcher(weak_limit=3)
    assert m.feed(text="мой",sample_cursor=3840,stream_epoch="a",
                  updated=True,suppressed=False,endpoint=True) is True
    assert m.last_name=="мой"
    m.reset()
    assert m.feed(text="мой ник сколько времени",sample_cursor=7680,
                  stream_epoch="a",updated=True,suppressed=False,
                  endpoint=True) is True
    assert m.last_name=="мой ник"
    assert m.weak_total==2
    m.reset()
    assert m.feed(text="привет мойка скажи",sample_cursor=11520,
                  stream_epoch="a",updated=True,suppressed=False,
                  endpoint=True) is True
    assert m.weak_total==3
    m.reset()
    assert m.feed(text="мой сколько времени",sample_cursor=14400,
                  stream_epoch="a",updated=True,suppressed=False,
                  endpoint=True) is False
    # The exact name remains a strong candidate even with weak cap full.
    m.reset()
    assert m.feed(text="моника скажи",sample_cursor=16320,
                  stream_epoch="a",updated=True,suppressed=False,
                  endpoint=True) is True


def test_browser_wake_adapter_forwards_final_monik_to_canonical_host_core():
    from host_a_browser_wake_policy import BrowserWakeAdapter
    from host_a_wake_adapter import WakeGate
    from host_wake_core import HostCore
    from host_wake_contract import AudioChunk
    from dataclasses import dataclass
    @dataclass
    class Hypothesis:
        text: str
        endpoint: bool
        updated: bool

    class Decoder:
        def __init__(self):
            self.last_hypothesis=None

    class BBridge:
        def __init__(self):
            self.inner=type("Inner",(),{"lab":Decoder()})()
            self.suppress_events=False
        def feed_chunk(self,chunk):
            self.inner.lab.last_hypothesis=Hypothesis(
                "привет моник из по этому времени", endpoint=True,
                updated=True)
            return None
        def reset(self):
            self.inner.lab.last_hypothesis=None

    gate=WakeGate()
    wrapped=BrowserWakeAdapter(BBridge(),gate,weak_limit=3)
    core=HostCore(wrapped,"abc",allowed_wake_phrases={"monika"})
    frame=bytes(1920)
    events=core.feed({"epoch":"abc","seq":0,"sample_start":0,
                     "sample_count":960},frame,
                     received_monotonic_ns=12345)
    assert events and events[0]["event"]=="wake"
    assert wrapped.last_candidate_token=="моник"
    assert wrapped.last_candidate_kind=="weak"
    item=gate.take()
    assert item is not None and item[0].phrase_id=="monika"
    assert item[1]==0
    core.close()

def test_browser_preroll_retains_name_when_vosk_detects_only_on_final():
    from host_a_wake_adapter import WakeGate
    from host_wake_contract import AudioChunk
    from host_a_cloud_transcribe import MAX_REPLAY_SAMPLES
    from host_wake_contract import WakeEvent

    browser=WakeGate(capacity_samples=80000)
    physical_default=WakeGate()
    assert physical_default.capacity_samples==MAX_REPLAY_SAMPLES==32000
    assert browser.capacity_samples==80000
    # Vosk emits only a single final hypothesis after 4.5 seconds of speech.
    # Local Browser Lab must retain the first syllables for cloud verification.
    first=(1).to_bytes(2,"little",signed=True)*960
    for seq in range(75):
        chunk=AudioChunk(first,"br",seq*960,seq+1)
        event=(WakeEvent(
            stream_epoch="br",
            end_sample_index=chunk.end_sample_index,
            phrase_id="monika",detector_id="browser",
            detected_monotonic_ns=seq+1)
            if seq==74 else None)
        browser.feed(chunk,event)
        physical_default.feed(chunk,event)
    _,br_start,br_pcm=browser.take()
    _,old_start,old_pcm=physical_default.take()
    assert br_start==0
    assert len(br_pcm)//2==75*960
    assert old_start>0
    assert len(old_pcm)//2<=32000
    assert br_pcm[:1920]==first


def test_real_transcriber_browser_explicit_replay_cap_5s():
    from host_a_cloud_transcribe import (
        MAX_REPLAY_SAMPLES, MAX_BROWSER_REPLAY_SAMPLES)
    from host_a_paid_budget import HostPaidTrialBudget
    # Any physical caller gets 2s default. Browser factory explicitly opts
    # into 5s while maintaining the 15s max total input/cloud budget.
    budget=HostPaidTrialBudget(Path(__file__).resolve().parent)
    default=CloudTranscriber(budget,key_loader=lambda:"sk-MOCK")
    browser=CloudTranscriber(
        budget,key_loader=lambda:"sk-MOCK",
        max_replay_samples=MAX_BROWSER_REPLAY_SAMPLES)
    assert default.max_replay_samples==MAX_REPLAY_SAMPLES==32000
    assert browser.max_replay_samples==MAX_BROWSER_REPLAY_SAMPLES==80000
    with pytest.raises(ValueError):
        CloudTranscriber(budget,key_loader=lambda:"sk-MOCK",
                         max_replay_samples=160000)
