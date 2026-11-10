import json,time,asyncio
from pathlib import Path
import pytest
from gobot.routing import SmartRouter,RouterPolicy
from gobot.models import ChatRequest
from gobot.quality import SelectiveVerifier,Assessment,calculate,arithmetic_expression
from gobot.processes import AgentError
from gobot.context_manager import ContextManager

CASES=json.loads((Path(__file__).parent/'fixtures/quality-router.json').read_text(encoding='utf-8'))['cases']
STATES={'antigravity':{'available':True},'codex':{'available':True}}
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_synthetic_policy(case):
    decision=SmartRouter().choose(ChatRequest(text=case['text'],mode='auto',usage_consent=True),case['context'],STATES)
    label=decision.tool or ('codex' if decision.provider=='codex' else 'argon' if 'argon' in (decision.model or '') else 'reasoning' if decision.category=='REASONING' else 'flash')
    assert label==case['expected']
    assert decision.classifier_calls==0
    assert decision.quality['verification_required']==case['verification_required']
    if case['category']=='calculator':assert calculate(arithmetic_expression(case['text']))==case['reference_answer']

def test_quality_rejects_self_confidence_and_missing_evidence():
    verifier=SelectiveVerifier();assessment=Assessment(verification_required=True,method='external_sources')
    assert not verifier.check(assessment,'Я абсолютно уверен: факт верен.')['accepted']
    assert not verifier.check(assessment,'Факт',{'method':'other_model','verified':True,'canonical_answer':'Факт'})['accepted']
    assert verifier.check(assessment,'Не удалось проверить.',{'abstained':True})['accepted']

def test_flash_failure_not_heavy_fallback_and_registry_limits():
    with pytest.raises(AgentError):SmartRouter().choose(ChatRequest(text='Привет',mode='auto'),{}, {'codex':{'available':True}})
    with pytest.raises(AgentError,match='heavy_model_not_allowed_in_auto'):
        SmartRouter(RouterPolicy(fast_cli_model='gemini-4-argon-medium')).choose(ChatRequest(text='Привет',mode='auto'),{},STATES)
    assert not SmartRouter().capabilities['lite_approved_categories']

def test_cancel_and_required_verification_do_not_voice_unchecked_facts(settings,monkeypatch):
    from gobot.brain import Service
    import gobot.brain as module
    async def forbidden(*a,**kw):raise AssertionError('unnecessary model call');yield ''
    monkeypatch.setattr(module,'bridge_stream',forbidden)
    monkeypatch.setattr(module,'agent_status',lambda *a:STATES)
    async def run():
        service=Service(settings);req=ChatRequest(text='Какое лекарство дать ребёнку?',mode='auto')
        await service.prepare(req);events=[e async for e in service.events(req)]
        assert events[-1].type=='final'
        spoken=' '.join(e.data['text'] for e in events if e.type=='sentence_ready')
        assert 'проверенный источник' in spoken
    asyncio.run(run())
