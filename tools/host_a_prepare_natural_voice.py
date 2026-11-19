"""One-off Owner-authorized natural voice sample preparation on PLAN.

Does not open COM3 or device gateway. Only static deterministic Russian time
phrases go to the Speech API; no microphone sound and no transcripts uploaded.
The shared owner ledger caps spending. No unattended recurrence.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.parent / "GoBotHome"
sys.path.insert(0, str(ROOT / "services" / "voice"))
sys.path.insert(0, str(MAIN))

from host_a_paid_budget import HostPaidTrialBudget
from host_a_natural_time_voice import OpenAITimeVoice
from services.brain.gobot.secrets_store import load_openai_key


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--owner-approved-natural-time-voice", action="store_true")
    p.add_argument("--count", type=int, default=4)
    p.add_argument("--preflight-only", action="store_true")
    args = p.parse_args()
    if not args.owner_approved_natural_time_voice:
        raise PermissionError("OWNER_NATURAL_TIME_VOICE_APPROVAL_REQUIRED")
    if not 1 <= args.count <= 8:
        raise ValueError("BOUND_BATCH_REQUIRED")
    budget = HostPaidTrialBudget(ROOT / "run" / "host-a" /
                                 "paid-trial-20261116")
    voice = OpenAITimeVoice(ROOT / "run" / "host-a" /
                            "natural-time-voice", budget,
                            key_loader=load_openai_key)
    state = budget.status()
    print("VOICE_MODEL=gpt-4o-mini-tts VOICE=marin", flush=True)
    print("SHARED_LIMIT_SECONDS=" + str(state["max_seconds"]) +
          " BOOKED_SECONDS=" + str(state["reserved_seconds"]) +
          " USD_ESTIMATE=" + str(state["reserved_estimated_usd"]),
          flush=True)
    if args.preflight_only:
        print("TTS_PREFLIGHT_ONLY_ZERO_NETWORK_ZERO_RESERVATIONS", flush=True)
        return
    # No device IO or concurrent audio test when generating test samples.
    import psutil
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.pid == __import__("os").getpid():
            continue
        if proc.info.get("name") not in ("python.exe", "pythonw.exe"):
            continue
        command = " ".join(proc.info.get("cmdline") or ())
        if any(name in command for name in (
            "host_a_paid_time_trial.py", "host_spotpear_dictation.py",
            "host_monika_live.py", "host_rc1_sustained_usb.py",
        )):
            raise RuntimeError("DEVICE_AUDIO_TRIAL_BUSY_ABORT_TTS_WARMUP")
    t = time.monotonic()
    result = voice.prefetch(args.count)
    for hour, minute, status, packet_count in result:
        print(f"NATURAL_VOICE_{hour:02d}:{minute:02d}={status} "
              f"OPUS24_PACKETS={packet_count}", flush=True)
    status = budget.status()
    print("NATURAL_VOICE_RESULT generated=" +
          str(sum(r[2]=="GENERATED" for r in result)) +
          " cached=" + str(sum(r[2]=="CACHED" for r in result)) +
          " elapsed_s=" + str(round(time.monotonic()-t,2)) +
          " shared_booked_seconds=" + str(status["reserved_seconds"]) +
          " shared_usd_estimate=" + str(status["reserved_estimated_usd"]),
          flush=True)


if __name__ == "__main__":
    main()
