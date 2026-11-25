"""True local models: synthetic Russian utterance -> touch -> WSS Opus16
-> independent local Whisper clock command -> real offline Piper Opus24 reply.

FAKE device; not an acoustic Spotpear or human touch test. No private room
capture, microphone recording, cloud, Brain, B/C/CLI or public audio files.
"""
from __future__ import annotations
import asyncio
from fractions import Fraction
import json
import math
from pathlib import Path
import sys
import time

import av
import numpy as np
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services"/"voice"))
sys.path.insert(0,str(ROOT/"tests"))
from gobot_device_gateway import Gateway
from host_local_command import OfflineTimeResponder
from host_rc1_local_command_probe import prepare_pcm
from test_host_audio_downlink import HELLO, QuietDetector, uplink_packets


def to_opus16(samples:np.ndarray)->list[bytes]:
    samples=np.clip(np.rint(samples*32768),-30000,30000).astype("<i2")
    codec=av.CodecContext.create("libopus","w")
    codec.sample_rate=16000;codec.layout="mono";codec.format="s16"
    codec.time_base=Fraction(1,16000)
    codec.options={"frame_duration":"60","application":"voip"}
    codec.open();out=[]
    nframes=math.ceil(len(samples)/960)
    for n in range(nframes):
        chunk=samples[n*960:(n+1)*960]
        if len(chunk)<960:chunk=np.pad(chunk,(0,960-len(chunk)))
        frame=av.AudioFrame.from_ndarray(chunk.reshape(1,960),format="s16",layout="mono")
        frame.sample_rate=16000;frame.time_base=Fraction(1,16000);frame.pts=n*960
        out.extend(bytes(packet) for packet in codec.encode(frame))
    if len(out)!=nframes:raise ValueError("synthetic_encoder_frame_count")
    return out


async def main():
    private=ROOT.parent/"GoBotHome"/"data"
    voice=private/"hardware"/"gobot-v1"/"irina.onnx"
    asr=private/"models"/"faster-whisper-small"
    started=time.monotonic()
    speech=prepare_pcm(Path(sys.executable).with_name("piper.exe"),voice,
                       "Скажи, сколько сейчас времени?")
    speech_pkts=to_opus16(speech)
    silence=uplink_packets(1)[0]
    del speech
    forbidden_calls=[];holder=[]
    def forbidden(*a,**k):
        forbidden_calls.append(True);raise AssertionError("provider_is_disabled")
    config={"device_mac":"synthetic-local-mac","device_token":"synthetic-local-secret",
            "mode":"hardware_test","host_wake":{
                "enabled":True,"lan_stream_consent":True,
                "acceptance_only":True,"free_downlink_fixture":True,
                "input_level_stats":True}}
    async def handler(ws):
        g=Gateway(config,"NEVER_USED",client_factory=forbidden,
                  host_detector_factory=QuietDetector)
        g.save_stats=lambda:None
        g.respond=forbidden;g.reserve_manual_turn=forbidden
        g.host_local_command_responder=OfflineTimeResponder(asr,voice)
        holder.append(g)
        await g.handle(ws)
    async with serve(handler,"127.0.0.1",0,compression=None) as server:
        port=server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/xiaozhi/v1/",
                           additional_headers={"Device-Id":config["device_mac"],
                              "Protocol-Version":"1",
                              "Authorization":"Bearer "+config["device_token"]},
                           compression=None) as ws:
            send_lock=asyncio.Lock()
            async def send(body,payload=None):
                async with send_lock:
                    await ws.send(json.dumps(body))
                    if payload is not None:await ws.send(payload)
            await ws.send(json.dumps(HELLO))
            hello=json.loads(await ws.recv());ready=json.loads(await ws.recv())
            assert hello["audio_params"]["sample_rate"]==24000
            assert ready["paid_session_opened"] is False
            session=ready["session_id"];epoch=ready["epoch"]
            def msg(kind,**extra):
                return {"type":kind,"session_id":session,"epoch":epoch,**extra}
            await send(msg("gobot_host_ready_ack",frame_samples=960))
            await send(msg("gobot_host_touch",gesture="activate"))
            async with asyncio.timeout(6):
                while True:
                    event=json.loads(await ws.recv())
                    if event["type"]=="gobot_host_event":
                        assert event["source"]=="physical_touch"
                        activation=event["feedback_id"];break
            await send(msg("gobot_host_ack",feedback_id=activation,event="rendered"))
            await send(msg("gobot_host_ack",feedback_id=activation,event="cue_started"))
            stopped=asyncio.Event()
            async def mic_stream():
                index=0;finished=False
                while not stopped.is_set() and index<550:
                    packet=speech_pkts[index] if index<len(speech_pkts) else silence
                    await send(msg("gobot_host_frame",seq=index,
                                   sample_start=index*960,sample_count=960),packet)
                    if not finished and index>=len(speech_pkts)+14:
                        await send(msg("gobot_host_finish"))
                        finished=True
                    index+=1
                    await asyncio.sleep(.06)
                return finished,index
            mic=asyncio.create_task(mic_stream())
            output=[];playback_id=None;received_idle=False
            async with asyncio.timeout(40):
                while True:
                    control=json.loads(await ws.recv())
                    kind=control.get("type")
                    if kind=="gobot_host_output_start":
                        assert control["audio_kind"]=="fixture"
                        assert control["output_epoch"]==0
                        assert 1<=control["packet_count"]<=64
                        playback_id=control["playback_id"]
                    elif kind=="gobot_host_output_frame":
                        assert control["playback_id"]==playback_id
                        assert control["seq"]==len(output)
                        packet=await ws.recv()
                        assert isinstance(packet,bytes)
                        output.append(packet)
                        if len(output)==1:
                            await send(msg("gobot_host_playback",playback_id=playback_id,
                                           output_epoch=0,playing=True))
                    elif kind=="gobot_host_output_end":
                        assert control["packet_count"]==len(output)
                        await send(msg("gobot_host_playback",playback_id=playback_id,
                                       output_epoch=0,playing=False))
                    elif kind=="gobot_host_idle":
                        received_idle=True
                        break
                    elif kind=="custom":
                        continue
                    else:raise AssertionError("unexpected:"+str(kind))
            stopped.set()
            finished,seq=await mic
            await asyncio.sleep(.15)
            await send(msg("gobot_host_mute",muted=True))
            await ws.wait_closed()
    await asyncio.sleep(.15)
    stats=holder[0].stats["host"]
    assert not forbidden_calls
    assert finished and received_idle and len(output)>=12
    assert stats["local_command_jobs"]==1
    assert stats["local_command_recognized"]==1
    assert stats["local_command_failures"]==0
    assert stats["fixture_playback_started_ack"] is True
    assert stats["fixture_playback_drained_ack"] is True
    assert stats["provider_calls"]==stats["financial_reservations"]==0
    assert stats["raw_audio_saved"] is False
    print(json.dumps({"event":"LOCAL_MODELS_TIME_E2E_SYNTHETIC_PASS",
                      "touch":"simulated_device_not_physical",
                      "asr":"real_faster_whisper_small_offline",
                      "reply":"deterministic_local_time_piper",
                      "codec":"actual_16k_to_24k_opus",
                      "mic_packets":stats["received_packets"],
                      "response_packets":len(output),
                      "elapsed_seconds":round(time.monotonic()-started,2),
                      "provider_calls":0,"audio_saved":False},
                     ensure_ascii=True),flush=True)


if __name__=="__main__":
    asyncio.run(main())
