"""Owner memory controls: exact terminal routing, no transcripts or paid calls."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from gobot.realtime_ws_api import attach_brain_direct_voice, safe_working_memory_status
from gobot.sophia_panel import attach_sophia_panel


TOKEN='fixture-memory-admin-token'
OWNER='owner@example.invalid'
LOCAL='http://127.0.0.1:18811'
TAILNET='https://plan.tailffc57c.ts.net'
SCOPE={'source':'device','device_id':'enrolled-column','client_id':'enrolled-column'}
POLICY={'enabled':True,'ttl_seconds':43200,'persist':True,
        'background':True,'summarize':True,'supplement':True}
PATH='/api/v1/voice-ws/memory'
ADMIN='/api/sophia/admin/memory'
AUTH={'Authorization':'Bearer '+TOKEN}


def diagnostic_fixture():
    return {'available':True,'enabled':True,'policy':deepcopy(POLICY),
        'private_archive':False,'trigger':'every_question','supplements_per_question':1,
        'lookup':{'state':'delivered_late','queries':8,'useful_results':3,
            'supplements':1,'last_lookup_ms':14,'last_sources':2,
            'omitted':['recent_exchange_excerpted','TRANSCRIPT_CANARY'],
            'text':'TRANSCRIPT_CANARY','source_ids':['SOURCE_CANARY']},
        'working':{'enabled':True,'version':3,'available_exchanges':4,
            'completed_exchanges':3,'source_count':7,'ttl_seconds':43200,
            'persistence_requested':True,'persisted':True,'restored_exchanges':2,
            'scope_id':'SCOPE_CANARY','summary_kind':'attributed_working_sources',
            'coverage':'scoped_partial_working_memory','error':None,
            'messages':[{'content':'TRANSCRIPT_CANARY'}]},
        'summary_worker':{'model':'gpt-6-luna','last_state':'applied',
            'enabled_for_scope':True,'active':False,'queued':0,
            'global_tokens_used_or_reserved':800,'daily_token_limit':4000,
            'scope_tokens_used_or_reserved':800,'available_tokens':3200,
            'unknown_usage_attempts':0,'spoken_responses_created':0,
            'budget_day_utc':'2026-11-21','api_key':'SECRET_CANARY'},
        'conversation_id':'CONVERSATION_CANARY','turn_id':'TURN_CANARY'}


class Flow:
    def __init__(self):
        self.state=diagnostic_fixture()
        self.calls=[]
        self.error=None

    def status(self):
        return deepcopy(self.state)

    async def set_policy(self,values):
        if self.error:raise self.error
        self.calls.append(('configure',deepcopy(values)))
        self.state['policy']=deepcopy(values)
        self.state['enabled']=values['enabled']
        return self.status()

    async def clear(self):
        if self.error:raise self.error
        self.calls.append(('clear',None))
        self.state['working']['available_exchanges']=0
        return self.status()


def brain_app():
    app=FastAPI()
    flow=Flow()
    session=SimpleNamespace(closed=False,memory_flow=flow,
        offer=SimpleNamespace(device_id=SCOPE['device_id'],
            client_id=SCOPE['client_id'],owner_test_binding=None))
    manager=SimpleNamespace(sessions={'current':session})

    async def auth(request:Request):
        if request.headers.get('authorization')!='Bearer '+TOKEN:
            raise HTTPException(401)

    attach_brain_direct_voice(app,SimpleNamespace(sessions={}),manager,auth,TOKEN)
    return app,flow,manager


def assert_no_content(value):
    rendered=json.dumps(value)
    for canary in ('TRANSCRIPT_CANARY','SOURCE_CANARY','SCOPE_CANARY',
                   'SECRET_CANARY','TURN_CANARY','CONVERSATION_CANARY'):
        assert canary not in rendered


def test_safe_status_keeps_useful_diagnostics_without_content_or_identifiers():
    result=safe_working_memory_status(diagnostic_fixture())
    assert result['policy']==POLICY
    assert result['working']['available_exchanges']==4
    assert result['lookup']['omitted']==['recent_exchange_excerpted']
    assert result['summary_worker']['global_tokens_used_or_reserved']==800
    assert result['summary_worker']['unknown_usage_attempts']==0
    assert_no_content(result)


def test_safe_status_rejects_malformed_and_unbounded_values():
    result=safe_working_memory_status({'available':'yes',
        'policy':{'enabled':1,'ttl_seconds':float('inf')},
        'lookup':{'state':{},'queries':True,'last_lookup_ms':float('nan'),
            'hot_tokens':10**1000,'omitted':[{},['text'],'recent_exchange_excerpted']},
        'working':{'summary_kind':[],'error':{},'version':-2},
        'summary_worker':{'last_state':{},'model':'SECRET_CANARY',
            'budget_day_utc':'2026-11-21 SECRET_CANARY'}})
    assert result['policy']=={}
    assert result['lookup']=={'state':'unavailable','omitted':['recent_exchange_excerpted']}
    assert result['working']=={'error':'unavailable'}
    assert result['summary_worker']=={'last_state':'unavailable'}
    assert_no_content(result)


def test_unconfirmed_context_ack_is_visible_without_claiming_delivery():
    value=diagnostic_fixture()
    value['lookup']['state']='context_ack_unconfirmed'
    assert safe_working_memory_status(value)['lookup']['state']=='context_ack_unconfirmed'


def test_legacy_lifecycle_status_cannot_export_working_scope_identifiers():
    from gobot.realtime_memory import DialogueMemory
    app,_,manager=brain_app()
    controller=object.__new__(DialogueMemory)
    controller.policy=deepcopy(POLICY);controller.enabled=True;controller.last={'state':'ready'}
    controller.request=lambda:SimpleNamespace(remember=False)
    controller.eligibility=lambda:True
    controller.memory=SimpleNamespace(working_status=lambda req:{
        'scope_id':'SCOPE_CANARY','available_exchanges':3,'enabled':True})
    manager.memory_summary=SimpleNamespace(status=lambda req:{
        'scope_id':'SCOPE_CANARY','last_state':'applied','available_tokens':1000})
    controller.session=SimpleNamespace(manager=manager)
    session=manager.sessions['current']
    session.memory_flow=controller;session.id='current-session';session.ready=True;session.state='ready'
    session.offer.conversation_id='current-conversation'
    session.generation_allowed=lambda:True
    session.lifecycle_status=lambda:{'working_memory':controller.status()}
    manager.status=lambda:{};manager.admission_preview=lambda **kwargs:{'allowed':True}
    with TestClient(app) as client:
        for closed in (False,True):
            session.closed=closed
            result=client.get('/api/v1/voice-ws/status',params=SCOPE,headers=AUTH)
            assert result.status_code==200
            values=result.json()['closed_sessions' if closed else 'sessions']
            memory=values[0]['lifecycle']['working_memory']
            assert memory['working']['available_exchanges']==3
            assert memory['summary_worker']['available_tokens']==1000
            assert 'scope_id' not in memory['working']
            assert 'scope_id' not in memory['summary_worker']
            assert_no_content(result.json())


def test_brain_status_requires_authentication_and_exact_active_terminal():
    app,flow,manager=brain_app()
    with TestClient(app) as client:
        assert client.get(PATH,params=SCOPE).status_code==401
        response=client.get(PATH,params=SCOPE,headers=AUTH)
        assert response.status_code==200
        assert response.headers['cache-control']=='no-store'
        assert response.json()['memory']['available'] is True
        assert_no_content(response.json())
        assert client.get(PATH,headers=AUTH).status_code==422
        for changes in ({'client_id':'foreign'}, {'device_id':'foreign'},
                        {'owner_test_binding':'foreign'}, {'source':'browser'}):
            assert client.get(PATH,params={**SCOPE,**changes},headers=AUTH).status_code==409
        manager.sessions['duplicate']=manager.sessions['current']
        assert client.get(PATH,params=SCOPE,headers=AUTH).status_code==409
        manager.sessions.pop('duplicate')
        manager.sessions['current'].closed=True
        assert client.get(PATH,params=SCOPE,headers=AUTH).status_code==409
    assert not flow.calls


@pytest.mark.parametrize('values',[
    {},{**POLICY,'enabled':1},{**POLICY,'persist':'true'},
    {**POLICY,'ttl_seconds':3599},{**POLICY,'ttl_seconds':86401},
    {**POLICY,'ttl_seconds':43200.0},{**POLICY,'private_archive':True},None,[],
])
def test_brain_rejects_invalid_policy_without_mutating(values):
    app,flow,_=brain_app()
    with TestClient(app) as client:
        result=client.post(PATH,json={**SCOPE,'action':'configure','values':values},headers=AUTH)
        assert result.status_code==422
    assert not flow.calls


def test_brain_controls_require_exact_scope_and_explicit_clear_confirmation():
    app,flow,_=brain_app()
    values={**POLICY,'ttl_seconds':3600}
    with TestClient(app) as client:
        assert client.post(PATH,json={**SCOPE,'action':'clear','confirm':True}).status_code==401
        for bad in ({'source':[]},{'client_id':{}},{'owner_test_binding':{}},
                    {'conversation_id':'private'}):
            assert client.post(PATH,json={**SCOPE,'action':'clear','confirm':True,**bad},headers=AUTH).status_code==422
        for confirm in (None,False,1,'true'):
            assert client.post(PATH,json={**SCOPE,'action':'clear','confirm':confirm},headers=AUTH).status_code==422
        assert not flow.calls
        result=client.post(PATH,json={**SCOPE,'action':'configure','values':values},headers=AUTH)
        assert result.status_code==200 and result.json()['accepted'] is True
        assert result.json()['memory']['policy']==values
        assert flow.calls==[('configure',values)]
        result=client.post(PATH,json={**SCOPE,'action':'clear','confirm':True},headers=AUTH)
        assert result.status_code==200 and result.json()['memory']['working']['available_exchanges']==0
        assert flow.calls[-1]==('clear',None)
        assert_no_content(result.json())


@pytest.mark.parametrize('error,status,code',[
    (ValueError('working_memory_change_requires_idle'),409,'working_memory_change_requires_idle'),
    (PermissionError('working_memory_owner_binding_required'),403,'working_memory_owner_binding_required'),
    (PermissionError('SECRET_CANARY'),403,'working_memory_unavailable'),
    (OSError('SECRET_CANARY'),503,'working_memory_unavailable'),
])
def test_brain_propagates_idle_and_owner_guards_without_sensitive_errors(error,status,code):
    app,flow,_=brain_app();flow.error=error
    with TestClient(app) as client:
        result=client.post(PATH,json={**SCOPE,'action':'clear','confirm':True},headers=AUTH)
        assert result.status_code==status and result.json()['detail']==code
        assert_no_content(result.json())
    assert not flow.calls


def panel_app(tmp_path):
    (tmp_path/'run').mkdir()
    (tmp_path/'run/keys.json').write_text(json.dumps({'api_token':TOKEN}))
    private=tmp_path/'data/hardware/gobot-v1';private.mkdir(parents=True)
    (private/'gateway.json').write_text(json.dumps({'device_id':SCOPE['device_id'],
        'unified_voice':{'enabled':True}}))
    (tmp_path/'data/sophia-admin-owner.json').write_text(json.dumps({
        'version':1,'owner_login_sha256':hashlib.sha256(OWNER.encode()).hexdigest(),
        'local_owner_enabled':True}))
    calls=[]
    reply={'status':200,'body':{'memory':diagnostic_fixture(),'accepted':True,
                              'api_token':'SECRET_CANARY'}}

    def backend(request):
        calls.append(request)
        return httpx.Response(reply['status'],json=reply['body'])

    app=FastAPI()
    attach_sophia_panel(app,tmp_path,client_factory=lambda **kwargs:httpx.AsyncClient(
        transport=httpx.MockTransport(backend),**kwargs))
    return app,calls,reply


def test_panel_routes_only_enrolled_terminal_and_strips_backend_content(tmp_path):
    app,calls,_=panel_app(tmp_path)
    with TestClient(app,base_url=LOCAL,client=('127.0.0.1',50000)) as client:
        result=client.get(ADMIN)
        assert result.status_code==200
        assert 'no-store' in result.headers['cache-control']
        assert_no_content(result.json())
        assert TOKEN not in result.text and SCOPE['device_id'] not in result.text
        assert dict(calls[-1].url.params)==SCOPE
        assert calls[-1].headers['authorization']=='Bearer '+TOKEN
        values={**POLICY,'ttl_seconds':14400}
        result=client.post(ADMIN,headers={'Origin':LOCAL},json={'action':'configure','values':values})
        assert result.status_code==200 and result.json()['accepted'] is True
        assert json.loads(calls[-1].content)=={**SCOPE,'action':'configure','values':values}
        assert_no_content(result.json())
        result=client.post(ADMIN,headers={'Origin':LOCAL},json={'action':'clear','confirm':True})
        assert result.status_code==200
        assert json.loads(calls[-1].content)=={**SCOPE,'action':'clear','confirm':True}


def test_panel_rejects_caller_principals_and_missing_confirmation(tmp_path):
    app,calls,_=panel_app(tmp_path)
    with TestClient(app,base_url=LOCAL,client=('127.0.0.1',50000)) as client:
        assert client.get(ADMIN,params={'device_id':'foreign'}).status_code==422
        for data in ({'action':'clear'}, {'action':'clear','confirm':1},
            {'action':'clear','confirm':True,'client_id':'foreign'},
            {'action':'configure','values':{**POLICY,'persist':1}},
            {'action':'configure','values':POLICY,'source':'browser'}):
            assert client.post(ADMIN,headers={'Origin':LOCAL},json=data).status_code==422
    assert not calls


def test_panel_memory_reuses_owner_host_origin_and_tailnet_guards(tmp_path):
    app,calls,_=panel_app(tmp_path)
    with TestClient(app,base_url=LOCAL,client=('127.0.0.1',50000)) as client:
        assert client.post(ADMIN,json={'action':'clear','confirm':True}).status_code==403
        assert client.post(ADMIN,headers={'Origin':'https://foreign.invalid'},
            json={'action':'clear','confirm':True}).status_code==403
        assert client.get(ADMIN,headers={'Host':'foreign.invalid'}).status_code==403
    with TestClient(app,base_url=TAILNET,client=('127.0.0.1',50000)) as client:
        for headers in ({},{'Tailscale-User-Login':'guest@example.invalid'}):
            assert client.get(ADMIN,headers=headers).status_code==403
        assert not calls
        response=client.get(ADMIN,headers={'Tailscale-User-Login':OWNER})
        assert response.status_code==200
    assert len(calls)==1


@pytest.mark.parametrize('status,body,expected',[
    (503,{'detail':'SECRET_CANARY'},503),
    (409,{'detail':'working_memory_change_requires_idle'},409),
    (200,[],503),(200,{'memory':diagnostic_fixture()},503),
])
def test_panel_unknown_mutation_outcome_never_claims_success(tmp_path,status,body,expected):
    app,calls,reply=panel_app(tmp_path);reply.update(status=status,body=body)
    with TestClient(app,base_url=LOCAL,client=('127.0.0.1',50000)) as client:
        result=client.post(ADMIN,headers={'Origin':LOCAL},json={'action':'clear','confirm':True})
        assert result.status_code==expected
        assert_no_content(result.json())
        assert result.json().get('accepted') is not True
    assert len(calls)==1
