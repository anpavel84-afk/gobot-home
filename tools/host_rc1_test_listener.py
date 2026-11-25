"""Guarded one-shot LAN HOST-A RC1 free-only test listener.

Separate TCP port, same existing enrollment identity and local TLS cert; no
production config mutations, Brain, paid API, disk recording, detector training
or persistent background service. Silent detector: ONLY physical touch activates.
"""
from __future__ import annotations
import argparse
import asyncio
import ipaddress
import json
import os
import ssl
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "voice"))
from gobot_device_gateway import Gateway
from websockets.asyncio.server import serve


class DisabledWake:
    def feed(self, pcm, *, speaking):
        return None

    def reset(self):
        return None


def forbidden_paid(*args, **kwargs):
    raise RuntimeError("RC1_paid_endpoint_permanently_blocked")


def prepare(original: dict, port: int) -> dict:
    bind = ipaddress.ip_address(original.get("bind", ""))
    if bind.version != 4 or not bind.is_private or port != 18799:
        raise ValueError("isolated_private_lan_port_required")
    if original.get("port") == port or original.get("mode") not in {
        "hardware_test", "realtime_b", "live_c", "legacy_a", "duplex_test"
    }:
        raise ValueError("unapproved_production_port_or_mode")
    for key in ("device_token", "device_mac"):
        if not isinstance(original.get(key), str) or not original[key]:
            raise ValueError("existing_device_enrollment_required")
    return {
        "bind": str(bind), "port": port, "device_id": original.get("device_id"),
        "device_mac": original["device_mac"], "device_token": original["device_token"],
        "mode": "hardware_test",
        "host_wake": {
            "enabled": True, "lan_stream_consent": True,
            "acceptance_only": True, "free_downlink_fixture": True,
            "input_level_stats": True
        }
    }


async def run(args):
    private = Path(args.private).resolve()
    original = json.loads((private / "gateway.json").read_text(encoding="utf8"))
    cfg = prepare(original, args.port)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(private / "server.pem"), str(private / "server.key"))
    gateway = Gateway(cfg, "NEVER_USED", client_factory=forbidden_paid,
                      host_detector_factory=DisabledWake)
    gateway.save_stats = lambda: None
    gateway.respond = forbidden_paid
    gateway.reserve_manual_turn = forbidden_paid
    if args.offline_russian:
        from functools import partial
        from host_local_tts import offline_russian_packets
        voice=private/"irina.onnx"
        if not voice.is_file() or not (private/"irina.onnx.json").is_file():
            raise ValueError("offline_russian_test_voice_absent")
        gateway.host_fixture_factory=partial(offline_russian_packets,voice)
    if args.local_time:
        from host_local_command import OfflineTimeResponder
        local_asr=ROOT/"data"/"models"/"faster-whisper-small"
        # The HOST-A repository is a separate worktree; the reference
        # model lives under the existing main checkout, never copied.
        main_root=ROOT.parent/"GoBotHome"
        local_asr=main_root/"data"/"models"/"faster-whisper-small"
        gateway.host_local_command_responder=OfflineTimeResponder(
            local_asr,private/"irina.onnx")

    # Deliberately a finite interactive run, no scheduler/service install.
    if args.report:
        report=args.report.resolve()
        if (ROOT/"run"/"host-a") not in report.parents:
            raise ValueError("private_ignored_report_directory_required")
    if args.stop_file and args.stop_file.exists():
        raise ValueError("stale_stop_file_refused")
    async with serve(gateway.handle, cfg["bind"], cfg["port"], ssl=tls,
                     max_size=16384, max_queue=8, ping_interval=20,
                     ping_timeout=10, open_timeout=8, close_timeout=2,
                     compression=None):
        print(json.dumps({
            "event": "HOST_RC1_LISTENING", "port": cfg["port"], "auth": "existing",
            "tls": True, "wake": "DISABLED", "provider_calls": 0,
            "production_gateway_switched": False,
            "recording_saved": False,
            "free_fixture_type": "offline_russian" if args.offline_russian else "low_level_tone",
            "free_touch_local_command": "clock" if args.local_time else "OFF"
        }), flush=True)
        try:
            deadline=asyncio.get_running_loop().time()+args.seconds
            while True:
                remaining=deadline-asyncio.get_running_loop().time()
                if remaining<=0:break
                await asyncio.sleep(min(60 if args.seconds>200 else 10,remaining))
                h=gateway.stats.get("host",{})
                if h:
                    # Sanitized numeric counters only, no PCM/transcript.
                    fields=("received_packets","pcm_frames","received_span_s",
                            "pcm_peak_abs",
                            "pcm_max_rms","pcm_rms_min","pcm_nonquiet_frames",
                            "pcm_total_samples","pcm_clipped_samples","pcm_abs_dc_max",
                            "last_input_seq","max_queue_age_ms","max_queue_frames",
                            "downlink_packets","fixture_playback_started_ack",
                            "fixture_playback_drained_ack","provider_calls",
                            "last_failure_code","abrupt_device_close",
                            "manual_touch_activations","manual_touch_stops",
                            "local_command_jobs","local_command_recognized",
                            "local_command_unrecognized","local_command_failures")
                    print(json.dumps({"event":"HOST_RC1_NUMERIC_STREAM",
                                      "stats":{k:h[k] for k in fields if k in h}}),flush=True)
                if args.stop_file and args.stop_file.exists() and not gateway.active:
                    print('HOST_RC1_FINI_FILE_AND_DEVICE_DISCONNECTED',flush=True)
                    break
        finally:
            # Statistics contain only counts and queue timings, no PCM.
            result = {k:v for k,v in gateway.stats.items()
                      if k in ("host", "accepted", "rejected", "completed", "errors")}
            print(json.dumps({"event":"HOST_RC1_FINISHED",
                              "read_only_counters":result}), flush=True)
            if args.report:
                snapshot={"source":"physical_Spotpear", "audio_persisted":False,
                          "paid_calls":0,"test_listener_port":args.port,
                          "status":"NUMERIC_ONLY_NOT_HUMAN_ACCEPTED","counters":result}
                args.report.write_text(json.dumps(snapshot,indent=2),encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", default=str(ROOT / "data" / "hardware" / "gobot-v1"))
    parser.add_argument("--port", type=int, default=18799)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--report",type=Path)
    parser.add_argument("--stop-file",type=Path)
    parser.add_argument("--offline-russian",action="store_true")
    parser.add_argument("--local-time",action="store_true")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 2000:
        parser.error("finite_5_to_2000_seconds_required")
    asyncio.run(run(args))
