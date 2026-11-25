"""HOST-A Owner grant 2026-11-16: 50 total billable test minutes and $3
local estimated-cost ceiling. This is NOT a platform billing limit.

All reservations are charged conservatively at full requested duration, even
after errors, to fail closed across a crash/retry. No secrets or transcripts
are stored. Existing B/C ledgers are separate and never modified.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import math
import os
import uuid

MODEL_USD_PER_MIN = {
    "gpt-live-transcribe": 0.017,
    "gpt-live-1": 0.05,
}
MAX_SECONDS = 50 * 60
MAX_USD = 3.0
MAX_SINGLE_SESSION_SECONDS = 180
SCHEMA = "gobot_host_a_owner_grant_20261116_v1"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fresh():
    return {
        "schema": SCHEMA, "scope": "HOST-A experimental only",
        "grant_date": "2026-11-16",
        "max_seconds": MAX_SECONDS, "max_estimated_usd": MAX_USD,
        "reserved_seconds": 0, "reserved_estimated_usd": 0.0,
        "sessions": [],
        "production_allowed": False,
        "other_B_C_ledgers_unchanged": True,
    }


class BudgetError(PermissionError):
    pass


class HostPaidTrialBudget:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.file = self.folder / "ledger.json"
        self.lock_file = self.folder / "ledger.lock"

    def _locked(self, fn):
        # Deliberately Windows-only, matching protected DPAPI PLAN.
        if os.name != "nt":
            raise BudgetError("Windows PLAN budget lock required")
        import msvcrt
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.lock_file.open("a+b") as fp:
            fp.seek(0)
            if fp.read(1) == b"":
                fp.seek(0); fp.write(b"0"); fp.flush()
            fp.seek(0)
            msvcrt.locking(fp.fileno(), msvcrt.LK_LOCK, 1)
            try:
                return fn()
            finally:
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)

    def _read(self):
        if not self.file.exists():
            return _fresh()
        value = json.loads(self.file.read_text(encoding="utf-8"))
        if (value.get("schema") != SCHEMA or
            value.get("max_seconds") != MAX_SECONDS or
            value.get("max_estimated_usd") != MAX_USD):
            raise BudgetError("budget_ledger_schema_or_limits_changed")
        return value

    def _write(self, value):
        target = self.file.with_suffix(".tmp")
        target.write_text(json.dumps(value, sort_keys=True, indent=2),
                          encoding="utf-8")
        os.replace(target, self.file)

    def status(self):
        return self._locked(lambda: self._read())

    def reserve(self, model: str, seconds: int, *, local_wake_confirmed: bool):
        if not local_wake_confirmed:
            raise BudgetError("no_openai_session_without_local_wake")
        if model not in MODEL_USD_PER_MIN:
            raise BudgetError("model_not_owner_authorized")
        if type(seconds) is not int or not 1 <= seconds <= MAX_SINGLE_SESSION_SECONDS:
            raise BudgetError("unbounded_paid_session")
        cost = seconds / 60.0 * MODEL_USD_PER_MIN[model]

        def book():
            value = self._read()
            if value["reserved_seconds"] + seconds > MAX_SECONDS:
                raise BudgetError("50_min_total_exhausted")
            if value["reserved_estimated_usd"] + cost > MAX_USD + 1e-9:
                raise BudgetError("3_usd_estimate_ceiling")
            ident = uuid.uuid4().hex
            value["reserved_seconds"] += seconds
            value["reserved_estimated_usd"] = round(
                value["reserved_estimated_usd"] + cost, 6)
            value["sessions"].append({
                "id": ident, "model": model, "reserved_seconds": seconds,
                "cost_ceiling_usd": round(cost, 6), "start_utc": _now(),
                "status": "RESERVED_CONSERVATIVE", "finished_utc": None,
                "actual_elapsed_seconds": None,
            })
            self._write(value)
            return ident
        return self._locked(book)

    def reserve_voice_phrase(self, *, model: str = "gpt-4o-mini-tts",
                             voice: str = "marin", seconds: int = 30):
        """Conservatively reserve one prerecorded, non-user-audio TTS phrase.

        $0.05 is a per-phrase local estimate, intentionally much larger than
        typical 2-3s TTS usage. It is NOT a provider-enforced spending cap.
        The same 3000s / $3 ledger governs STT and cached voice generation.
        """
        if model != "gpt-4o-mini-tts" or voice not in ("marin", "cedar"):
            raise BudgetError("unapproved_time_voice_model_or_voice")
        if type(seconds) is not int or not 1 <= seconds <= 30:
            raise BudgetError("unbounded_time_voice_request")
        cost = 0.05

        def book():
            value = self._read()
            if value["reserved_seconds"] + seconds > MAX_SECONDS:
                raise BudgetError("50_min_total_exhausted")
            if value["reserved_estimated_usd"] + cost > MAX_USD + 1e-9:
                raise BudgetError("3_usd_estimate_ceiling")
            ident = uuid.uuid4().hex
            value["reserved_seconds"] += seconds
            value["reserved_estimated_usd"] = round(
                value["reserved_estimated_usd"] + cost, 6)
            value["sessions"].append({
                "id": ident, "model": model, "voice": voice,
                "reserved_seconds": seconds,
                "cost_ceiling_usd": cost,
                "start_utc": _now(),
                "status": "RESERVED_CONSERVATIVE",
                "finished_utc": None,
                "actual_elapsed_seconds": None,
                "kind": "fixed_time_speech_preview",
            })
            self._write(value)
            return ident
        return self._locked(book)

    def reserve_browser_dialog(self):
        """Owner-approved, bounded real Brain+TTS turn, shared 50m/$3 ledger.

        Conservative $0.35 not a provider guarantee. GPT-4.1-mini Chat
        Completions is capped by existing Brain at 700 output tokens.
        GPT-Realtime-2.1-mini TTS is capped by caller to 180 characters and
        35s wall time. A maximum of eight real Browser Dialog reservations
        applies under the same existing hardware STT ledger.
        """
        model = "brain-gpt-4.1-mini+tts-gpt-realtime-2.1-mini"
        seconds = 90
        cost = 0.35

        def book():
            value = self._read()
            if sum(row.get("model") == model for row in value["sessions"]) >= 8:
                raise BudgetError("browser_real_turn_count_limit")
            if value["reserved_seconds"] + seconds > MAX_SECONDS:
                raise BudgetError("50_min_total_exhausted")
            if value["reserved_estimated_usd"] + cost > MAX_USD + 1e-9:
                raise BudgetError("3_usd_estimate_ceiling")
            ident = uuid.uuid4().hex
            value["reserved_seconds"] += seconds
            value["reserved_estimated_usd"] = round(
                value["reserved_estimated_usd"] + cost, 6)
            value["sessions"].append({
                "id": ident, "model": model, "reserved_seconds": seconds,
                "cost_ceiling_usd": cost, "start_utc": _now(),
                "status": "RESERVED_CONSERVATIVE", "finished_utc": None,
                "actual_elapsed_seconds": None,
                "kind": "browser_brain_plus_natural_openai_voice",
            })
            self._write(value)
            return ident

        return self._locked(book)

    def finish(self, ident: str, *, elapsed_seconds: float, result: str):
        if (not isinstance(elapsed_seconds, (int, float))
            or not math.isfinite(elapsed_seconds)
            or elapsed_seconds < 0):
            raise BudgetError("invalid_elapsed")
        if not ident or result not in ("COMPLETE", "FAILED", "TIMEOUT", "CANCELLED"):
            raise BudgetError("invalid_finish")

        def close():
            value = self._read()
            matches = [r for r in value["sessions"] if r["id"] == ident]
            if len(matches) != 1 or matches[0]["status"] != "RESERVED_CONSERVATIVE":
                raise BudgetError("unknown_or_finalized_reservation")
            row = matches[0]
            row["status"] = result
            row["finished_utc"] = _now()
            row["actual_elapsed_seconds"] = round(elapsed_seconds, 3)
            # NEVER refund reserved duration on close; conservative cap.
            self._write(value)
        return self._locked(close)
