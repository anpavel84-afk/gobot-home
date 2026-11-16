"""Bounded free HOST-A physical test listener with one Monika wake candidate.

This does NOT change HOST-A code or firmware, switch the Spotpear to HOST,
consume paid A/B/C, or enable the production gateway. It only runs a finite
one-off, authenticated private-LAN listener on A's dedicated RC1 test port.

Default is SHADOW (no actual wake activation). Experimental test-only wake
events require BOTH the explicit --arm-monika CLI argument and the OWNER
typing YES-MONIKA-PILOT at the same local PLAN console; this is not a
production acceptance or 30min false-wake clearance. A's HostCore owns all
event handling, user cue, session, mute, STOP and output on the physical unit.

Requires separate HOST-A authorization to use its test COM3 script; this
program NEVER accesses COM ports. Do not start while HOST-A owns the listener.
"""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import importlib.util
from pathlib import Path
import ssl
import sys

from .monika_bridge import make_monika_factory

B_ROOT=Path(__file__).resolve().parents[3]
MONIKA_NAME="Моника"
STOP_TOKEN="YES-MONIKA-PILOT"


def safe_runtime_paths():
    parent=B_ROOT.parent
    a=parent/"GoBotHome-host-A"
    main=parent/"GoBotHome"
    return a,main


def a_runtime_import(a: Path):
    # HOST-A has PyAV/httpx; its dedicated test process may read only the
    # preinstalled B Vosk Python wheel (identical Python 3.14 ABI) without
    # installing it into the production A environment. No external downloads.
    if importlib.util.find_spec("vosk") is None:
        b_venv_site=B_ROOT.parent/"HOST-B-lab"/".venv"/"Lib"/"site-packages"
        if not (b_venv_site/"vosk"/"__init__.py").is_file():
            raise RuntimeError("ISOLATED_VOSK_DEPENDENCY_MISSING")
        sys.path.append(str(b_venv_site))
    if not (a/"services"/"voice"/"host_wake_contract.py").is_file():
        raise RuntimeError("HOST_A_V1_CONTRACT_MISSING")
    if not (a/"tools"/"host_rc1_test_listener.py").is_file():
        raise RuntimeError("HOST_A_FREE_LISTENER_MISSING")
    # Independent B source/worktree remains immutable; imports are read-only.
    sys.path.insert(0,str(a/"services"/"voice"))
    sys.path.insert(0,str(a/"tools"))
    from host_rc1_test_listener import prepare,forbidden_paid
    from gobot_device_gateway import Gateway
    from host_wake_contract import WakeEvent
    return prepare,forbidden_paid,Gateway,WakeEvent


def validate_private(cfg_root: Path):
    required=("gateway.json","server.pem","server.key")
    for name in required:
        if not (cfg_root/name).is_file():
            raise RuntimeError("HOST_A_PRIVATE_AUTH_FILE_MISSING:"+name)
    data=json.loads((cfg_root/"gateway.json").read_text(encoding="utf8"))
    return data


def physical_test_gates(*, allow_events: bool, isolated_port: int,
                        trial_seconds: int):
    if isolated_port != 18799:
        raise PermissionError("host_rc1_test_port_only")
    if not 15 <= trial_seconds <= 180:
        raise ValueError("finite_15_to_180_second_hardware_trial_only")
    return "EXPERIMENTAL_TEST_ONLY" if allow_events else "SHADOW_ONLY"


async def launch(args, *, prepared):
    a,main=safe_runtime_paths()
    prepare,forbidden_paid,Gateway,WakeEvent=a_runtime_import(a)
    private=main/"data"/"hardware"/"gobot-v1"
    original=validate_private(private)
    cfg=prepare(original,args.port)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(private/"server.pem"),str(private/"server.key"))
    original_factory=make_monika_factory(
        args.models_root,allow_experimental_events=args.arm_monika,
        isolated_hardware_test=True,wake_event_type=WakeEvent)
    owned_detectors=[]
    def isolated_factory():
        detector=original_factory()
        owned_detectors.append(detector)
        return detector
    gateway=Gateway(cfg,"NEVER_USED",client_factory=forbidden_paid,
                    host_detector_factory=isolated_factory)
    gateway.save_stats=lambda:None
    gateway.respond=forbidden_paid
    gateway.reserve_manual_turn=forbidden_paid
    # The only output the device may produce without an assistant is the
    # A-owned local cue and its existing no-cloud fixture via optional touch.
    # Do not inject any second Brain/worker, paid model or speaker service.
    from websockets.asyncio.server import serve
    async with serve(gateway.handle,cfg["bind"],cfg["port"],
                     ssl=tls,max_size=16384,max_queue=8,
                     ping_interval=20,ping_timeout=10,open_timeout=8,
                     close_timeout=2,compression=None):
        print(json.dumps({
            "event":"MONIKA_HOST_RC1_LISTENING",
            "port":args.port,"tls":True,"enrollment":"existing",
            "wake_candidate":"monika","wake_mode":prepared,
            "paid_clients_blocked":True,
            "audio_saved":False,"transcripts_saved":False,
            "production_gateway_changed":False,
            "requires_A_owned_COM3_HOST_ON":True,
            "expires_in_seconds":args.seconds,
        },ensure_ascii=False),flush=True)
        try:
            await asyncio.sleep(args.seconds)
        finally:
            host=gateway.stats.get("host",{})
            print(json.dumps({
                "event":"MONIKA_HOST_RC1_FINISHED",
                "host_frames":host.get("pcm_frames",0),
                "received_packets":host.get("received_packets",0),
                "model_candidate_events":sum(d.shadow_candidate_count for d in owned_detectors),
                "downlink_packets":host.get("downlink_packets",0),
                "host_failure":host.get("last_failure_code"),
                "paid_calls":0,"audio_saved":False,
                "production_gateway_changed":False,
            },ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models-root",type=Path,required=True)
    p.add_argument("--port",type=int,default=18799)
    p.add_argument("--seconds",type=int,default=120)
    p.add_argument("--arm-monika",action="store_true")
    p.add_argument("--preflight-only",action="store_true")
    args=p.parse_args()
    prepared=physical_test_gates(allow_events=args.arm_monika,
                                 isolated_port=args.port,
                                 trial_seconds=args.seconds)
    a,main=safe_runtime_paths()
    if not a.is_dir() or not main.is_dir():
        raise RuntimeError("HOST_A_SEPARATE_WORKTREE_OR_MAIN_MISSING")
    prepare,forbidden_paid,Gateway,WakeEvent=a_runtime_import(a)
    from .gobi_policy import make_candidate_backend
    backend=make_candidate_backend("vosk",args.models_root,"monika",threads=1)
    print("MONIKA_VOSK_CHECK",backend.word_ids,flush=True)
    backend.reset()
    if args.preflight_only:
        print("MONIKA_PILOT_PREFLIGHT_ONLY_NO_LISTENER_NO_MIC_NO_COM3")
        return
    if args.arm_monika:
        print("CAUTION: ONLY finite isolated free hardware test; not production!")
        if input("LOCAL OWNER type YES-MONIKA-PILOT: ").strip()!=STOP_TOKEN:
            print("MONIKA_PILOT_DENIED_NO_LISTENER")
            return
    asyncio.run(launch(args,prepared=prepared))


if __name__=="__main__":
    main()
