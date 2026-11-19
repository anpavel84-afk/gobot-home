"""Explicit finite TLS WSS LAN acceptance with synthetic frames (NOT Spotpear)."""
import asyncio
import json
import ssl
import sys
from pathlib import Path
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT / "services" / "voice"))
sys.path.insert(0,str(HERE))
from host_rc1_test_listener import DisabledWake,forbidden_paid,prepare
from gobot_device_gateway import Gateway
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect


async def run():
    private=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/"data/hardware/gobot-v1"
    source=json.loads((private/"gateway.json").read_text(encoding="utf8"))
    config=prepare(source,18799)
    gateway=Gateway(config,"NEVER_USED",client_factory=forbidden_paid,
                    host_detector_factory=DisabledWake)
    gateway.save_stats=lambda:None
    gateway.respond=forbidden_paid
    gateway.reserve_manual_turn=forbidden_paid
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(private/"server.pem"),str(private/"server.key"))
    client_tls=ssl.create_default_context(cafile=str(private/"server.pem"))

    async with serve(gateway.handle,config["bind"],18799,ssl=tls,
                     max_size=16384,max_queue=8,compression=None) as listener:
        async with connect(f'wss://{config["bind"]}:18799/xiaozhi/v1/',
                           ssl=client_tls,additional_headers={
                               "Device-Id":config["device_mac"],
                               "Protocol-Version":"1",
                               "Authorization":"Bearer "+config["device_token"]},
                           compression=None) as ws:
            caps={"version":1,"capture":"continuous","frame_sequence":True,
                  "local_wake_enabled":False,"local_feedback":True,
                  "playback_epoch":True}
            hello={"type":"hello","version":1,"transport":"websocket",
                   "audio_params":{"format":"opus","sample_rate":16000,
                                   "channels":1,"frame_duration":60},
                   "host_stream":caps}
            await ws.send(json.dumps(hello))
            hi=json.loads(await ws.recv()); ready=json.loads(await ws.recv())
            assert hi["audio_params"]["sample_rate"]==24000
            assert ready["paid_session_opened"] is False
            epoch=ready["epoch"];session=ready["session_id"]
            def msg(type,**kw):
                return dict(type=type,session_id=session,epoch=epoch,**kw)
            await ws.send(json.dumps(msg("gobot_host_ready_ack",frame_samples=960)))
            await ws.send(json.dumps(msg("gobot_host_fixture")))
            count=0;started=False
            async with asyncio.timeout(6):
                while True:
                    event=json.loads(await ws.recv())
                    typ=event["type"]
                    if typ=="gobot_host_output_start":
                        assert event["audio_kind"]=="fixture"
                        playback_id=event["playback_id"]
                    elif typ=="gobot_host_output_frame":
                        assert event["playback_id"]==playback_id and event["seq"]==count
                        data=await ws.recv()
                        assert isinstance(data,bytes) and len(data)<=4096
                        count+=1
                        if not started:
                            # Simulated device; cannot prove physical playback.
                            await ws.send(json.dumps(msg("gobot_host_playback",
                                                       playback_id=playback_id,
                                                       output_epoch=0,playing=True)))
                            started=True
                    elif typ=="gobot_host_output_end":
                        assert event["packet_count"]==count and count>=6
                        await ws.send(json.dumps(msg("gobot_host_playback",
                                                   playback_id=playback_id,
                                                   output_epoch=0,playing=False)))
                        break
                    else:raise AssertionError("unexpected control "+typ)
            await asyncio.sleep(.2)
            await ws.send(json.dumps(msg("gobot_host_mute",muted=True)))
            await ws.wait_closed()

    stats=gateway.stats["host"]
    assert count==stats["downlink_packets"]
    assert stats["fixture_playback_started_ack"]
    assert stats["fixture_playback_drained_ack"]
    assert stats["provider_calls"]==0 and stats["financial_reservations"]==0
    assert stats["clean_mute"] and "last_failure_code" not in stats,stats
    print(json.dumps({"event":"HOST_RC1_LAN_TLS_SMOKE_PASS","frames":count,
                      "transport":"LAN_WSS_TLS","device":"SYNTHETIC_NOT_ESP32",
                      "physical_playback":"NOT_TESTED","paid_calls":0}),flush=True)


if __name__=="__main__":
    asyncio.run(run())
