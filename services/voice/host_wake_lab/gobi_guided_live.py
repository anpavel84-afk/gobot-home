r"""Owner-consented short Windows PLAN mic test of ONE GoBot wake candidate.

Only manual PLAN console consent opens mic. Never stores microphone PCM or
transcripts and never calls the gateway/Brain/paid providers. Each attempt
compares two decoders on the SAME ephemeral 16-kHz PCM: primary LIVE; second
SHADOW offline replay after mic closes. Models/phrase aliases are never mixed.

Sample, when the Owner is PHYSICALLY at PLAN:
  python -m services.voice.host_wake_lab.gobi_guided_live \
   --owner-consent-live --candidate gobi --engine vosk --shadow-engine t-one \
   --models-root C:\Users\PLAN\gobot\HOST-B-lab\models --device 21
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time

from .gobi_policy import CANDIDATES, CANDIDATE_DISPLAY, make_candidate_backend
from .guided_live import capture_live, process_pcm, pcm_signal_levels, prompt_confirm, score_trial

HZ=16000
BACKGROUND_FPH_MIN=1800


def catalog(candidate):
    if candidate not in CANDIDATES:
        raise ValueError("unknown_candidate")
    name=CANDIDATE_DISPLAY[candidate]
    # The backing detector uses plain ASR text 'гоби'; U+0301 here is user prompt only.
    positive=[
      ("isolated1","isolated","Обычный голос, 30-50 см: "+name),
      ("isolated2","isolated","Обычный голос, повторите: "+name),
      ("weather","continuous","Без паузы: "+name+", какая сегодня погода?"),
      ("time","continuous","Без паузы: "+name+", сколько времени?"),
      ("quiet","quiet","ТИХО и естественно: "+name+", сколько времени?"),
      ("far","distance","С расстояния примерно 2 метра: "+name+", какая сегодня погода?"),
    ]
    neg=[
      ("robot","near","Робот, какая сегодня погода?"),
      ("gobot","near","Гобот, сколько времени?"),
      ("lips","near","Губы надо беречь"),
      ("globe","near","Глобус стоит на столе"),
      ("globi","cross_name","Гло́би, какая сегодня погода?"),
      ("gobi","cross_name","Го́би, какая сегодня погода?"),
      ("hey_gobi","cross_name","Эй, Го́би, сколько времени?"),
      ("no-address","non_address","Мы долго говорили про пустыню Гоби"),
      ("room","conversation","Расскажите вслух пару предложений без обращения к помощнику"),
    ]
    if candidate=="monika":
        # Ordinary household distractors, not all other wake names are
        # interchangeable. A person can mention "Моника" without addressing
        # the assistant: score that mention separately from cross-name cases.
        neg=[
          ("monitor","near","Монитор работает"),
          ("monik","near","Моник на столе"),
          ("monya","near","Моня здесь"),
          ("monika-mention","conversation","Мы сегодня обсуждали Монику"),
          ("montirovka","near","Монтировка лежит на полу"),
          ("robot","near","Робот работает"),
          ("weather","non_address","Какая сегодня погода?"),
          ("room","conversation","Поговорите вслух о чём-нибудь без обращения"),
        ]
    # Exclude target as a cross-name negative and preserve all other explicit
    # competing names distinctly from everyday unrelated negative speech.
    neg=[x for x in neg if x[0]!=candidate]
    return (
      [(f"{candidate}-{ident}","positive",condition,name,txt)
       for ident,condition,txt in positive],
      [(f"negative-{ident}","negative",condition,None,txt)
       for ident,condition,txt in neg],
    )


def summarize(kind, expected, events):
    score=score_trial(kind,expected,events)
    return {"hit":bool(score["hit"]),
            "false_events":int(score["false_events"]),
            "wrong_candidates":int(score["wrong_candidates"])}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--owner-consent-live",action="store_true")
    p.add_argument("--candidate",required=True,choices=CANDIDATES)
    p.add_argument("--engine",default="auto",choices=("auto","vosk","t-one","zipformer-window"))
    p.add_argument("--shadow-engine",default="auto",choices=("auto","none","vosk","t-one","zipformer-window"))
    p.add_argument("--models-root",type=Path,required=True)
    p.add_argument("--device",type=int,default=1)  # Windows MME shared mic; avoid WDM-KS 21
    p.add_argument("--seconds",type=float,default=6.0)
    p.add_argument("--quick",action="store_true",
                   help="Only prioritized 3 positive prompts + 5 negative controls")
    p.add_argument("--trace-all",action="store_true",
                   help="Show three actual model partials/finals ONLY at local console after Owner consent")
    p.add_argument("--background-tv",action="store_true",
                   help="30s genuine TV speech negative, from actual room TV")
    p.add_argument("--background-music",action="store_true",
                   help="30s genuine music negative, from actual room player")
    p.add_argument("--out",type=Path)
    args=p.parse_args()
    if args.engine=="auto":
        args.engine="t-one" if args.candidate=="globi" else "vosk"
    if args.shadow_engine=="auto":
        args.shadow_engine="zipformer-window" if args.engine=="t-one" else "t-one"
    positives,negatives=catalog(args.candidate)
    if args.quick:
        positives=[t for t in positives if t[0].split("-")[-1] in ("isolated1","weather","time")]
        wanted=(("negative-monitor","negative-monik","negative-monya",
                 "negative-monika-mention","negative-room")
                if args.candidate=="monika" else
                ("negative-robot","negative-gobot","negative-lips",
                 "negative-globe","negative-room"))
        negatives=[t for t in negatives if t[0] in wanted]
    trials=positives+negatives
    if args.background_tv:
        trials.append(("tv","negative","TV_background",None,"Включите обычную речь с телевизора на 30 секунд"))
    if args.background_music:
        trials.append(("music","negative","music_background",None,"Включите музыку на 30 секунд"))
    if not 2 <= args.seconds <= 8:
        p.error("--seconds must be 2 to 8 seconds")
    if args.shadow_engine==args.engine:
        p.error("use a DIFFERENT shadow engine or none")
    if len(positives)*args.seconds + len(negatives)*args.seconds + (
        int(args.background_tv)+int(args.background_music))*30 > 300:
        p.error("mic capture over 300 seconds not permitted")
    if not args.owner_consent_live:
        print("NOT_RUN_CONSENT_REQUIRED; PC microphone NOT opened.")
        return
    print("HOST-B WAKE LAB | ПРИОРИТЕТ",CANDIDATE_DISPLAY[args.candidate])
    print("ONLY THIS CANDIDATE ACTIVE in this lab. All other names are negatives.")
    print("Проверка бесплатная и локальная. Звук/транскрипты не сохраняются.")
    print("Нажатие Enter перед фразой запускает запись; после фразы подтвердите y/yes/да.")
    print("MIC_ROUTE",args.device,"(PLAN MME Microphone Array=1; old WDM-KS=21)")
    print("Встроенный сигнал после распознавания НЕ является ответом Brain.")
    print("Owner PHYSICALLY at PLAN must now type YES-PC-MIC to authorize this run.")
    if input("Local Owner consent: ").strip() != "YES-PC-MIC":
        print("NOT_RUN_CONSENT_DENIED")
        return
    import psutil
    proc=psutil.Process(os.getpid())
    t0=time.perf_counter()
    primary=make_candidate_backend(args.engine,args.models_root,args.candidate,threads=1)
    primary_cold_ms=round((time.perf_counter()-t0)*1000,1)
    second=None
    second_cold_ms=None
    if args.shadow_engine!="none":
        t0=time.perf_counter()
        second=make_candidate_backend(args.shadow_engine,args.models_root,args.candidate,threads=1)
        second_cold_ms=round((time.perf_counter()-t0)*1000,1)
    # Optional diagnostics only: third model never produces activation/ACK.
    # Its texts appear only in the locally consented terminal, never in JSON.
    trace_models={}
    if args.trace_all:
        from .gobi_diagnostics import replay_model_hypotheses
        for engine_name in ("vosk","t-one","zipformer-window"):
            if engine_name==args.engine:
                trace_models[engine_name]=primary
            elif engine_name==args.shadow_engine and second is not None:
                trace_models[engine_name]=second
            else:
                try:
                    trace_models[engine_name]=make_candidate_backend(
                        engine_name,args.models_root,args.candidate,threads=1)
                except Exception as exc:
                    print("TRACE_MODEL_UNAVAILABLE",engine_name,type(exc).__name__,
                          str(exc)[:120])
    outcomes={args.engine:{"positives":0,"detected":0,"misses":0,"negative_cases":0,
                           "false_events":0,"background_seconds":0.0,
                           "background_false_events":0,"near_negative_false_events":0,
                           "cross_variant_cases":0,"cross_variant_events":0}}
    if second is not None:
        outcomes[args.shadow_engine]={"positives":0,"detected":0,"misses":0,
                "negative_cases":0,"false_events":0,"background_seconds":0.0,
                "background_false_events":0,"near_negative_false_events":0,
                "cross_variant_cases":0,"cross_variant_events":0}
    records=[]
    ack_events=[]
    excluded=[]
    capture_errors=[]  # error class/device only; never save human ASR text
    rss_max=proc.memory_info().rss
    cpu0=proc.cpu_times()
    wall0=time.perf_counter()
    ack_threads=[]

    def local_ack(event):
        from .local_command import beep_ack
        stamp=time.monotonic_ns()
        ack_record={"phrase_id":event["phrase_id"],
                    "confirmation_sample":event["end_sample_index"],
                    "detected_monotonic_ns":event["detected_monotonic_ns"],
                    "ack_request_monotonic_ns":stamp,
                    "api_request_delay_ms":round((stamp-event["detected_monotonic_ns"])/1e6,2),
                    "audible_onset_verified":False}
        ack_events.append(ack_record)
        def beep():
            try:
                beep_ack()
            except Exception as exc:
                print("LOCAL_CUE_UNAVAILABLE",type(exc).__name__)
        th=threading.Thread(target=beep,daemon=True)
        ack_threads.append(th)
        th.start()

    for ident,kind,condition,expected,prompt in trials:
        print("\nTRIAL",ident,"(",kind,condition,")")
        print("SAY:",prompt)
        if condition=="isolated":
            print("Ударение на первый слог. Начните говорить сразу после MIC_OPEN.")
        key=input("Enter=start / s=skip / q=stop: ").strip().lower()
        if key=="q":
            print("OWNER_STOPPED")
            break
        if key!="":
            excluded.append({"id":ident,"reason":"SKIPPED_OR_INVALID_BEFORE_MIC"})
            print("SKIPPED_NOT_COUNTED")
            continue
        seconds=30 if condition in ("TV_background","music_background") else args.seconds
        pcm=None
        try:
            def live_trace(hypothesis, end_index):
                print("LIVE_ASR",args.engine,
                      "stage",("SEGMENT_FINAL" if hypothesis.endpoint else "PARTIAL"),
                      "pcm_end_s",round(end_index/HZ,3),
                      "text",repr(hypothesis.text[:180]),flush=True)
            pcm,live_events,epoch,queue_backlog_ms=capture_live(
                primary,device=args.device,seconds=seconds,
                candidate_id=args.candidate,on_wake=local_ack,
                on_hypothesis=live_trace if args.trace_all else None)
            print("MIC_CLOSED | events",len(live_events))
            shadow_events=process_pcm(second,pcm,epoch,candidate_id=args.candidate) if second else []
            if args.trace_all:
                print("== SAME HUMAN PCM: actual ASR HYPOTHESES, console-only ==")
                for engine_name, model in trace_models.items():
                    print("REPLAY_TRACE_MODEL",engine_name,"candidate",args.candidate,
                          "not live detection, no audio/transcript file")
                    replay_model_hypotheses(model,pcm,label=engine_name)
                print("== END CONSOLE ASR TRACES; NONE SAVED IN REPORT ==")
            levels=pcm_signal_levels(pcm)
            print("SIGNAL_RMS_DBFS",levels["rms_dbfs"],"PEAK_DBFS",levels["peak_dbfs"],
                  "no audio file written")
            if levels["rms_dbfs"] is not None and levels["rms_dbfs"] < -52:
                print("WARNING_QUIET_OR_MUTED: inspect input microphone selection")
            print("LIVE candidate",[(e["phrase_id"],e["end_sample_index"]) for e in live_events])
            if second:
                print("SHADOW candidate",[(e["phrase_id"],e["end_sample_index"]) for e in shadow_events],
                      "(post-capture replay, NOT live latency)")
            if not prompt_confirm():
                excluded.append({"id":ident,"reason":"OWNER_DECLINED_AFTER_CAPTURE"})
                continue
            rec={"id":ident,"kind":kind,"condition":condition,"owner_confirmed":True,
                 "mic_rms_dbfs":levels["rms_dbfs"],"mic_peak_dbfs":levels["peak_dbfs"],
                 "capture_duration_s":round(len(pcm)/32000,2),
                 "live_max_backlog_ms":queue_backlog_ms,
                 "primary_event_count":len(live_events),
                 "shadow_event_count":len(shadow_events)}
            for eng,events in ((args.engine,live_events),(args.shadow_engine,shadow_events)):
                if eng=="none":
                    continue
                s=outcomes[eng]
                outcome=summarize(kind,expected,events)
                if kind=="positive":
                    s["positives"]+=1
                    s["detected"]+=int(outcome["hit"])
                    s["misses"]+=int(not outcome["hit"])
                elif condition=="cross_name":
                    s["cross_variant_cases"]+=1
                    s["cross_variant_events"]+=outcome["false_events"]
                else:
                    s["negative_cases"]+=1
                    s["false_events"]+=outcome["false_events"]
                    if condition in ("TV_background","music_background","conversation"):
                        s["background_seconds"]+=len(pcm)/32000.
                        s["background_false_events"]+=outcome["false_events"]
                    else:
                        s["near_negative_false_events"]+=outcome["false_events"]
                rec[f"{eng}_hit"]=outcome["hit"]
                rec[f"{eng}_false_events"]=outcome["false_events"]
            records.append(rec)
            rss_max=max(rss_max,proc.memory_info().rss)
        except Exception as exc:
            # Keep full PortAudio diagnostics in this LOCAL terminal only.
            # Do not persist stack traces or any speech hypothesis.
            print("LIVE_MIC_OR_PIPELINE_ERROR",type(exc).__name__,
                  "device",args.device,"details",str(exc)[:280],flush=True)
            print("MIC_CAPTURE_ABORTED_NO_RETRY; no paid calls; no gateway switch")
            capture_errors.append({
                "trial_id":ident,"error_type":type(exc).__name__,
                "device":args.device,"run_aborted":True,
            })
            excluded.append({"id":ident,"reason":"MIC_CAPTURE_OR_PIPELINE_ERROR"})
            break
        finally:
            if pcm is not None:
                pcm[:]=bytes(len(pcm))
                pcm.clear()
            primary.reset()
            if second is not None:
                second.reset()
    for t in ack_threads:
        t.join(timeout=2)
    cpu1=proc.cpu_times()
    wall=time.perf_counter()-wall0
    for s in outcomes.values():
        s["false_wakes_per_hour"]=(
            round(s["background_false_events"]*3600/s["background_seconds"],3)
            if s["background_seconds"]>=BACKGROUND_FPH_MIN else None)
        s["human_name_end_P50_ms"]=None
        s["human_name_end_P95_ms"]=None
    result={"schema":"gobot_host_b_gobi_live_v1",
      "timestamp_utc":datetime.now(timezone.utc).isoformat(),
      "candidate":args.candidate,"spelling":CANDIDATE_DISPLAY[args.candidate],
      "primary_engine_live":args.engine,"shadow_engine_postcapture":args.shadow_engine,
      "model_versions":{args.engine:primary.model_version,
                        **({args.shadow_engine:second.model_version} if second else {})},
      "model_cold_ms":{args.engine:primary_cold_ms,
                       **({args.shadow_engine:second_cold_ms} if second else {})},
      "one_candidate_only":True,"activation_approved":False,
      "audio_saved":False,"transcripts_saved":False,"network_audio_sent":False,
      "trace_showed_all_model_hypotheses_locally":bool(args.trace_all),
      "trace_hypothesis_text_persisted":False,
      "paid_calls":0,
      "name_end_offset_ground_truth_available":False,
      "cue_onset_acoustically_measured":False,
      "cpu_time_s":round(cpu1.user+cpu1.system-cpu0.user-cpu0.system,3),
      "wall_s":round(wall,2),"peak_process_rss_mb":round(rss_max/1048576,1),
      "actual_background_exposure_s":round(sum(
            r["capture_duration_s"] for r in records
            if r["condition"] in ("TV_background","music_background","conversation")),2),
      "results":outcomes,"trials":records,"excluded":excluded,
      "capture_errors":capture_errors,
      "cross_variant_events_are_not_ambient_false_activations":True,
      "cue_api_proxies":ack_events,
      "model_status":"HUMAN_TESTED_NOT_AUTO_ACCEPTED"}
    path=args.out or (args.models_root.parent/"results"/(
            "gobi-human-"+args.candidate+"-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".json"))
    path.parent.mkdir(exist_ok=True,parents=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("HUMAN_SUMMARY",outcomes)
    print("JSON_META_ONLY",path)
    print("NO PRODUCTION ACTIVATION. REVIEW BOTH FALSE EVENTS AND MISSES.")


if __name__=="__main__":
    main()
