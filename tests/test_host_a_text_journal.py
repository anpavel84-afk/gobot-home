"""Local HOST-A full speech-text journal acceptance tests — no cloud."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "voice"))
from host_a_text_journal import LocalConversationJournal, SCHEMA


def _read(path):
    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]


def test_full_text_and_latency_are_saved_locally(tmp_path):
    async def run():
        log = LocalConversationJournal(
            tmp_path / "private-conversations",
            session="aabbccddeeff001122334455", mode="REAL")
        log.start()
        log.record_vosk(text="модников", final=False,
                        offset_ms=200, sample_cursor=960, frame_seq=1,
                        rms_dbfs=-20.3, turn=0)
        log.record_vosk(text="модников", final=False,
                        offset_ms=220, sample_cursor=1920, frame_seq=2,
                        rms_dbfs=-21.1, turn=0)
        log.record_vosk(text="маньяка моника", final=True,
                        offset_ms=420, sample_cursor=3840, frame_seq=4,
                        rms_dbfs=-19.2, turn=0)
        log.record("wake", offset_ms=500, turn=1, local=True)
        log.record("wake_candidate", offset_ms=501, turn=1,
                   text="моника сколько времени")
        log.record("cloud_connect_start", offset_ms=504, turn=1)
        log.record("cloud_ready", offset_ms=950, turn=1, setup_ms=446)
        log.record("cloud_partial", offset_ms=1320, turn=1,
                   text="Моника, ск")
        log.record("cloud_partial", offset_ms=1450, turn=1,
                   text="олько времени")
        log.record("cloud_final", offset_ms=1800, turn=1,
                   text="Моника, сколько времени?")
        log.record("cloud_verdict", offset_ms=1810, turn=1,
                   status="CONFIRMED", text="Моника, сколько времени?")
        log.record("brain_question", offset_ms=4050, turn=1,
                   question="сколько времени")
        log.record("brain_start", offset_ms=4070, turn=1,
                   provider="original_gobot_brain")
        log.record("brain_first_text", offset_ms=4300, turn=1)
        log.record("brain_delta", offset_ms=4320, turn=1,
                   text="Сейчас ")
        log.record("brain_delta", offset_ms=4350, turn=1,
                   text="девять утра.")
        log.record("brain_sentence", offset_ms=4450, turn=1,
                   text="Сейчас девять утра.")
        log.record("tts_first_audio", offset_ms=5250, turn=1)
        log.record("brain_final", offset_ms=5700, turn=1,
                   text="Сейчас девять утра.", provider="local")
        log.record("playback_drained", offset_ms=8000, turn=1,
                   status="confirmed_by_browser")
        # Arbitrary unapproved fields must never leak credentials/audio.
        log.record("debug", offset_ms=8100, turn=1, text="OK",
                   Authorization="Bearer sk-private-test",
                   api_key="sk-private-test", pcm=b"raw-audio",
                   secret_header="sk-private-test")
        log.summarize_turn(1)
        await log.close()
        assert log.snapshot()["complete_so_far"], log.snapshot()
        entries = _read(log.path)
        assert entries[0]["stage"] == "session_start"
        assert entries[-1]["stage"] == "session_end"
        assert entries[-1]["complete"] is True
        stages = [x["stage"] for x in entries]
        assert "wake_candidate" in stages
        assert stages.count("vosk_partial") == 1
        assert stages.count("vosk_final") == 1
        assert stages.count("cloud_partial") == 2
        assert stages.count("brain_delta") == 2
        assert [x["text"] for x in entries
                if x["stage"] == "cloud_partial"] == [
                    "Моника, ск", "олько времени"]
        assert [x["question"] for x in entries
                if x["stage"] == "brain_question"] == ["сколько времени"]
        analysis = next(x for x in entries
                        if x.get("stage") == "turn_analysis"
                        and "latency_ms" in x)
        assert analysis["cloud_transcript"] == "Моника, сколько времени?"
        assert analysis["answer"] == "Сейчас девять утра."
        assert analysis["latency_ms"]["stt_final_to_brain_ms"] == 2270
        assert analysis["latency_ms"]["wake_to_first_audio_ms"] == 4750
        assert "cloud_to_brain_handoff_over_1000ms" in analysis["findings"]
        assert "wake_to_first_audio_over_3000ms" in analysis["findings"]
        raw = log.path.read_text(encoding="utf-8")
        assert "модников" in raw and "маньяка" in raw
        assert "sk-private-test" not in raw
        assert "raw-audio" not in raw
        assert 'Authorization' not in raw

    asyncio.run(run())


def test_cloud_rejected_turn_analysis_no_brain(tmp_path):
    async def run():
        log = LocalConversationJournal(
            tmp_path, session="1234567890abcdef12345678", mode="REAL")
        log.start()
        log.record("wake", offset_ms=1000, turn=1)
        log.record("cloud_final", offset_ms=1900, turn=1,
                   text="какой-то фильм про монику")
        log.record("cloud_rejected", offset_ms=1970, turn=1,
                   status="UNCERTAIN")
        log.summarize_turn(1)
        await log.close()
        analysis = [x for x in _read(log.path)
                    if x.get("stage") == "turn_analysis"
                    and "latency_ms" in x]
        assert len(analysis) == 1
        assert analysis[0]["status"] == "NOT_CONFIRMED_UNCERTAIN"
        assert "cloud_name_not_confirmed" in analysis[0]["findings"]
        assert analysis[0]["question"] is None
        assert not any(x["stage"] == "brain_question"
                       for x in _read(log.path))
    asyncio.run(run())


def test_mock_logging_no_cloud_stays_local(tmp_path):
    async def run():
        log = LocalConversationJournal(
            tmp_path, session="00112233445566778899aabb", mode="MOCK")
        log.start()
        log.record("ready", offset_ms=20, turn=0, mode="MOCK")
        log.record_vosk(
            text="моника сколько", final=False, offset_ms=900,
            sample_cursor=960, frame_seq=5, rms_dbfs=-30.0, turn=0)
        log.record("cloud_partial", offset_ms=1100, turn=1,
                   text="моника сколько", mock=True)
        await log.close()
        data = _read(log.path)
        assert data[0]["mode"] == "MOCK"
        assert data[-1]["complete"] is True
        assert any(x["stage"] == "vosk_partial" for x in data)
        assert any(x.get("mock") is True for x in data)
    asyncio.run(run())

def test_asr_emitted_stage_keyword_does_not_crash_or_change_journal_kind(tmp_path):
    """Regression for real phone crash: emit('asr', stage='partial', text=...)."""
    from host_a_browser_voice_lab import BrowserVoiceSession

    class FakeSocket:
        def __init__(self): self.messages = []
        async def send_json(self, value): self.messages.append(value)

    async def run():
        socket = FakeSocket()
        browser = BrowserVoiceSession(socket, factory=lambda: None)
        browser.journal = LocalConversationJournal(
            tmp_path, session=browser.epoch, mode="REAL")
        browser.journal.start()
        # Reproduce the actual Vosk emissions of the 2026-11-17 incident.
        await browser.emit("asr", text="модников", stage="partial",
                           engine="vosk-small-ru-0.22", actual=True)
        await browser.emit("asr", text="моника сколько времени",
                           stage="final", engine="vosk-small-ru-0.22",
                           actual=True)
        assert socket.messages[0]["stage"] == "partial"
        assert socket.messages[1]["stage"] == "final"
        await browser.journal.close()
        rows = _read(browser.journal.path)
        assert [r["stage"] for r in rows if r["stage"] == "asr"] == [
            "asr", "asr"]
        assert [r["text"] for r in rows if r["stage"] == "asr"] == [
            "модников", "моника сколько времени"]
        assert rows[-1]["complete"] is True

    asyncio.run(run())
