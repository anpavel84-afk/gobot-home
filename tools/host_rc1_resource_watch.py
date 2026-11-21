"""One-shot read-only Windows RSS/CPU/thread monitor for a finite free HOST test.

Never samples room audio or network payload. Finds the known test listener
Python process (not the live production gateway) and samples only numeric
resource counters until private done marker exists or a hard deadline passes.
No scheduled service, no global hooks and no process termination.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import psutil

p=argparse.ArgumentParser()
p.add_argument("--report",type=Path,required=True)
p.add_argument("--stop-marker",type=Path,required=True)
p.add_argument("--seconds",type=int,default=1950)
p.add_argument("--sample-seconds",type=int,default=60)
args=p.parse_args()

safe=Path(__file__).resolve().parents[1]/"run"/"host-a"
report=args.report.resolve()
marker=args.stop_marker.resolve()
if safe.resolve() not in report.parents or safe.resolve() not in marker.parents:
    p.error("ignored_private_report_directory_required")
if report.exists() or marker.exists() or not 1500<=args.seconds<=2000:
    p.error("existing_report_marker_or_bad_duration")
if not 10<=args.sample_seconds<=60:p.error("invalid_poll_interval")

def find_listener():
    matches=[]
    for process in psutil.process_iter(["pid","name","cmdline"]):
        try:
            cmd=process.info["cmdline"] or []
            if (process.info["name"] or "").lower().startswith("python") and any(
                part.endswith("host_rc1_test_listener.py") for part in cmd
            ) and "1980" in cmd:
                matches.append(process)
        except (psutil.AccessDenied,psutil.NoSuchProcess):
            pass
    # Need one per actual test invocation; Windows Python launcher can
    # create a parent wrapper and a child, so pick the leaf with largest RSS.
    matches.sort(key=lambda proc:proc.memory_info().rss,reverse=True)
    return matches[0] if matches else None

samples=[];deadline=time.monotonic()+args.seconds
run_start=time.monotonic();handle=None
while time.monotonic()<deadline:
    if marker.exists() and len(samples)>=2:break
    if handle is None:
        handle=find_listener()
        if handle is not None:
            print("HOST_RC1_RESOURCE_MONITOR_ATTACHED",flush=True)
    if handle is not None:
        try:
            m=handle.memory_info()
            sample={
                "elapsed_s":round(time.monotonic()-run_start,2),
                "rss_mib":round(m.rss/1048576,3),
                "vms_mib":round(m.vms/1048576,3),
                "threads":handle.num_threads(),
                "cpu_user_s":round(handle.cpu_times().user,3),
                "cpu_system_s":round(handle.cpu_times().system,3),
            }
            samples.append(sample)
            print("HOST_RC1_MEMORY_SNAPSHOT",json.dumps(sample),flush=True)
        except (psutil.AccessDenied,psutil.NoSuchProcess):
            handle=None
    time.sleep(args.sample_seconds)
if not samples:
    raise RuntimeError("no_test_listener_process_observed")
rss=[x["rss_mib"] for x in samples]
result={
    "kind":"HOST_RC1_NUMBER_ONLY_RESOURCES","samples":samples,
    "sample_count":len(samples),
    "memory_rss_first_mib":rss[0],
    "memory_rss_last_mib":rss[-1],
    "memory_rss_delta_mib":round(rss[-1]-rss[0],3),
    "memory_rss_peak_mib":max(rss),
    "audio_recorded":False,"paid_calls":0,
}
report.write_text(json.dumps(result,indent=2),encoding="utf8")
print("HOST_RC1_RESOURCE_RESULT",json.dumps(
    {k:v for k,v in result.items() if k!="samples"}),flush=True)
