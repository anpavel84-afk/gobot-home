"""Fail-closed touch-only local time path, synthetic microphone device.

The ASR output and local Opus packets are mocked in network tests. Separate
offline model/Piper probe tests the real CPU path, NOT human acceptance.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import json
import sys
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"services"/"voice"))
from host_local_command import classify_command,time_reply,OfflineTimeResponder
from host_downlink import fixture_packets
from gobot_device_gateway import Gateway
from test_host_audio_downlink import HELLO,QuietDetector,uplink_packets


@pytest.mark.parametrize("phrase,expected",[
    ("Скажи, сколько сейчас времени?", "local_time"),
    ("Который час?", "local_time"),
    ("Какое сегодня число?", None),
    ("Напомни про погоду завтра", None),
    ("Привет, я Гобот", None),
    ("", None),
])
def test_strict_local_command_grammar(phrase,expected):
    assert classify_command(phrase)==expected


def test_local_time_responder_no_web_or_model_response(tmp_path):
    asr=tmp_path/"asr";asr.mkdir();(asr/"model.bin").write_bytes(b"exists")
    voice=tmp_path/"voice.onnx";voice.write_bytes(b"exists")
    responder=OfflineTimeResponder(asr,voice)
    class FakeOfflineASR:
        def transcribe(self,*args,**kw):
            return [SimpleNamespace(text="Скажи, сколько сейчас времени?")],None
    responder._model=FakeOfflineASR()
    with patch("host_local_command.offline_russian_packets",return_value=(b"opus",)) as synth:
        packets=responder((1000).to_bytes(2,"little",signed=True)*16000)
    assert packets==(b"opus",)
    assert synth.call_args.kwargs["text"].startswith("Сейчас ")
    assert "2026" not in synth.call_args.kwargs["text"]


def test_local_time_is_from_explicit_sao_paulo_clock():
    clock=datetime(2026,11,16,20,24,tzinfo=ZoneInfo("America/Sao_Paulo"))
    assert time_reply(clock)=="Сейчас 20:24."


def test_touch_to_local_opus_response_without_any_provider():
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect

    async def trial():
        calls=[];servers=[]
        def denied(*a,**kw):
            calls.append("forbidden");raise AssertionError("no_provider_allowed")
        config={"device_mac":"local-test-mac","device_token":"local-test-secret",
                "mode":"hardware_test","host_wake":{
                    "enabled":True,"lan_stream_consent":True,
                    "acceptance_only":True,"free_downlink_fixture":True}}
        async def handler(ws):
            gateway=Gateway(config,"NEVER_PAID",client_factory=denied,
                            host_detector_factory=QuietDetector)
            gateway.save_stats=lambda:None
            gateway.respond=denied
            gateway.reserve_manual_turn=denied
            gateway.host_local_command_responder=lambda pcm: fixture_packets()
            servers.append(gateway)
            await gateway.handle(ws)
        async with serve(handler,"127.0.0.1",0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/xiaozhi/v1/",
                                additional_headers={"Device-Id":"local-test-mac",
                                  "Protocol-Version":"1",
                                  "Authorization":"Bearer local-test-secret"},
                                compression=None) as ws:
                await ws.send(json.dumps(HELLO))
                hello=json.loads(await ws.recv())
                ready=json.loads(await ws.recv())
                assert hello["audio_params"]["sample_rate"]==24000
                epoch,session=ready["epoch"],ready["session_id"]
                def msg(kind,**data):
                    return dict(type=kind,session_id=session,epoch=epoch,**data)
                await ws.send(json.dumps(msg("gobot_host_ready_ack",frame_samples=960)))
                await ws.send(json.dumps(msg("gobot_host_touch",gesture="activate")))
                hit=None
                async with asyncio.timeout(6):
                    while hit is None:
                        event=json.loads(await ws.recv())
                        if event["type"]=="gobot_host_event":
                            assert event["event"]=="wake"
                            hit=event["feedback_id"]
                await ws.send(json.dumps(msg("gobot_host_ack",feedback_id=hit,event="rendered")))
                await ws.send(json.dumps(msg("gobot_host_ack",feedback_id=hit,event="cue_started")))
                # Current server emits a UI hint separately; ignore it.
                for seq,packet in enumerate(uplink_packets(14)):
                    await ws.send(json.dumps(msg("gobot_host_frame",seq=seq,
                                                 sample_start=seq*960,sample_count=960)))
                    await ws.send(packet)
                    await asyncio.sleep(.035)
                await ws.send(json.dumps(msg("gobot_host_finish")))
                played=[];playback=None
                async with asyncio.timeout(7):
                    while True:
                        control=json.loads(await ws.recv())
                        kind=control["type"]
                        if kind=="custom" or kind=="gobot_host_idle":continue
                        if kind=="gobot_host_output_start":
                            assert control["packet_count"]==len(fixture_packets())
                            playback=control["playback_id"]
                        elif kind=="gobot_host_output_frame":
                            assert control["playback_id"]==playback
                            assert control["seq"]==len(played)
                            packet=await ws.recv()
                            assert isinstance(packet,bytes)
                            played.append(packet)
                            if len(played)==1:
                                await ws.send(json.dumps(msg("gobot_host_playback",
                                      playback_id=playback,output_epoch=0,playing=True)))
                        elif kind=="gobot_host_output_end":
                            assert control["packet_count"]==len(played)
                            await ws.send(json.dumps(msg("gobot_host_playback",
                                    playback_id=playback,output_epoch=0,playing=False)))
                            break
                        else:raise AssertionError("unexpected_output_type:"+kind)
                await asyncio.sleep(.12)
                await ws.send(json.dumps(msg("gobot_host_mute",muted=True)))
                await ws.wait_closed()
        assert len(servers)==1 and not calls
        stats=servers[0].stats["host"]
        assert stats["local_command_jobs"]==stats["local_command_recognized"]==1
        assert stats["downlink_packets"]==len(played)
        assert stats["fixture_playback_started_ack"] is True
        assert stats["fixture_playback_drained_ack"] is True
        assert stats["provider_calls"]==stats["financial_reservations"]==0
        assert stats["raw_audio_saved"] is False
    asyncio.run(trial())


def test_touch_stop_invalidates_pending_offline_reply_even_before_speaker():
    from host_wake_core import HostCore
    core=HostCore(QuietDetector(),"epoch-local")
    core.feed({"epoch":"epoch-local","seq":0,"sample_start":0,"sample_count":960},
              (1200).to_bytes(2,"little",signed=True)*960)
    event=core.activate("physical_touch")
    assert event["event"]=="wake"
    core.local_reply_pending=True
    assert core.activate("physical_touch") is None
    core.finish_input().clear()
    stop=core.stop()
    assert stop and stop["event"]=="stop"
    assert stop["output_epoch"]==1
    assert core.local_reply_pending is False
    assert core.stop_pending==stop["command_id"]
    core.stop_ack(stop["command_id"],1)
    assert core.stop_pending is None
    core.close()


def test_touch_stop_cancels_pending_local_asr_before_speaker():
    """No late local response may escape a physical Stop output epoch."""
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect

    async def run():
        servers=[]
        config={"device_mac":"stop-test-mac","device_token":"stop-test",
                "mode":"hardware_test","host_wake":{"enabled":True,
                "lan_stream_consent":True,"acceptance_only":True,
                "free_downlink_fixture":True}}
        def slow_response(pcm):
            time.sleep(.65)
            return fixture_packets()
        async def handler(ws):
            gw=Gateway(config,"NOT_PAID",host_detector_factory=QuietDetector)
            gw.save_stats=lambda:None
            gw.host_local_command_responder=slow_response
            servers.append(gw)
            await gw.handle(ws)
        async with serve(handler,"127.0.0.1",0) as serv:
            port=serv.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/xiaozhi/v1/",
                               additional_headers={
                                   "Device-Id":"stop-test-mac",
                                   "Protocol-Version":"1",
                                   "Authorization":"Bearer stop-test"}) as ws:
                await ws.send(json.dumps(HELLO))
                await ws.recv();ready=json.loads(await ws.recv())
                def msg(t,**kw):
                    return {"type":t,"session_id":ready["session_id"],
                            "epoch":ready["epoch"],**kw}
                await ws.send(json.dumps(msg("gobot_host_ready_ack",frame_samples=960)))
                await ws.send(json.dumps(msg("gobot_host_touch",gesture="activate")))
                async with asyncio.timeout(4):
                    while True:
                        event=json.loads(await ws.recv())
                        if event.get("type")=="gobot_host_event":
                            wake_id=event["feedback_id"];break
                await ws.send(json.dumps(msg("gobot_host_ack",feedback_id=wake_id,event="rendered")))
                await ws.send(json.dumps(msg("gobot_host_ack",feedback_id=wake_id,event="cue_started")))
                for i,pkt in enumerate(uplink_packets(6)):
                    await ws.send(json.dumps(msg("gobot_host_frame",seq=i,
                                                sample_start=i*960,sample_count=960)))
                    await ws.send(pkt)
                    await asyncio.sleep(.06)  # Real-time producer, never burst the bounded queue.
                await ws.send(json.dumps(msg("gobot_host_finish")))
                await ws.send(json.dumps(msg("gobot_host_touch",gesture="stop")))
                stop_id=None;stop_epoch=None
                async with asyncio.timeout(5):
                    while stop_id is None:
                        event=json.loads(await ws.recv())
                        if event["type"]=="gobot_host_event" and event["event"]=="stop":
                            stop_id=event["feedback_id"]
                            stop_epoch=event["output_epoch"]
                assert stop_epoch==1
                await ws.send(json.dumps(msg("gobot_host_ack",feedback_id=stop_id,
                                             event="stopped",output_epoch=stop_epoch)))
                await asyncio.sleep(.8)  # Native slow ASR already returned.
                assert servers[0].stats["host"]["downlink_packets"]==0
                await ws.send(json.dumps(msg("gobot_host_mute",muted=True)))
                await ws.wait_closed()
        await asyncio.sleep(.15)
        stats=servers[0].stats["host"]
        assert stats["local_command_jobs"]==1
        assert stats["local_command_recognized"]==0
        assert stats["downlink_packets"]==0
        assert stats["financial_reservations"]==0
        assert stats["raw_audio_saved"] is False
        assert "last_failure_code" not in stats,stats
    asyncio.run(run())
