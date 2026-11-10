"""PCM identity mirror uses existing worker boundaries, zero external providers."""
import asyncio
from types import SimpleNamespace
import pytest
from gobot.realtime_speaker import NativeSpeakerIdentity

def fixture(result=None):
    async def identify(pcm):return result or {'state':'unknown','personal_authorized':False}
    family=SimpleNamespace(profiles=lambda:[{'enabled':True,'consent':True,'age':'adult'}],calibration=lambda:{'threshold':.8})
    identity=SimpleNamespace(engine=SimpleNamespace(installed=lambda:True),identify=identify)
    s=SimpleNamespace(closed=False,turns=[],personalization=None,access=SimpleNamespace(confirmed_profile_id=None),offer=SimpleNamespace(speaker_consent=True,device_id='owner',client_id='client',profile_epoch=None),id='session',events=[],tasks=[],closures=[])
    async def close(*a):s.closures.append(a)
    s.manager=SimpleNamespace(identity=SimpleNamespace(family=family,speaker_identity=identity),close=close)
    s.emit=lambda kind,**data:s.events.append((kind,data))
    def spawn(coro):
        t=asyncio.create_task(coro);s.tasks.append(t);return t
    s.spawn=spawn
    return s,NativeSpeakerIdentity(s)

def test_mirror_ready_requires_existing_consent_model_and_calibration():
    s,m=fixture();assert m.status()['ready']
    s.offer.speaker_consent=False;assert not m.status()['ready']
    s.offer.speaker_consent=True;s.manager.identity.family.profiles=lambda:[]
    assert m.status()['reason']=='no_enrolled_consenting_profiles'

def test_recognition_is_not_authorization_and_duplicate_segment_is_rejected():
    async def run():
        s,m=fixture({'state':'recognized','profile_id':'synthetic-a','similarity':.95,'embedding':'MUST_NOT_LEAVE_HOST'})
        segment=m.begin();await m.accept(segment,b'\0'*96000);await asyncio.gather(*s.tasks)
        event=s.events[-1][1]
        assert event['ui_identity']=='tentative_match' and not event['personal_authorized']
        assert 'embedding' not in event and 'MUST_NOT' not in str(event)
        with pytest.raises(ValueError):await m.accept(segment,b'\0'*96000)
    asyncio.run(run())

def test_late_old_speaker_result_does_not_change_new_turn():
    async def run():
        s,m=fixture();gate=asyncio.Event()
        async def identify(pcm):await gate.wait();return {'state':'recognized','profile_id':'old'}
        s.manager.identity.speaker_identity.identify=identify
        segment=m.begin();await m.accept(segment,b'\0'*96000)
        m.begin();gate.set();await asyncio.gather(*s.tasks)
        assert not s.events
    asyncio.run(run())

def test_different_speaker_closes_old_provider_session_without_granting_new_rights():
    async def run():
        s,m=fixture({'state':'recognized','profile_id':'new-person'})
        m.last_profile='old-person';await m.accept(m.begin(),b'\0'*96000);await asyncio.gather(*s.tasks)
        assert s.closures and s.closures[0][-1]=='speaker_changed_or_uncertain'
        assert s.access.confirmed_profile_id is None
    asyncio.run(run())

def test_oversize_or_wrong_nonce_rejected_before_worker():
    async def run():
        s,m=fixture();m.begin()
        with pytest.raises(ValueError):await m.accept('wrong',b'\0'*96000)
        with pytest.raises(ValueError):await m.accept(m.current,b'\0'*192002)
        assert not s.tasks
    asyncio.run(run())
