"""Single-word Monika detector factory for HOST-A's existing AudioChunk/WakeEvent.

IMPORTANT: This module does not install a gateway, update an ESP32, change
HOST-A's config, create a server, or activate a paid AI conversation.

- PRODUCTION and unapproved test default: SHADOW ONLY (None on all frames).
- A selected, separately approved, finite HOST-A hardware acceptance listener
  may set allow_experimental_events=True; that setting does NOT certify the
  detector or authorize normal gateway deployment.
- No other wake names are enabled (including GoBot, Gobi, Globi, Hey Gobi).
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable

from .bridge import HostWakeDetectorAdapter
from .gobi_policy import CANDIDATES, make_candidate_backend

WAKE_ID = "monika"
WAKE_TEXT = "Моника"


def make_monika_detector(models_root: str | Path, *,
                         allow_experimental_events: bool = False,
                         isolated_hardware_test: bool = False,
                         wake_event_type=None,
                         threads: int = 1) -> HostWakeDetectorAdapter:
    """Returns a compatible HOST-A detector (always fail-closed by default).

    Experimental event emission has two explicit gates:
    1) allow_experimental_events=True must be set by HOST-A Owner/maintainer
    2) isolated_hardware_test=True: never as normal or production gateway.

    Even in this mode the only effect is sending a WakeEvent to HOST-A's
    existing HostCore; HOST-A remains the owner of activation, STOP and output.
    """
    if CANDIDATES[WAKE_ID] != ("моника",):
        raise RuntimeError("monika_policy_not_exact")
    if allow_experimental_events and not isolated_hardware_test:
        raise PermissionError("monika_event_requires_isolated_A_hardware_test")
    if type(threads) is not int or not 1 <= threads <= 2:
        raise ValueError("bounded_cpu_threads_required")
    backend = make_candidate_backend("vosk",models_root,WAKE_ID,threads=threads)
    if backend.word_ids.get("моника", -1) < 0:
        raise ValueError("monika_out_of_vocabulary")
    return HostWakeDetectorAdapter(
        backend, candidate_id=WAKE_ID,
        activation_approved=(allow_experimental_events and isolated_hardware_test),
        wake_event_type=wake_event_type,
    )


def make_monika_factory(models_root: str | Path, *,
                        allow_experimental_events: bool = False,
                        isolated_hardware_test: bool = False,
                        wake_event_type=None) -> Callable[[], HostWakeDetectorAdapter]:
    """One factory per HOST-A connection; no persistent second worker."""
    root = Path(models_root)
    def new_detector():
        return make_monika_detector(
            root, allow_experimental_events=allow_experimental_events,
            isolated_hardware_test=isolated_hardware_test,
            wake_event_type=wake_event_type,
        )
    return new_detector
