"""150 authored semantic cases, production dispatcher/tools, paid egress forbidden."""
import asyncio,json,time
from collections import Counter
from pathlib import Path
import pytest
from hybrid_fixtures import make,dispatch,timer_count

CASES=[json.loads(line) for line in (Path(__file__).parent/'router_eval/cases.jsonl').read_text(encoding='utf8').splitlines()]

def test_category_counts():
    assert Counter(c['group'] for c in CASES)=={'direct':40,'context':25,'compound':20,'indirect':25,'free':20,'unavailable':20}

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['case_id'])
def test_authored_router_case(settings,case,monkeypatch):
    brain,h,scope,c=make(settings)
    # Provider methods would be a defect even without a configured key.
    async def forbidden(*a,**kw):raise AssertionError('paid provider reached by deterministic dispatcher')
    from gobot.live_provider import LiveProvider
    from gobot.realtime_provider import RealtimeProvider
    monkeypatch.setattr(LiveProvider,'create',forbidden);monkeypatch.setattr(RealtimeProvider,'create',forbidden)
    async def run():
        ctx=case['context']
        for text in ctx.get('setup',[]):await dispatch(h,scope,c,text)
        if ctx.get('expire_frame') and c.frame:c.frame.expires=0
        if ctx.get('expire_pending'):
            for pending in brain.memory.transient_pending.values():pending['expires']=0
        if ctx.get('media'):c.media=ctx['media']
        before=timer_count(brain)
        for text in case['utterances']:result=await dispatch(h,scope,c,text)
        assert result.route_type in case['expected']['routes'],(case['utterances'],result.route_type,result.reason)
        assert timer_count(brain)-before==case['expected']['timer_delta']
    asyncio.run(run())
