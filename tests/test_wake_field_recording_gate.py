import importlib.util,sys
from pathlib import Path
import pytest

root=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake'
sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('field_raw_recording',root/'record_raw_usb.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_no_new_consent_never_opens_or_arms_a_device():
    with pytest.raises(ValueError,match='fresh recording consent'):
        m.main('INVALID_PORT',30,False,'field_failed_wake_recheck')


def test_new_field_protocol_rejects_longer_capture_before_device_access():
    with pytest.raises(ValueError,match='limited to30 seconds'):
        m.main('INVALID_PORT',31,True,'field_failed_wake_recheck')
