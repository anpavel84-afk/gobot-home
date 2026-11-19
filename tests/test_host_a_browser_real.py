"""HOST-A REAL Browser Lab safety/owner grant tests. No OpenAI connection."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile

import pytest

A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "services" / "voice"))
sys.path.insert(0, str(A / "tools"))
from host_a_paid_budget import HostPaidTrialBudget, BudgetError
from host_a_cloud_transcribe import verify_address
from host_a_browser_voice_lab import BrowserVoiceSession


class Sink:
    def __init__(self):
        self.events = []

    async def send_json(self, obj):
        self.events.append(obj)


def test_browser_grant_shares_exact_existing_stt_ledger(tmp_path):
    budget = HostPaidTrialBudget(tmp_path)
    old_id = budget.reserve("gpt-live-transcribe", 30,
                            local_wake_confirmed=True)
    budget.finish(old_id, elapsed_seconds=2, result="COMPLETE")
    dialogue = budget.reserve_browser_dialog()
    budget.finish(dialogue, elapsed_seconds=3, result="COMPLETE")
    data = budget.status()
    assert data["reserved_seconds"] == 120
    assert data["reserved_estimated_usd"] == 0.3585
    assert data["sessions"][1]["model"] == (
        "brain-gpt-4.1-mini+tts-gpt-realtime-2.1-mini")


def test_no_double_charge_reusing_browser_close(tmp_path):
    budget = HostPaidTrialBudget(tmp_path)
    ident = budget.reserve_browser_dialog()
    budget.finish(ident, elapsed_seconds=7, result="CANCELLED")
    with pytest.raises(BudgetError):
        budget.finish(ident, elapsed_seconds=7, result="COMPLETE")
    assert budget.status()["reserved_estimated_usd"] == 0.35


def test_browser_dialog_max_eight_and_estimate_limit(tmp_path):
    budget = HostPaidTrialBudget(tmp_path)
    for i in range(8):
        budget.reserve_browser_dialog()
    assert budget.status()["reserved_estimated_usd"] == 2.8
    with pytest.raises(BudgetError, match="browser_real_turn_count_limit"):
        budget.reserve_browser_dialog()


def test_browser_real_explicit_paid_consent_required():
    sink = Sink()
    session = BrowserVoiceSession(sink, factory=lambda: None)
    async def check():
        return await session.on_hello({
            "type": "hello", "source": "BROWSER_MIC",
            "sink": "BROWSER_AUDIO", "mode": "REAL",
            "sample_rate": 16000, "paid_consent": False,
        })
    assert asyncio.run(check()) is False
    assert sink.events[-1]["code"] == "PAID_BROWSER_CONSENT_REQUIRED"
    assert session.brain is None


def test_browser_refuses_untrusted_spotpear_source_without_device_access():
    sink = Sink()
    session = BrowserVoiceSession(sink, factory=lambda: None)
    async def check():
        return await session.on_hello({
            "type": "hello", "source": "SPOTPEAR_WSS",
            "sink": "BROWSER_AUDIO", "mode": "REAL",
            "sample_rate": 16000, "paid_consent": True,
        })
    assert asyncio.run(check()) is False
    assert sink.events[-1]["code"] == "BROWSER_MIC_AUDIO_ONLY"
    assert session.brain is None


def test_cloud_weak_asr_not_authoritative():
    assert verify_address("маньяка сколько времени")[0] != "CONFIRMED"
    assert verify_address("моник сколько времени")[0] != "CONFIRMED"
    assert verify_address("фильм про монику")[0] != "CONFIRMED"
    assert verify_address("Моника, сколько времени?")[0] == "CONFIRMED"
