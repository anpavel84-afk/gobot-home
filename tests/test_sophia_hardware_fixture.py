"""A finite fixture must not turn an unsolicited disconnect into a PASS."""
import pytest

from tools.sophia_hardware_fixture import barge_aec_evidence, expected_close_reason


@pytest.mark.parametrize('received', [None, 1000, 1001, 1002, 1011])
@pytest.mark.parametrize('sent', [None, 1000, 1001])
def test_unrequested_close_fails_even_when_peer_close_is_clean(sent, received):
    assert expected_close_reason(unmute_requested=False, stopping=False,
                                 sent_code=sent, received_code=received) is None


@pytest.mark.parametrize('received', [None, 1000, 1001])
def test_requested_unmute_or_deadline_needs_exact_boundary(received):
    assert expected_close_reason(unmute_requested=True, stopping=False,
        sent_code=None, received_code=received) == 'expected_unmute_disconnect'
    assert expected_close_reason(unmute_requested=False, stopping=True,
        sent_code=1001, received_code=received) == 'expected_fixture_shutdown'
    assert expected_close_reason(unmute_requested=False, stopping=True,
        sent_code=None, received_code=received) is None


@pytest.mark.parametrize('received', [1002, 1008, 1011])
def test_explicit_peer_error_is_never_hidden_by_cleanup(received):
    assert expected_close_reason(unmute_requested=True, stopping=True,
                                 sent_code=1001, received_code=received) is None


def test_echoing_peer_close_is_not_server_initiated_deadline_shutdown():
    assert expected_close_reason(unmute_requested=False, stopping=True,
        sent_code=1001, received_code=1001, received_before_sent=True) is None


def aec_resources():
    return {'aec_ready':True,'aec_frames':20,'aec_reference_frames':18,
            'aec_process_max_us':4200,'audio_input_stack_hwm_bytes':1600,
            'internal_free':45000,'psram_free':3600000}


def test_hardware_aec_evidence_requires_new_reference_work_and_reports_limits():
    result=barge_aec_evidence({'aec_frames':2,'aec_reference_frames':1},aec_resources())
    assert result['new_aec_frames']==18
    assert result['new_reference_frames']==17
    assert result['human_wake_or_echo_rejection_accepted'] is False


@pytest.mark.parametrize('baseline',[{}, {'aec_frames':0}, {'aec_reference_frames':0},
    {'aec_frames':True,'aec_reference_frames':0}])
def test_missing_baseline_does_not_make_historical_aec_counters_look_new(baseline):
    with pytest.raises(ValueError,match='baseline_missing'):
        barge_aec_evidence(baseline,aec_resources())


@pytest.mark.parametrize('change',[
    {'aec_ready':False}, {'aec_frames':2}, {'aec_reference_frames':1},
    {'aec_process_max_us':0}, {'aec_process_max_us':32000},
    {'audio_input_stack_hwm_bytes':511}, {'audio_input_stack_hwm_bytes':True},
    {'psram_free':None},
])
def test_idle_ready_or_stale_counters_and_unsafe_processing_do_not_pass(change):
    with pytest.raises(ValueError):
        barge_aec_evidence({'aec_frames':2,'aec_reference_frames':1},{**aec_resources(),**change})
