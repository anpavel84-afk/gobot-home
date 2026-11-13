"""Touch transport and financial isolation. No USB, microphone, network or provider."""
import asyncio
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from gobot.device_contract import DeviceProfile
from gobot.live_budget import LiveBudget
from gobot.live_contract import LiveOffer
from gobot.owner_testing import HardwareVoiceGrant, OwnerTesting, OwnerTestPolicy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
from spotpear_live import StreamingSpeech
from spotpear_scene import project_scene


def test_scoped_board_allowance(tmp_path):
    owner = OwnerTesting(tmp_path/'owner')
    board = 'spotpear-001122334455'
    grant = HardwareVoiceGrant(client_id=board, grant_id=uuid4().hex, expires_at=time.time()+3600,
                               sessions=4, session_seconds=45, backend_calls=2, estimate_usd=1)
    policy = OwnerTestPolicy(enabled=True, authorization='fixture', allowed_client_id='phone',
                             live_enabled=True, live_backend_enabled=True, hardware_voice=grant)
    owner.policy_path.write_text(policy.model_dump_json())
    budget = LiveBudget(tmp_path/'live', owner)
    offer = LiveOffer(session_id=uuid4().hex, conversation_id=uuid4().hex, consent=True,
                      device_id=board, client_id=board, conversation_mode='unified',sdp='v=0'+' '*32)
    assert owner.authorized('phone') and not owner.authorized(board)
    for change in ({'remember':True},{'device_id':'phone'},{'owner_test_binding':'phone'},{'conversation_mode':'standalone'},
                   {'developer_acceptance':True},{'expert_quota_consent':True}):
        with pytest.raises(PermissionError):
            budget.reserve(offer.model_copy(update=change))
    assert owner.hardware_voice_ready(board)
    for _ in range(4):
        assert budget.reserve(offer.model_copy(update={'session_id':uuid4().hex}))==45
    with pytest.raises(PermissionError):
        budget.reserve(offer)
    assert not owner.hardware_voice_ready(board)
    for kind in ('expert','image','transcription'):
        with pytest.raises(PermissionError):
            owner.reserve(board,kind,uuid4().hex)
    for _ in range(2):
        owner.reserve(board,'live_backend',uuid4().hex,estimate=.001)
    with pytest.raises(PermissionError):
        owner.reserve(board,'live_backend',uuid4().hex,estimate=.001)
    assert not owner.status(board)['authorized']
    assert DeviceProfile(client_id=board,client_kind='spotpear').capabilities()['kind']=='spotpear'


def test_fifty_manual_board_sessions_keep_phone_and_prior_usage_separate(tmp_path,monkeypatch):
    owner=OwnerTesting(tmp_path/'owner')
    board='fixture-board'
    grant=HardwareVoiceGrant(client_id=board,grant_id=uuid4().hex,expires_at=None,
                             sessions=50,session_seconds=60,backend_calls=0,estimate_usd=2.5)
    policy=OwnerTestPolicy(enabled=True,authorization='fixture',allowed_client_id='phone',
                           live_enabled=True,live_backend_enabled=True,hardware_voice=grant)
    owner.policy_path.write_text(policy.model_dump_json())
    budget=LiveBudget(tmp_path/'live',owner)
    offer=LiveOffer(session_id=uuid4().hex,conversation_id=uuid4().hex,consent=True,
                    device_id=board,client_id=board,conversation_mode='unified',
                    sdp='v=0'+' '*32,personalization_mode='guest',remember=False)
    with owner.connect() as db:
        db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)',
                   ('prior-board-attempt',int(time.time()//86400),'live',.0316667,0,'hardware:prior-grant'))
    initial_time=time.time()
    for index in range(50):
        if index==25:monkeypatch.setattr(time,'time',lambda:initial_time+2*86400)
        assert owner.hardware_voice_ready(board)
        assert budget.reserve(offer.model_copy(update={'session_id':uuid4().hex}))==60
    assert not owner.hardware_voice_ready(board)
    with pytest.raises(PermissionError,match='hardware_voice_limit'):
        budget.reserve(offer.model_copy(update={'session_id':uuid4().hex}))
    for kind in ('live_backend','expert','image'):
        with pytest.raises(PermissionError):owner.reserve(board,kind,uuid4().hex,estimate=.001)
    assert owner.authorized('phone') and not owner.authorized(board)
    assert owner.policy().allowed_client_id=='phone'
    with owner.connect() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==51
    with pytest.raises(ValueError):HardwareVoiceGrant.model_validate({**grant.model_dump(),'sessions':51})


def test_audio_reaches_track_before_end_and_buffer_is_bounded():
    async def run():
        track=StreamingSpeech()
        samples=b'\x03\x00'*320
        track.feed(samples)
        frame=await track.recv()
        assert frame.to_ndarray().tobytes()==samples and not track.ended.is_set()
        diagnostics=track.diagnostics()
        assert diagnostics['consumed_samples']==diagnostics['clocked_samples']==320
        assert diagnostics['peak_backlog_ms']==20 and diagnostics['backlog_ms']==0
        with pytest.raises(ValueError):
            track.feed(bytes(StreamingSpeech.MAX_BACKLOG_BYTES+2))
        track.finish()
        assert track.ended.is_set()
        with pytest.raises(ValueError):
            track.feed(samples)
        track.stop()
    asyncio.run(run())


def test_timer_and_forecast_reach_same_device_projection():
    timer=str(uuid4())
    frame=dict(id='timer-test',type='timer_widget',title='Таймер',text='Таймер запущен',
               metadata=dict(deadline=105,timer_id=timer))
    payload=project_scene(frame,now=100)['payload']
    assert (payload['timer_key'],payload['remaining_ms'])==(timer,5000)
    day=dict(date='2026-11-13',low=15,high=23,rain_percent=60,wind_kmh=13,
             weather_code=61,icon='rain',condition='Дождь')
    frame.update(type='weather_card',title='Прогноз',metadata=dict(weather=dict(kind='forecast',
                 icon='rain',condition='Дождь',days=[day])))
    payload=project_scene(frame)['payload']
    assert (payload['weather_icon'],payload['title'],payload['text'])==('rain','15…23 °C','Дождь')
