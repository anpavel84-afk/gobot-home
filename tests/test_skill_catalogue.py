"""400 inventory cases checked against actual free routing, no paid generations."""
import json
from pathlib import Path
import pytest
from gobot.quick_intents import resolve_quick
from gobot.skill_catalogue import catalogue,summary
from gobot.conversation_control import closing_intent
from gobot.conversation_modes import mode_intent
from gobot.local_tools import LocalTools
from gobot.memory import Memory
from gobot.models import ChatRequest

ROWS=catalogue()['scenarios']
ROUTED=[row for row in ROWS if row['path'] in {'native','integration'}]
@pytest.mark.parametrize('row',ROUTED,ids=[row['id'] for row in ROUTED])
def test_catalogue_local_commands_and_blockers_follow_real_routes(row,settings):
    question=row['request']
    if row['path']=='native':
        quick=resolve_quick(question,{'native_live_guest':True})
        assert quick or mode_intent(question) or closing_intent(question)
        assert row['readiness']=='local_path'
    elif row['path']=='integration':
        quick=resolve_quick(question,{'native_live_guest':True})
        assert quick and quick.executor=='skill_readiness' and quick.status=='unavailable'
        result=LocalTools(Memory(settings.db)).execute(quick.executor,ChatRequest(text=question,remember=False),quick.slots)
        assert result.evidence['abstained'] and not result.widget
        assert any(word in result.text.casefold() for word in ['не выполнен','не отправлен','не подключен'])

def test_catalogue_never_claims_400_working_integrations_or_grants_rights():
    state=summary();assert state['scenarios']==400
    assert not state['all_integrations_enabled'] and not state['acoustic_parity_verified']
    assert state['inventory_is_not_permission']
    assert len({r['id'] for r in ROWS})==400 and len({r['request'] for r in ROWS})==400

def test_guest_inventory_does_not_disable_existing_legacy_memory_route():
    question='Прочитай мои личные заметки'
    assert resolve_quick(question) is None
    assert resolve_quick(question,{'native_live_guest':True}).executor=='skill_readiness'
