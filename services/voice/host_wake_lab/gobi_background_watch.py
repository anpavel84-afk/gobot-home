r"""Opt-in finite 30/60-minute FALSE WAKE exposure on PLAN; NO RECORDING.

This is deliberately a distinct protocol from the <=300s guided phrase demo.
One candidate, one local ASR engine, one bounded frame queue. No aliases,
training, gateway/Brain/provider sessions, audio persistence or transcript logging.
The human must confirm the background contained no intentional wake calls before
the rate can be calculated. CPU/RAM and actual captured PCM duration measured.
This command IS NOT started by remote automation. Run visibly on PLAN:

python -m services.voice.host_wake_lab.gobi_background_watch \
  --owner-consent-live --candidate gobi --engine vosk \
  --models-root C:\Users\PLAN\gobot\HOST-B-lab\models \
  --source tv --minutes 30 --device 21
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import queue
import time
import uuid

from .detect import WakeLab
from .gobi_policy import CANDIDATES, CandidateMatcher, make_candidate_backend

RATE=16000
FRAME=960
MIN_EXPOSURE_SEC=1800


def rate_per_hour(false_events: int, exposure_seconds: float,
                  *, owner_confirmed: bool) -> float | None:
    if (not owner_confirmed or exposure_seconds < MIN_EXPOSURE_SEC
            or exposure_seconds <= 0 or false_events < 0):
        return None
    return round(false_events*3600/exposure_seconds,4)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--owner-consent-live",action="store_true")
    p.add_argument("--candidate",choices=CANDIDATES,required=True)
    p.add_argument("--engine",choices=("auto","vosk","t-one","zipformer-window"),default="auto")
    p.add_argument("--source",choices=("tv","music","conversation"),required=True)
    p.add_argument("--models-root",type=Path,required=True)
    p.add_argument("--minutes",type=int,choices=(30,60),default=30)
    p.add_argument("--device",type=int,default=21)
    a=p.parse_args()
    if not a.owner_consent_live:
        print("NOT_RUN_CONSENT_REQUIRED: microphone never opened.")
        return
    if a.engine=="auto":
        a.engine="t-one" if a.candidate=="globi" else "vosk"
    print("BACKGROUND ONLY: one wake candidate =",a.candidate,
          "one ASR engine =",a.engine,"source",a.source)
    print("Timed capture",a.minutes,"minutes; NO audio/transcript disk writes.")
    print("Mic must hear REAL ambient",a.source,
          "without intentional wake address; no paid services.")
    print("Do not start concurrently with HOST-A performance/hardware tests.")
    if input("Type YES-PC-MIC locally at PLAN: ").strip()!="YES-PC-MIC":
        print("NOT_RUN_CONSENT_DENIED")
        return
    import sounddevice as sd
    import psutil
    proc=psutil.Process(os.getpid())
    t0=time.perf_counter()
    decoder=make_candidate_backend(a.engine,a.models_root,a.candidate,threads=1)
    init_ms=round((time.perf_counter()-t0)*1000,1)
    lab=WakeLab(decoder,matcher=CandidateMatcher(a.candidate))
    epoch=uuid.uuid4().hex
    frames=queue.Queue(maxsize=8)
    fault=[]
    events=[]
    captured=0
    max_queue_delay_ms=0.
    peak_rss=proc.memory_info().rss
    cpu0=proc.cpu_times()
    wall0=time.monotonic()
    target=a.minutes*60*RATE
    # No ever-growing input ring. Callback stores <=8 frames; no network.
    def callback(pcm,nframes,time_info,status):
        if status or nframes!=FRAME:
            fault.append("portaudio_overflow_or_wrong_frame")
            return
        try:
            frames.put_nowait((bytes(pcm),time.monotonic_ns()))
        except queue.Full:
            fault.append("input_queue_overflow")
    try:
        with sd.RawInputStream(
            samplerate=RATE,blocksize=FRAME,
            channels=1,dtype="int16",device=a.device,callback=callback
        ):
            print("BACKGROUND_MIC_OPENED. Ctrl+C to abort; 30m capture is finite.")
            while captured<target:
                if fault:
                    raise RuntimeError(fault[0])
                try:
                    data,recv=frames.get(timeout=2)
                except queue.Empty:
                    raise RuntimeError("no_microphone_frames")
                max_queue_delay_ms=max(
                    max_queue_delay_ms,(time.monotonic_ns()-recv)/1e6)
                found=lab.feed(
                    pcm_s16le=data,stream_epoch=epoch,
                    sample_index=captured,received_monotonic_ns=recv,
                )
                captured+=len(data)//2
                for event in found:
                    events.append({
                        "phrase_id":event["phrase_id"],
                        "event_time_audio_s":round(event["end_sample_index"]/RATE,3),
                    })
                if captured%(RATE*60)==0:
                    print("BACKGROUND_MINUTE",captured//(RATE*60),
                          "false_events_so_far",len(events))
                peak_rss=max(peak_rss,proc.memory_info().rss)
    except KeyboardInterrupt:
        print("BACKGROUND_OWNER_STOPPED_EARLY")
    except Exception as error:
        fault.append(type(error).__name__)
        print("BACKGROUND_ABORTED",type(error).__name__)
    finally:
        lab.reset()
        while not frames.empty():
            frames.get_nowait()
    cpu1=proc.cpu_times()
    exposure=captured/RATE
    print("MIC_CLOSED captured_s",round(exposure,2),"events",len(events))
    if fault:
        print("EXPOSURE_INVALID_DUE_TO_FAULT",fault)
    print("Confirm real",a.source,"contained NO intentional wake address.")
    reply=input("Type YES-NEGATIVE (or other to invalidate): ").strip()
    accepted=reply=="YES-NEGATIVE" and not fault
    fph=rate_per_hour(len(events),exposure,owner_confirmed=accepted)
    doc={
        "schema":"gobot_host_b_ambient_negative_v1",
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),
        "single_candidate":a.candidate,"engine":a.engine,
        "model_version":decoder.model_version,"license":decoder.license,
        "source":a.source,"owner_confirmed_negative":accepted,
        "captured_audio_seconds":round(exposure,3),"false_events":len(events),
        "false_wakes_per_hour":fph,
        "rate_status":"MEASURED" if fph is not None else "NOT_MEASURED",
        "faults":fault,"max_frame_queue_age_ms":round(max_queue_delay_ms,2),
        "cold_model_load_ms":init_ms,
        "cpu_time_s":round(cpu1.user+cpu1.system-cpu0.user-cpu0.system,2),
        "wall_s":round(time.monotonic()-wall0,2),
        "peak_process_rss_mb":round(peak_rss/1048576,1),
        "activation_approved":False,"paid_calls":0,
        "audio_saved":False,"transcripts_saved":False,"audio_sent_to_cloud":False,
        "event_timestamps":events,
    }
    out=a.models_root.parent/"results"/(
        "gobi-background-"+a.candidate+"-"+a.engine+"-"+a.source+"-"+
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
    print("METADATA_ONLY_REPORT",out,"FPH",fph,
          "(not automatic acceptance; 0 events does not mean 0 risk)")


if __name__=="__main__":
    main()
