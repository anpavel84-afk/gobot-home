import importlib.util,sys
from pathlib import Path
import pytest

BASE=Path('firmware/spotpear/microwake').resolve();sys.path.insert(0,str(BASE))
from guided_wake_plan import plan,header,validate_capture
from record_raw_usb import main,prepare_guided_usb


def test_same_sample_clock_schedule_covers_capture_and_both_accents():
    p=plan();rows=p['steps']
    assert rows[0]['start']==0 and rows[-1]['end']==50
    assert all(a['end']==b['start'] for a,b in zip(rows,rows[1:]))
    names=[r for r in rows if r['kind']=='name']
    assert len(names)==8 and [r['stress'] for r in names]==['first']*4+['second']*4
    assert len({r['hint'] for r in names})==8
    assert {names[i]['stress'] for i in p['heldout_isolated_indices']}=={'first','second'}
    assert not set(p['heldout_isolated_indices'])&set(p['training_isolated_indices'])
    assert all(len(r['text'])<=20 and len(r['hint'])<=16 for r in rows)
    assert (BASE/'guided_wake_prompts.h').read_text(encoding='utf-8')==header()


@pytest.mark.parametrize('seconds',[15,30,49,51,60])
def test_wrong_guided_duration_never_opens_device(seconds):
    with pytest.raises(ValueError,match='exactly50'):main('INVALID',seconds,True,'guided_wake8')


def test_new_guide_and_persistent_model_need_new_explicit_recording_consent():
    with pytest.raises(ValueError,match='fresh recording consent'):main('INVALID',50,False,'guided_wake8',True)
    with pytest.raises(ValueError,match='separate and guided-only'):main('INVALID',50,True,'wake10_questions',True)


def test_usb_prepare_retry_never_arms_or_starts_capture(monkeypatch):
    import record_raw_usb
    clock=[0]
    def now():clock[0]+=.25;return clock[0]
    monkeypatch.setattr(record_raw_usb.time,'monotonic',now)
    class Device:
        writes=[]
        def reset_input_buffer(self):pass
        def write(self,b):self.writes.append(b)
        def readline(self,size):return b'GOBOT_RAW_USB_READY\n' if len(self.writes)==2 else b''
    device=Device();prepare_guided_usb(device)
    assert device.writes==[b'GOBOT_RAW_USB_PREPARE\n']*2


@pytest.mark.parametrize('bad',[None,'expired','wrong_clock_plan','unconfirmed','partial','cloud'])
def test_guided_training_has_fixed_untrained_names_questions_and_no_privacy_renewal(bad):
    meta={'protocol':'guided_wake8','capture_domain':'mono_pcm16_pre_afe','capture_state':'complete_crc_verified','physical_start_ack':True,'owner_reported_completion':True,'cloud_transfer':False,'expires_at':200,'capture_plan':plan()};seconds=50
    if bad=='expired':meta['expires_at']=99
    if bad=='wrong_clock_plan':meta['capture_plan']['heldout_question_indices']=[]
    if bad=='unconfirmed':meta['owner_reported_completion']=False
    if bad=='partial':seconds=49.99
    if bad=='cloud':meta['cloud_transfer']=True
    if bad:
        with pytest.raises(ValueError):validate_capture(meta,seconds,100)
    else:
        value=validate_capture(meta,seconds,100)
        assert value['training_question_indices']==[] and value['heldout_question_indices']==[0,1]
