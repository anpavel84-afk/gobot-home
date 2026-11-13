"""A gadget that has not applied continuous mode cannot start a paid leg."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import httpx
import numpy as np
import pytest
from websockets.datastructures import Headers
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"services/voice"))
import gobot_device_gateway as gw

def test_no_voice_launch_before_device_ack(tmp_path,monkeypatch):
    async def scenario():
        monkeypatch.setattr(gw,"PRIVATE",tmp_path)
        config={"device_mac":"fixture","device_token":"fixture-token","device_id":"fixture-board",
                "mode":"live_c","continuous_live":True,"hardware_live_consent":True,"brain_url":"http://fixture"}
        launches=[]
        async def allowed(request):return httpx.Response(200,json={"enabled":True})
        gateway=gw.Gateway(config,"fixture",client_factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(allowed)))
        async def respond(*args):launches.append(True)
        gateway.respond=respond
        encoder=gw.OpusOutput()
        packets=encoder.feed((2000*np.sin(np.arange(8000)*.2)).astype("<i2").tobytes(),16000)+encoder.finish()
        class Socket:
            request=SimpleNamespace(path="/xiaozhi/v1/",headers=Headers({"Device-Id":"fixture","Protocol-Version":"1","Authorization":"Bearer fixture-token"}))
            ident=None
            async def send(self,message):
                obj=json.loads(message)
                if obj["type"]=="hello":self.ident=obj["session_id"]
            async def close(self,*args):pass
            def __aiter__(self):return self.items()
            async def items(self):
                yield json.dumps({"type":"hello","version":1,"transport":"websocket",
                                  "audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}})
                yield json.dumps({"type":"listen","state":"start","mode":"auto","session_id":self.ident})
                for packet in packets:yield packet
        await gateway.handle(Socket())
        assert gateway.stats["received_packets"]>0 and not launches
    asyncio.run(scenario())


@pytest.mark.parametrize('ack_first',[False,True])
def test_deferred_capture_starts_only_after_capability_ack_and_transport_ready(tmp_path,monkeypatch,ack_first):
    async def scenario():
        monkeypatch.setattr(gw,'PRIVATE',tmp_path)
        config={'device_mac':'fixture','device_token':'fixture-token','device_id':'fixture-board',
                'mode':'live_c','continuous_live':True,'hardware_live_consent':True,'brain_url':'http://fixture'}
        async def allowed(request):return httpx.Response(200,json={'enabled':True})
        gateway=gw.Gateway(config,'fixture',client_factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(allowed)))
        launches=[];ready=asyncio.Event()
        async def respond(ws,send,capture,ident):
            assert capture.deferred_start and not capture.input_seen
            launches.append(ident)
            await send({'type':'gobot_media_ready'})
        gateway.respond=respond
        encoder=gw.OpusOutput()
        packets=encoder.feed((2000*np.sin(np.arange(8000)*.2)).astype('<i2').tobytes(),16000)+encoder.finish()
        class Socket:
            request=SimpleNamespace(path='/xiaozhi/v1/',headers=Headers({'Device-Id':'fixture','Protocol-Version':'1','Authorization':'Bearer fixture-token'}))
            ident=None
            async def send(self,message):
                obj=json.loads(message)
                if obj['type']=='hello':self.ident=obj['session_id']
                if obj['type']=='gobot_media_ready':ready.set()
            async def close(self,*args):pass
            def __aiter__(self):return self.items()
            async def items(self):
                yield json.dumps({'type':'hello','version':1,'transport':'websocket',
                                  'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}})
                ack={'type':'gobot_session_ready','continuous':True,'capture_deferred':True,'session_id':self.ident}
                listen={'type':'listen','state':'start','mode':'auto','session_id':self.ident}
                yield json.dumps(ack if ack_first else listen)
                assert not launches
                yield json.dumps(listen if ack_first else ack)
                await asyncio.wait_for(ready.wait(),1)
                for packet in packets:yield packet
        await gateway.handle(Socket())
        assert len(launches)==1 and gateway.stats['received_packets']>0
        assert gateway.stats['deferred_capture_ack']==1 and gateway.stats['errors']==0
    asyncio.run(scenario())
