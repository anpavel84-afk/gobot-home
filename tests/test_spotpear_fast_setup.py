"""Local setup concurrency/cleanup, no provider or microphone."""
import asyncio,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
from spotpear_livekit import LocalMediaRelay,rtc

@pytest.mark.parametrize('fail',[False,True])
def test_parallel_join_and_publish_or_cancel_sibling(monkeypatch,fail):
    async def run():
        joined=[];published=[];cancelled=[];relay=None
        class Room:
            def __init__(self):self.local_participant=self
            def on(self,name):return lambda fn:fn
            async def connect(self,*args):
                joined.append(self)
                if fail and len(joined)==2:raise ConnectionError('local fixture')
                try:
                    while len(joined)<2 or fail:await asyncio.sleep(0)
                except asyncio.CancelledError:cancelled.append(self);raise
            async def publish_track(self,*args):
                published.append(self)
                while len(published)<2:await asyncio.sleep(0)
                for event in relay.ready:event.set()
        monkeypatch.setattr(rtc,'Room',Room)
        monkeypatch.setattr(rtc,'AudioSource',lambda *a,**k:object())
        monkeypatch.setattr(rtc,'LocalAudioTrack',SimpleNamespace(create_audio_track=lambda *a:object()))
        relay=LocalMediaRelay({'url':'ws://127.0.0.1:17880','key':'fixture','secret':'fixture'},'local-only')
        assert not joined # Constructing a relay does not open any connection.
        if fail:
            with pytest.raises(ExceptionGroup):await asyncio.wait_for(relay.connect(parallel=True),1)
            assert len(cancelled)==1 and not published
        else:
            await asyncio.wait_for(relay.connect(parallel=True),1)
            assert len(joined)==len(published)==2
    asyncio.run(run())
