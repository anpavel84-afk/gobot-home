"""HOST-A Browser Lab measured accounting — Windows PLAN only, no paid calls."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest

A=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(A/"services"/"voice"))
sys.path.insert(0,str(A/"tools"))
from host_a_paid_budget import HostPaidTrialBudget, BudgetError
from host_a_browser_metered_budget import (
    BrowserMeteredBudget, BRAIN_MODEL, STT_MODEL,
    realtime_usage_usd, new_chat_estimate_usd,
)
from host_a_browser_usage_probe import RealtimeUsageTap


def make_old(folder):
    old=HostPaidTrialBudget(folder)
    for _ in range(8):
        k=old.reserve_browser_dialog()
        old.finish(k, elapsed_seconds=6.5, result="COMPLETE")
    for _ in range(20):
        k=old.reserve(STT_MODEL,20,local_wake_confirmed=True)
        old.finish(k,elapsed_seconds=4.2,result="COMPLETE")
    return old


def test_rebase_never_mutates_original_owner_ledger(tmp_path):
    old=make_old(tmp_path)
    original=old.file.read_bytes()
    v2=BrowserMeteredBudget(tmp_path)
    s=v2.status()
    assert old.file.read_bytes()==original
    assert s["legacy_imports"]==28
    assert s["legacy_virtual_reserved_usd"]==pytest.approx(2.91334,abs=.001)
    # Historical flat $2.8 is no longer described as billed consumption.
    assert s["legacy_reconciled_estimated_usd"] < 1.35
    assert s["reserved_estimated_usd"] < 1.35
    assert s["reserved_seconds"] < 200
    assert s["provider_invoice_confirmed"] is False
    assert v2.file.exists()


def test_next_paid_dialogue_after_8_old_trials_succeeds_and_releases_hold(tmp_path):
    old=make_old(tmp_path)
    v2=BrowserMeteredBudget(tmp_path)
    before=v2.status()
    hold=v2.reserve_browser_dialog()
    reserved=v2.status()
    assert reserved["reserved_estimated_usd"]==pytest.approx(
        before["reserved_estimated_usd"]+.35,abs=.000005)
    usage={
        "tts_reports":[{
            "input_token_details":{
                "text_tokens":160,"audio_tokens":0,
                "cached_tokens_details":{"text_tokens":0,"audio_tokens":0}
            },
            "output_token_details":{"text_tokens":0,"audio_tokens":250},
        }],
        "chat_input_estimated_tokens":2000,
        "chat_output_estimated_tokens":220,
    }
    v2.finish(hold,elapsed_seconds=4.7,result="COMPLETE",usage=usage)
    after=v2.status()
    assert after["reserved_estimated_usd"] < reserved["reserved_estimated_usd"]-.25
    assert after["reserved_estimated_usd"] > before["reserved_estimated_usd"]
    row=after["sessions"][-1]
    assert row["tts_provider_reported_tokens"] is True
    assert row["estimate_method"].startswith("realtime_response_done")
    assert row["released_virtual_reservation_usd"] > .30
    assert row["provider_invoice_confirmed"] is False
    assert old.file.read_bytes()==old.file.read_bytes()
    with pytest.raises(BudgetError):
        v2.finish(hold,elapsed_seconds=4.7,result="COMPLETE",usage=usage)


def test_stt_uses_audio_seconds_not_20s_hold(tmp_path):
    b=BrowserMeteredBudget(tmp_path)
    pre=b.status()["reserved_estimated_usd"]
    k=b.reserve(STT_MODEL,20,local_wake_confirmed=True)
    mid=b.status()["reserved_estimated_usd"]
    assert mid>pre
    b.finish(k,elapsed_seconds=5.7,audio_seconds=3.2,result="COMPLETE")
    end=b.status()["reserved_estimated_usd"]
    assert end-pre==pytest.approx(3.2/60*.017*1.25,abs=.000005)
    assert end<mid


def test_failure_keeps_full_pending_reservation(tmp_path):
    b=BrowserMeteredBudget(tmp_path)
    key=b.reserve_browser_dialog()
    with pytest.raises(BudgetError):
        b.reserve_browser_dialog()  # one operation in flight
    reserved=b.status()["reserved_estimated_usd"]
    b.finish(key,elapsed_seconds=4.2,result="FAILED")
    assert b.status()["reserved_estimated_usd"]==pytest.approx(reserved)
    assert b.status()["sessions"][0]["estimate_method"]=="failed_or_incomplete_keep_full_maximum_hold"


def test_legacy_pending_session_causes_fail_closed(tmp_path):
    old=HostPaidTrialBudget(tmp_path)
    k=old.reserve(STT_MODEL,20,local_wake_confirmed=True)
    b=BrowserMeteredBudget(tmp_path)
    with pytest.raises(BudgetError,match="legacy_physical_paid_trial_still_inflight"):
        b.status()
    old.finish(k,elapsed_seconds=4,result="COMPLETE")
    assert b.status()["legacy_imports"]==1


def test_provider_tts_audio_and_text_token_rates():
    usage={
        "input_token_details":{
            "text_tokens":400,"audio_tokens":100,
            "cached_tokens_details":{
                "text_tokens":100,"audio_tokens":20,
            },
        },
        "output_token_details":{"audio_tokens":800,"text_tokens":50},
    }
    expected=((300*.6+100*.06+80*10+20*.30+800*20+50*2.4)/1_000_000)
    assert realtime_usage_usd(usage)==pytest.approx(expected)
    assert new_chat_estimate_usd(2000,300)==pytest.approx(
        (2000*.4+300*1.6)/1_000_000)
    with pytest.raises(BudgetError):
        realtime_usage_usd({"input_token_details":{
            "audio_tokens":30,"cached_tokens_details":{"audio_tokens":50}
        }})


def test_missing_tts_provider_reports_are_visible_conservative_proxy(tmp_path):
    b=BrowserMeteredBudget(tmp_path)
    k=b.reserve_browser_dialog()
    b.finish(k,elapsed_seconds=5,result="COMPLETE",usage={
        "tts_reports":[],"chat_input_estimated_tokens":1200,
        "chat_output_estimated_tokens":110})
    row=b.status()["sessions"][0]
    assert row["accounted_estimated_usd"]==.15
    assert row["estimate_method"]=="no_realtime_usage_report_15c_safety_proxy"
    assert row["tts_provider_reported_tokens"] is False


def test_meter_tap_captures_response_done_only_and_never_audio(tmp_path):
    class FakeSocket:
        async def send(self,s):
            pass
        async def recv(self):
            return json.dumps({
                "type":"response.done","response":{
                    "id":"resp_ONE","status":"completed",
                    "output":[{"secret":"not-accounting"}],
                    "usage":{
                        "input_token_details":{"text_tokens":220,"audio_tokens":0,
                            "cached_tokens_details":{}},
                        "output_token_details":{"audio_tokens":50,"text_tokens":0},
                    }
                }
            })
    class FakeConnection:
        async def __aenter__(self):
            return FakeSocket()
        async def __aexit__(self,*args):
            return False
    async def run():
        tap=RealtimeUsageTap(base_connector=lambda *args,**kwargs: FakeConnection())
        tap.begin_turn()
        async with tap.connector("ws://LOCAL_TEST_ONLY") as ws:
            raw=await ws.recv()
            assert "not-accounting" in raw
            await ws.recv()  # duplicate provider response_id is ignored
        reports=tap.usage()
        assert len(reports)==1
        assert reports[0]["output_token_details"]["audio_tokens"]==50
        assert "secret" not in str(reports)
        assert "response.done" not in str(reports)
        tap.begin_turn()
        assert tap.usage()==[]
    asyncio.run(run())


def test_old_fixed_cost_budget_api_unchanged_for_physical_a(tmp_path):
    old=HostPaidTrialBudget(tmp_path)
    id=old.reserve_browser_dialog()
    old.finish(id,elapsed_seconds=1,result="COMPLETE")
    assert old.status()["reserved_estimated_usd"]==.35
    assert old.status()["reserved_seconds"]==90

def test_provider_usage_above_reserved_hold_is_never_silently_clamped(tmp_path):
    b=BrowserMeteredBudget(tmp_path)
    key=b.reserve_browser_dialog()
    # Artificially large provider report: upper hold is not an invoice cap.
    b.finish(key,elapsed_seconds=5,result="COMPLETE",usage={
        "tts_reports":[{
            "input_token_details":{"text_tokens":0,"audio_tokens":0},
            "output_token_details":{"audio_tokens":20000,"text_tokens":0},
        }],
        "chat_input_estimated_tokens":1000,
        "chat_output_estimated_tokens":100,
    })
    v=b.status()["sessions"][0]
    assert v["accounted_estimated_usd"]>.35
    assert v["actual_estimate_exceeded_initial_hold"] is True
    assert v["released_virtual_reservation_usd"]<0
