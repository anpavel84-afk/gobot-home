"""Browser Voice Lab v2 budget: bounded reservation, settle to observed usage.

Only the isolated Windows PLAN Browser Lab uses this overlay. The ORIGINAL
legacy HOST-A paid-trial ledger remains byte-for-byte immutable for audit,
physical Spotpear callers and old tests. This overlay is NOT a provider
invoice and never claims that the screenshot's project spend belongs to
Browser Lab.

Historical completed trials are transparently imported as upper-leaning
local proxies, NOT exact costs: STT at observed wall seconds * current
official audio/min tariff * safety factor; legacy Brain/TTS with NO usage
at $0.15 per finished turn. These uncertainties are visible. An unfinished
legacy trial fails closed rather than being silently released.

New audio STT is estimated from transmitted PCM duration. New Brain/TTS
is settled from the OpenAI Realtime response.done token usage when present
+ a tagged estimate for gpt-4.1-mini (whose existing stream does not emit
usage). Failed/unmetered attempts retain their original reservation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import uuid

from host_a_paid_budget import (
    HostPaidTrialBudget, BudgetError, MAX_SECONDS, MAX_USD,
    MODEL_USD_PER_MIN, MAX_SINGLE_SESSION_SECONDS,
)

SCHEMA="gobot_browser_usage_budget_v2_20261117"
BRAIN_MODEL="brain-gpt-4.1-mini+tts-gpt-realtime-2.1-mini"
STT_MODEL="gpt-live-transcribe"
NEW_BRAIN_RESERVE_USD=.35  # upper per-turn hold, RELEASED on success
NEW_BRAIN_RESERVE_SECONDS=90
LEGACY_UNMETERED_BRAIN_PROXY_USD=.15
LEGACY_STT_SAFETY=1.25
NEW_STT_SAFETY=1.25
NEW_TOKEN_SAFETY=1.25
MAX_BROWSER_CONSECUTIVE_TURNS=300  # only technical guard; money/time are primary
NEW_LEDGER="browser-metered-ledger-v2.json"
# Official rates on 2026-11-17 (USD per 1 million tokens).
CHAT_IN=0.40
CHAT_OUT=1.60
TTS_TEXT_IN=.60
TTS_TEXT_IN_CACHED=.06
TTS_TEXT_OUT=2.40
TTS_AUDIO_IN=10.
TTS_AUDIO_IN_CACHED=.30
TTS_AUDIO_OUT=20.


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite(value, *, minimum=0, maximum=1000000):
    if (not isinstance(value,(int,float)) or isinstance(value,bool)
            or not math.isfinite(value) or not minimum<=value<=maximum):
        raise BudgetError("invalid_usage_measurement")
    return float(value)


def _tokens_int(value):
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=10**7:
        raise BudgetError("invalid_provider_token_usage")
    return value


def realtime_usage_usd(usage:dict)->float:
    """Calculate reported mini TTS tokens; never guess usage from latency."""
    if not isinstance(usage,dict):
        raise BudgetError("provider_usage_not_dict")
    ia=usage.get("input_token_details",{}) or {}
    oa=usage.get("output_token_details",{}) or {}
    cached=ia.get("cached_tokens_details",{}) or {}
    if not all(isinstance(x,dict) for x in (ia,oa,cached)):
        raise BudgetError("provider_usage_detail_not_dict")
    if not ia and not oa:
        raise BudgetError("provider_token_breakdown_unavailable")
    ti=_tokens_int(ia.get("text_tokens",0))
    ai=_tokens_int(ia.get("audio_tokens",0))
    tc=_tokens_int(cached.get("text_tokens",0))
    ac=_tokens_int(cached.get("audio_tokens",0))
    to=_tokens_int(oa.get("text_tokens",0))
    ao=_tokens_int(oa.get("audio_tokens",0))
    if tc>ti or ac>ai:
        raise BudgetError("provider_cached_tokens_exceed_total")
    cost=((ti-tc)*TTS_TEXT_IN+tc*TTS_TEXT_IN_CACHED
          +(ai-ac)*TTS_AUDIO_IN+ac*TTS_AUDIO_IN_CACHED
          +to*TTS_TEXT_OUT+ao*TTS_AUDIO_OUT)/1_000_000
    return cost


def new_chat_estimate_usd(input_tokens,output_tokens):
    a=_tokens_int(input_tokens);b=_tokens_int(output_tokens)
    return (a*CHAT_IN+b*CHAT_OUT)/1_000_000


class BrowserMeteredBudget:
    supports_metered_settlement = True

    def __init__(self, folder:str|Path):
        self.folder=Path(folder)
        self.file=self.folder/NEW_LEDGER
        self.legacy=HostPaidTrialBudget(folder)

    def _write(self,v):
        self.folder.mkdir(parents=True,exist_ok=True)
        tmp=self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,
                                  sort_keys=True),encoding="utf-8")
        os.replace(tmp,self.file)

    def _legacy_completed(self):
        old=self.legacy._read()
        active=[x for x in old["sessions"]
                if x.get("status")=="RESERVED_CONSERVATIVE"]
        if active:raise BudgetError("legacy_physical_paid_trial_still_inflight")
        return old

    @staticmethod
    def _import_one(row):
        secs=_finite(row.get("actual_elapsed_seconds")
                     if row.get("actual_elapsed_seconds") is not None
                     else row["reserved_seconds"],maximum=MAX_SECONDS)
        kind=row.get("kind")
        model=row.get("model")
        if model==STT_MODEL:
            estimate=secs/60*MODEL_USD_PER_MIN[STT_MODEL]*LEGACY_STT_SAFETY
            method="legacy_wall_seconds_times_stt_tariff_with_25pct_margin"
        elif model==BRAIN_MODEL or kind=="browser_brain_plus_natural_openai_voice":
            estimate=LEGACY_UNMETERED_BRAIN_PROXY_USD
            method="legacy_unmetered_brain_tts_15c_safety_proxy"
        elif kind=="fixed_time_speech_preview":
            estimate=max(.05,float(row.get("cost_ceiling_usd") or 0))
            method="legacy_unmetered_prerecorded_tts_full_reservation"
        else:
            estimate=float(row.get("cost_ceiling_usd") or 0)
            method="legacy_unknown_model_full_reserved_cost"
        return {
            "legacy_id":str(row.get("id")),
            "model":model, "kind":kind,
            "status":str(row.get("status")),
            "actual_elapsed_seconds":round(secs,3),
            "historical_virtual_reserved_usd":round(
                float(row.get("cost_ceiling_usd") or 0),8),
            "accounted_estimated_usd":round(estimate,8),
            "estimate_method":method,
            "provider_invoice_confirmed":False,
        }

    def _read(self):
        old=self._legacy_completed()
        if self.file.exists():
            v=json.loads(self.file.read_text(encoding="utf-8"))
            if (v.get("schema")!=SCHEMA or v.get("max_seconds")!=MAX_SECONDS
                    or v.get("max_estimated_usd")!=MAX_USD):
                raise BudgetError("browser_v2_schema_or_max_changed")
        else:
            v={
                "schema":SCHEMA, "created_utc":_now(),
                "scope":"HOST-A browser only; legacy original immutable",
                "max_seconds":MAX_SECONDS,"max_estimated_usd":MAX_USD,
                "legacy_imports":[],"sessions":[],
                "provider_invoice_confirmed":False,
            }
        known={row["legacy_id"] for row in v["legacy_imports"]}
        added=False
        for row in old["sessions"]:
            if row.get("id") not in known:
                v["legacy_imports"].append(self._import_one(row))
                known.add(row.get("id"))
                added=True
        if added or not self.file.exists():
            v["legacy_snapshot_hash_sha256"]=hashlib.sha256(
                self.legacy.file.read_bytes()).hexdigest() if self.legacy.file.exists() else ""
            self._write(v)
        return v

    @staticmethod
    def _totals(v):
        history=v["legacy_imports"];rows=v["sessions"]
        spent=sum(float(x["accounted_estimated_usd"]) for x in history)
        spent+=sum(float(x.get("accounted_estimated_usd") or 0)
                   for x in rows if x["status"]!="RESERVED_CONSERVATIVE")
        pending=sum(float(x["reserved_estimated_usd"])
                    for x in rows if x["status"]=="RESERVED_CONSERVATIVE")
        seconds=sum(float(x["actual_elapsed_seconds"]) for x in history)
        seconds+=sum(float(x.get("actual_elapsed_seconds") or 0)
                    for x in rows if x["status"]!="RESERVED_CONSERVATIVE")
        pending_seconds=sum(float(x["reserved_seconds"]) for x in rows
                            if x["status"]=="RESERVED_CONSERVATIVE")
        return spent,pending,seconds,pending_seconds

    def status(self):
        def report():
            v=self._read()
            spent,pending,seconds,pending_seconds=self._totals(v)
            imported=sum(float(x["accounted_estimated_usd"])
                         for x in v["legacy_imports"])
            old_holds=sum(float(x["historical_virtual_reserved_usd"])
                          for x in v["legacy_imports"])
            return {
                "schema":SCHEMA, "max_seconds":MAX_SECONDS,
                "max_estimated_usd":MAX_USD,
                "reserved_estimated_usd":round(spent+pending,6),
                "reserved_seconds":round(seconds+pending_seconds,3),
                "settled_estimated_usd":round(spent,6),
                "pending_estimated_usd":round(pending,6),
                "legacy_imports":len(v["legacy_imports"]),
                "legacy_virtual_reserved_usd":round(old_holds,6),
                "legacy_reconciled_estimated_usd":round(imported,6),
                "legacy_released_virtual_usd":round(old_holds-imported,6),
                "sessions":v["sessions"],
                "provider_invoice_confirmed":False,
                "billing_method":"browser_stt_audio_seconds + provider_tts_tokens "
                                 "+ estimated_chat_tokens; historical proxy",
            }
        return self.legacy._locked(report)

    def _reserve(self,*,model,kind,seconds,cost,local_wake_confirmed):
        if local_wake_confirmed is not True:
            raise BudgetError("browser_paid_requires_local_confirmed_wake")
        seconds=_finite(seconds,minimum=.01,maximum=MAX_SINGLE_SESSION_SECONDS)
        cost=_finite(cost,minimum=.00000001,maximum=.50)
        def book():
            v=self._read()
            spent,pending,actual_s,pending_s=self._totals(v)
            if spent+pending+cost>MAX_USD+1e-9:
                raise BudgetError("3_usd_estimated_limit_reconciled")
            if actual_s+pending_s+seconds>MAX_SECONDS:
                raise BudgetError("50_min_measured_wall_budget_exhausted")
            if any(r["status"]=="RESERVED_CONSERVATIVE" for r in v["sessions"]):
                raise BudgetError("browser_single_paid_operation_only")
            if len(v["sessions"])>=MAX_BROWSER_CONSECUTIVE_TURNS:
                raise BudgetError("browser_300_total_api_trials_guard")
            ident=uuid.uuid4().hex
            v["sessions"].append({
                "id":ident, "kind":kind,"model":model,
                "start_utc":_now(),"status":"RESERVED_CONSERVATIVE",
                "reserved_seconds":seconds,
                "reserved_estimated_usd":round(cost,8),
                "accounted_estimated_usd":None,
                "actual_elapsed_seconds":None,
                "provider_invoice_confirmed":False,
            })
            self._write(v)
            return ident
        return self.legacy._locked(book)

    def reserve(self,model:str,seconds:int,*,local_wake_confirmed:bool):
        if model!=STT_MODEL or type(seconds) is not int or not 1<=seconds<=20:
            raise BudgetError("browser_stt_per_turn_limit_20s")
        return self._reserve(
            model=model,kind="browser_cloud_audio",
            seconds=seconds,cost=seconds/60*MODEL_USD_PER_MIN[model],
            local_wake_confirmed=local_wake_confirmed)

    def reserve_browser_dialog(self):
        # Unlike old v1, the historical count of 8 is NOT a lifetime ban.
        # Still reserve full old $0.35 maximum, then settle on completed
        # provider usage instead of pretending every turn spent the hold.
        return self._reserve(
            model=BRAIN_MODEL,kind="browser_brain_plus_natural_openai_voice",
            seconds=NEW_BRAIN_RESERVE_SECONDS,cost=NEW_BRAIN_RESERVE_USD,
            local_wake_confirmed=True)

    def reserve_voice_phrase(self,*,model="gpt-4o-mini-tts",
                             voice="marin",seconds=30):
        if model!="gpt-4o-mini-tts" or voice not in ("marin","cedar"):
            raise BudgetError("invalid_browser_fixed_tts")
        if not 1<=seconds<=30:raise BudgetError("invalid_fixed_tts_duration")
        return self._reserve(
            model=model,kind="fixed_time_speech_preview",
            seconds=seconds,cost=.05,local_wake_confirmed=True)

    def finish(self,ident:str,*,elapsed_seconds:float,result:str,
               audio_seconds:float|None=None,usage:dict|None=None):
        if result not in ("COMPLETE","FAILED","TIMEOUT","CANCELLED"):
            raise BudgetError("invalid_finish_status")
        elapsed=_finite(elapsed_seconds,maximum=MAX_SINGLE_SESSION_SECONDS*2)
        if audio_seconds is not None:
            audio_seconds=_finite(audio_seconds,maximum=20)
        def settle():
            v=self._read()
            matched=[r for r in v["sessions"] if r["id"]==ident]
            if len(matched)!=1 or matched[0]["status"]!="RESERVED_CONSERVATIVE":
                raise BudgetError("settlement_unknown_or_already_finished")
            row=matched[0]
            reserve=float(row["reserved_estimated_usd"])
            method="failed_or_incomplete_keep_full_maximum_hold"
            settle_cost=reserve
            if result=="COMPLETE" and row["kind"]=="browser_cloud_audio":
                if audio_seconds is not None:
                    cost=audio_seconds/60*MODEL_USD_PER_MIN[STT_MODEL]
                    settle_cost=max(.000001,cost*NEW_STT_SAFETY)
                    method="input_pcm_audio_seconds_x_official_stt_rate_1.25"
                else:
                    settle_cost=max(
                        .000001,elapsed/60*MODEL_USD_PER_MIN[STT_MODEL]
                        *NEW_STT_SAFETY)
                    method="wall_duration_proxy_missing_pcm"
            elif result=="COMPLETE" and row["kind"]=="browser_brain_plus_natural_openai_voice":
                if not isinstance(usage,dict):
                    settle_cost=.15
                    method="completed_but_provider_meter_missing_15c_safety_proxy"
                else:
                    data=usage.get("tts_reports",[]) or []
                    if not isinstance(data,list) or len(data)>12:
                        raise BudgetError("invalid_tts_meter_report_list")
                    measured=sum(realtime_usage_usd(x) for x in data)
                    chat_in=_tokens_int(usage.get("chat_input_estimated_tokens",0))
                    chat_out=_tokens_int(usage.get("chat_output_estimated_tokens",0))
                    chat=new_chat_estimate_usd(chat_in,chat_out)
                    if data:
                        settle_cost=max(
                            .002,(measured+chat)*NEW_TOKEN_SAFETY)
                        method="realtime_response_done_provider_tokens_plus_"
                        method+="estimated_chat_tokens_1.25"
                    else:
                        settle_cost=.15
                        method="no_realtime_usage_report_15c_safety_proxy"
                    row["tts_provider_reported_tokens"]=bool(data)
                    row["tts_provider_reports"]=len(data)
                    row["chat_tokens_estimated_in"]=chat_in
                    row["chat_tokens_estimated_out"]=chat_out
                    row["tts_provider_estimated_cost_usd"]=round(measured,8)
                    row["chat_estimated_cost_usd"]=round(chat,8)
            elif result=="COMPLETE" and row["kind"]=="fixed_time_speech_preview":
                settle_cost=reserve
                method="fixed_audio_without_usage_meter_reserved_in_full"
            row["actual_elapsed_seconds"]=round(elapsed,3)
            row["audio_seconds"]=round(audio_seconds,3) if audio_seconds is not None else None
            row["status"]=result
            row["finished_utc"]=_now()
            row["accounted_estimated_usd"]=round(settle_cost,8)
            row["estimate_method"]=method
            row["released_virtual_reservation_usd"]=round(reserve-settle_cost,8)
            row["actual_estimate_exceeded_initial_hold"]=settle_cost>reserve
            self._write(v)
        return self.legacy._locked(settle)
