"""A finite fixture must not turn an unsolicited disconnect into a PASS."""
import asyncio
import json

import pytest

from tools.sophia_hardware_fixture import (FixtureBrain, argument_parser, barge_aec_evidence,
                                         barge_sr_evidence, expected_close_reason, wait_until)


@pytest.mark.parametrize('request_id', [None, 'physical-mute-request'])
def test_fixture_mute_echo_preserves_gateway_request_correlation(request_id):
    async def run():
        brain = FixtureBrain({})
        command = {'type': 'mute', 'muted': True}
        if request_id is not None:
            command['request_id'] = request_id
        await brain.send(json.dumps(command))
        data = json.loads(await brain.__anext__())
        assert data == {'type': 'muted', 'data': {key: value for key, value in command.items()
                                               if key != 'type'}}
    asyncio.run(run())


@pytest.mark.parametrize('revision', [None, 0, 14, 4294967295])
def test_fixture_full_handshake_echoes_current_device_revision_and_keeps_legacy(revision):
    from test_sophia_gateway import connection

    async def run():
        gateway = connection()
        report = {'empty_fixture_transports': 0, 'actual_wake_events': 0,
                  'fixture_pcm24_samples': 0}
        brain = FixtureBrain(report)
        gateway.connector = lambda *args, **kwargs: brain
        ack = {'type': 'gobot_host_ready_ack', 'protocol': 2,
               'session_id': gateway.transport, 'epoch': gateway.epoch,
               'frame_samples': 960, 'pcm_stage': 'pre_afe',
               'stream_epoch': 'fresh-capture', 'sample_start': 0}
        if revision is not None:
            ack.update(mute_revision=revision, muted=False)
        await gateway.device.queue.put(json.dumps(ack))
        hello = {'host_stream': {'version': 2, 'local_wake_enabled': True,
                                'capture': 'continuous', 'pcm_stage': 'pre_afe'}}
        task = asyncio.create_task(gateway.run(gateway.device, hello, lambda _: True))

        def controls():
            return [message for raw in gateway.device.sent
                    if isinstance(raw, str) and
                    (message := json.loads(raw)).get('type') == 'gobot_host_mute']

        try:
            await wait_until(lambda: gateway.cloud_ready.is_set() and
                             gateway.latest_physical_mute_request is None, 2)
            assert gateway.device_mute_revision == revision
            assert not gateway.muted and not gateway.forward
            start_count = len(controls())
            assert start_count == (0 if revision is None else 1)
            for desired in (True, False):
                brain.emit('muted', muted=desired)
                await wait_until(lambda: gateway.muted is desired and
                                 len(controls()) > start_count and
                                 controls()[-1]['muted'] is desired, 2)
                start_count += 1
                wire = controls()[-1]
                if revision is None:
                    assert 'mute_revision' not in wire
                else:
                    assert wire['mute_revision'] == revision
            assert not gateway.forward and gateway.ring.cursor is None
            assert gateway.latest_physical_mute_request is None
            assert report == {'empty_fixture_transports': 1, 'actual_wake_events': 0,
                              'fixture_pcm24_samples': 0}
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


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


def sr_baseline():
    return {'aec_frames':2,'aec_reference_frames':1,'wake_barge_frames':10,
            'wake_barge_gaps':2,'wake_barge_processing_overrun_frames':0}


def sr_resources():
    return {**aec_resources(),'host_wake_mode':2,'wake_barge_frames':28,
            'wake_barge_gaps':2,'wake_barge_processing_overrun_frames':0,
            'wake_barge_process_max_us':25280,'wake_barge_detections':0,
            'wake_barge_accepted':0,'aec_level_frame':20,
            'aec_mic_avg_abs':540,'aec_ref_avg_abs':1024,'aec_clean_avg_abs':60,
            'aec_mic_peak':2000,'aec_ref_peak':4096,'aec_clean_peak':220}


def test_mode3_detector_progress_requires_real_new_aec_reference_but_no_detected_word():
    result=barge_sr_evidence(sr_baseline(),sr_resources())
    assert result['mode3_detector_processed'] is True
    assert result['new_wake_barge_frames']==18
    assert result['new_aec_frames']==18 and result['new_reference_frames']==17
    assert result['new_wake_barge_gaps']==result['new_processing_overrun_frames']==0
    assert result['wake_barge_process_max_us']==25280
    assert result['frame_duration_us']==32000
    assert result['audio_input_stack_hwm_bytes']==1600
    assert result['last_aec_frame_levels']['aec_level_frame']==20
    assert result['last_aec_frame_levels']['aec_clean_peak']==220
    assert result['acoustic_or_human_acceptance'] is False
    assert result['human_wake_or_echo_rejection_accepted'] is False


@pytest.mark.parametrize('change',[
    {'wake_barge_frames':10}, {'wake_barge_frames':9},
    {'wake_barge_gaps':3}, {'wake_barge_gaps':1},
    {'wake_barge_processing_overrun_frames':1},
    {'wake_barge_process_max_us':32001}, {'wake_barge_process_max_us':0},
    {'wake_barge_process_max_us':True}, {'wake_barge_process_max_us':float('inf')},
    {'wake_barge_frames':True}, {'wake_barge_frames':2**63},
    {'wake_barge_frames':float('nan')}, {'wake_barge_gaps':2.0},
    {'aec_frames':2}, {'aec_reference_frames':1},
    {'audio_input_stack_hwm_bytes':511},
])
def test_aec_alone_stale_detector_gaps_overruns_and_bad_values_never_pass_sr_gate(change):
    with pytest.raises(ValueError):
        barge_sr_evidence(sr_baseline(),{**sr_resources(),**change})


def test_combined_timing_limit_matches_strictly_greater_than_overrun_counter():
    result=barge_sr_evidence(sr_baseline(),{**sr_resources(),
        'wake_barge_process_max_us':32000,'audio_input_stack_hwm_bytes':512})
    assert result['mode3_detector_processed'] and result['new_processing_overrun_frames']==0


@pytest.mark.parametrize('key',[
    'wake_barge_frames','wake_barge_gaps','wake_barge_processing_overrun_frames',
])
def test_missing_or_invalid_sr_baseline_cannot_turn_historical_work_into_new_work(key):
    baseline=sr_baseline()
    baseline.pop(key)
    with pytest.raises(ValueError,match='barge_sr_baseline_missing'):
        barge_sr_evidence(baseline,sr_resources())
    for value in (True,-1,2**63,float('nan')):
        with pytest.raises(ValueError,match='barge_sr_baseline_missing'):
            barge_sr_evidence({**sr_baseline(),key:value},sr_resources())


def test_processing_overrun_counter_reset_is_not_a_successful_zero_delta():
    with pytest.raises(ValueError,match='barge_sr_processing_overrun_or_counter_reset'):
        barge_sr_evidence({**sr_baseline(),'wake_barge_processing_overrun_frames':1},sr_resources())


def test_optional_level_snapshot_must_be_coherent_bounded_integers():
    for change in ({'aec_level_frame':0},{'aec_clean_peak':True},
                   {'aec_mic_avg_abs':32769},{'aec_clean_avg_abs':float('nan')}):
        result=barge_sr_evidence(sr_baseline(),{**sr_resources(),**change})
        assert 'last_aec_frame_levels' not in result
        assert result['acoustic_or_human_acceptance'] is False
        json.dumps(result,allow_nan=False)


def test_sr_flag_is_optional_and_old_aec_flag_and_old_firmware_evidence_remain_valid():
    parser=argument_parser()
    default=parser.parse_args(['--report','unused.json'])
    old=parser.parse_args(['--report','unused.json','--require-barge-aec'])
    new=parser.parse_args(['--report','unused.json','--require-barge-sr'])
    assert not default.require_barge_aec and not default.require_barge_sr
    assert old.require_barge_aec and not old.require_barge_sr
    assert new.require_barge_sr
    assert barge_aec_evidence({'aec_frames':2,'aec_reference_frames':1},
                              aec_resources())['new_aec_frames']==18
    with pytest.raises(ValueError,match='barge_sr_baseline_missing'):
        barge_sr_evidence({'aec_frames':2,'aec_reference_frames':1},aec_resources())
