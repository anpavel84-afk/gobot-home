"""A finite fixture must not turn an unsolicited disconnect into a PASS."""
import pytest

from tools.sophia_hardware_fixture import expected_close_reason


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
