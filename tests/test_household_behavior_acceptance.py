"""Mandatory package contracts against real C routing and effects, fake IO only."""
import asyncio
import importlib.util
import json

import pytest

from household_acceptance_adapter import CASES, PACK, P0_IDS, HouseholdAdapter


_spec = importlib.util.spec_from_file_location('household_trace_contract', PACK / 'check_trace.py')
_checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checker)

# These cases presuppose authorized native private retrieval which AGENTS and
# IdentityAccessManager explicitly say is not integrated in C. A fake grant must
# not turn that absent feature into acceptance evidence. The existing profile
# invalidation tests remain active and separately exercise the fail-closed edge.
BLOCKED = {
    'W069': 'blocked:not_implemented: C native authorized private-weather antecedent is not integrated; no synthetic ACL bypass',
    'C004': 'blocked:not_implemented: C native authorized private-calendar antecedent is not integrated; no synthetic ACL bypass',
    'C002': 'blocked:client_evidence_required: transcript-only fixture cannot prove native audio interruption stopped client playback',
}


@pytest.mark.parametrize('case_id', [pytest.param(ident, marks=pytest.mark.skip(reason=BLOCKED[ident])) if ident in BLOCKED else ident for ident in P0_IDS])
def test_household_p0_contract(case_id, tmp_path, settings, monkeypatch, request):
    async def run():
        case = CASES[case_id]
        adapter = HouseholdAdapter(tmp_path, settings, monkeypatch, case)
        try:
            actual = await adapter.run()
            trace = {'case_id': case_id, 'observed': actual, 'evidence_kind': 'real_C_routing_and_SQLite_with_fake_external_IO',
                     'paid_provider_calls': 0, 'semantic_audio_screen_verification': 'separate_required'}
            (tmp_path / 'observed-trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
            request.node.user_properties.append(('normalized_trace', json.dumps(trace, ensure_ascii=False)))
            if case_id == 'W018' and actual['reason'] == 'comparison_not_implemented':
                # Execute the unsupported request and prove a real honest failure;
                # do not call the positive comparison contract passed or skip IO.
                assert actual['action'] == 'report_unavailable'
                assert actual['provider_requests'] == 0 and actual['home_mutations'] == 0
                pytest.xfail('blocked:not_implemented: bounded two-place weather comparison has no executor; honest no-effect failure verified')
            errors = _checker.compare(case['expected'], actual)
            assert not errors, json.dumps({'case_id': case_id, 'title': case['title'], 'contract_errors': errors,
                                            'observed': actual, 'paid_calls': 0, 'evidence': 'real C / fake external IO'}, ensure_ascii=False, indent=2)
        finally:
            await adapter.close()
    asyncio.run(run())


@pytest.mark.parametrize('other_owner', [False, True], ids=['other-client-same-owner', 'other-device-and-client'])
def test_opaque_weather_reference_is_denied_before_original_scope_closes(tmp_path, settings, other_owner):
    """Complements pending+epoch tests with live opaque-reference replay denial.

    A's context stays present throughout. B has its own valid device profile and
    receives no copied city, coordinates, pending payload or conversation data;
    only the opaque reference is replayed as an adversarial tool argument.
    """
    from test_weather_query_context import configured, HOME
    from gobot.weather_queries import weather_query

    async def run():
        tools, request_a, _, calls, _ = configured(tmp_path, settings)
        result_a = await tools.execute(request_a, weather_query('Погода в Рио'))
        reference = result_a.evidence['weather_request']['place_ref']
        owner_b = 'other-owner' if other_owner else request_a.device_id
        profile_b = tools.devices.update(owner_b + '@second-fixture', {'weather': HOME})
        request_b = request_a.model_copy(update={'device_id': owner_b, 'client_id': profile_b.client_id})
        assert tools.weather_query_context(request_b) == {}
        before = len(calls)
        slots = {'operation': 'weather_forecast', 'place_ref': reference, 'offset': 1, 'days': 1}
        denied = await tools.execute(request_b, slots)
        assert denied.evidence['reason'] == 'weather_place_expired'
        assert denied.frame is None and len(calls) == before
        # A is still usable; denial was scope isolation, not clearing everyone.
        allowed = await tools.execute(request_a, slots)
        assert allowed.frame.metadata.weather.place.startswith('Рио-де-Жанейро')
        assert allowed.evidence['weather_request']['place_ref'] == reference
        assert len(calls) == before + 1
    asyncio.run(run())

