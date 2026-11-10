"""Warm public-image cache benchmark. Refuses to fetch a missing asset."""
import asyncio,json,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.visual import VisualService
from gobot.models import ChatRequest

async def main():
    service=VisualService();samples=[]
    async def no_network(*args,**kwargs):raise AssertionError('Warm benchmark must not use network')
    def forbidden_provider(_):
        class Provider:
            class Client:get=staticmethod(no_network)
            client=Client()
            search=staticmethod(no_network)
        return Provider()
    service.provider_factory=forbidden_provider
    cases=['Покажи, как выглядят помидоры Бычье сердце','Покажи, как выглядит лабрадор','Покажи картинку Raspberry Pi']
    for index in range(60):
        start=time.perf_counter();result=await service.handle(ChatRequest(text=cases[index%3],mode='auto',remember=False));elapsed=(time.perf_counter()-start)*1000
        if not result.frame.images:raise SystemExit('Warm the real curated assets before running this benchmark')
        samples.append(elapsed)
    report={'kind':'warm local cache + schema construction, not network/browser/audio latency','n':len(samples),'p50_ms':statistics.median(samples),'p95_ms':sorted(samples)[56],'network_requests':0,'model_calls':0,'paid_api_calls':0}
    (ROOT/'docs/visual-cache-benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(main())
