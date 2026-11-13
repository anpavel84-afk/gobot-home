"""No provider calls: failure metadata is useful without leaking socket messages."""
import asyncio
from types import SimpleNamespace
from gobot.live import LiveSession

def test_sideband_failure_records_type_not_secret_message():
    class Broken:
        def __aiter__(self):return self
        async def __anext__(self):raise RuntimeError('PRIVATE payload Bearer secret')
    async def run():
        emitted=[]
        s=SimpleNamespace(ws=Broken(),closing=False,closed=True,
                          emit=lambda *a,**kw:emitted.append((a,kw)))
        await LiveSession.read(s)
        assert s.sideband_failure=={'kind':'RuntimeError','close_code':None,'http_status':None}
        assert emitted[0][1]['code']=='live_sideband_disconnected'
        assert 'PRIVATE' not in repr(emitted) and 'secret' not in repr(emitted)
    asyncio.run(run())
