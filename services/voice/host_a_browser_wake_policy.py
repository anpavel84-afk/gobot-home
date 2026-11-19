"""HOST-A browser-only name candidate policy over the EXACT existing Vosk.

This is a deterministic *post-recognizer* filter, not a new ASR model.
No changes to HOST-B, physical Spotpear or production detectors. All
candidates, including confident 'Моника', are verified against raw audio
by the existing real OpenAI STT before any Brain call.
"""
from __future__ import annotations

import re

from host_wake_contract import WakeEvent

NORMAL_NAME = "моника"
# Weak errors actually seen in owner test. Do not include "монитор", "фильм",
# or broad Levenshtein matches, to avoid paid hits on unrelated background.
WEAK_NAMES = frozenset({
    # Actual Vosk mistakes observed during OWNER's browser lab.
    "моник", "монки", "модников", "модеников", "модика", "маньяка",
    # Exact owner-requested broad candidates. These do NOT themselves wake
    # the Brain; real raw audio must still confirm canonical "Моника".
    "мой", "мойка", "мойник", "мои", "мойне", "мойни", "мойк",
})
SALUTATIONS = frozenset({
    ("окей",), ("ок",), ("о", "кей"), ("эй",), ("слушай",),
    ("слушайте",), ("привет",), ("ну",), ("а",), ("о",),
    ("ну", "слушай"), ("а", "ну"), ("пожалуйста",),
    ("слушай", "пожалуйста"),
})
NEGATIVE_CONTEXT = frozenset({
    "фильм", "фильме", "кино", "телевизор", "телевизору",
    "про", "об", "о", "показывали", "рассказывали", "история",
    "там", "слове", "тексте", "упоминали", "имя", "название",
    "модников",  # except when it IS the addressed first token
})


def words_of(text: str) -> tuple[str, ...]:
    if not isinstance(text, str) or not 1 <= len(text) <= 500:
        return ()
    return tuple(re.findall(r"[а-яё]+", text.casefold()))


def _weak_name(words: tuple[str,...], index: int) -> str | None:
    """Owner-approved broad 'мой…' probe, but not arbitrary substrings.

    Longer split form 'мой ник' is recognized as one hypothesized name.
    Single 'мой' and 'мойка' are intentionally permitted as WEAK,
    bounded by the existing session/global monetary limits.
    """
    token = words[index]
    if token == "мой" and index + 1 < len(words) and words[index+1] == "ник":
        return "мой ник"
    if token in WEAK_NAMES:
        return token
    # 'мой*' is deliberately restricted to one short word; words with
    # extra tokens ("мой телефон") still only make a weak probe, not a wake.
    if token.startswith("мой") and 3 <= len(token) <= 8:
        return token
    return None


def address_candidate(text: str) -> tuple[str, str, int] | None:
    """Return (strength, recognized token, index), anchored to an address.

    Vosk drops punctuation. We cannot treat every interior 'Моника' as an
    address: 'по телевизору фильм про Монику' must remain non-activating.
    """
    words = words_of(text)
    for index, token in enumerate(words[:5]):
        strength = "strong" if token == NORMAL_NAME else "weak"
        name = token if strength == "strong" else _weak_name(words, index)
        if name is None:
            continue
        pre = words[:index]
        if not pre or pre in SALUTATIONS or (
                index <= 3 and pre[-1:] in {
                    ("слушай",), ("эй",), ("окей",), ("привет",)
                } and not any(w in NEGATIVE_CONTEXT for w in pre)):
            return strength, name, index
    return None


def prefixed_monika(text: str) -> bool:
    match = address_candidate(text)
    return bool(match and match[2] > 0 and match[0] == "strong")


class BrowserAddressMatcher:
    """Two independent hypotheses OR final endpoint; bounded weak probes.

    Vosk sometimes emits one complete final sentence with NO distinct
    earlier partial. Endpoint itself counts as sufficient weak-candidate
    evidence for independent CLOUD verification, never Brain authorization.
    """

    def __init__(self, minimum_samples: int = 1600,
                 weak_limit: int = 3):
        if type(minimum_samples) is not int or not 1600 <= minimum_samples <= 4800:
            raise ValueError("invalid_minimum_stability")
        if type(weak_limit) is not int or not 0 <= weak_limit <= 5:
            raise ValueError("invalid_weak_candidate_limit")
        self.minimum_samples = minimum_samples
        self.weak_limit = weak_limit
        self.weak_total = 0
        self.epoch = None
        self.reset()

    def reset(self):
        self.first_at = None
        self.last_text = None
        self.previous_candidate = None
        self.fired = False
        self.last_strength = None
        self.last_name = None

    def feed(self, *, text: str, sample_cursor: int, stream_epoch: str,
             updated: bool, suppressed: bool, endpoint: bool=False) -> bool:
        if not isinstance(stream_epoch, str) or not stream_epoch:
            raise ValueError("browser_matcher_epoch_required")
        if type(sample_cursor) is not int or sample_cursor < 0:
            raise ValueError("browser_matcher_cursor_invalid")
        if self.epoch != stream_epoch:
            self.epoch = stream_epoch
            self.reset()
        if suppressed or self.fired:
            return False
        candidate = address_candidate(text)
        if candidate is None:
            self.first_at = None
            self.previous_candidate = None
            self.last_text = None
            return False
        strength, token, _ = candidate
        if strength == "weak" and self.weak_total >= self.weak_limit:
            return False
        if updated is not True:
            return False
        # A matching FINAL Vosk utterance may repeat the last partial text
        # verbatim, or be the only time this spelling appears. This must
        # still be forwarded as a *candidate* to the independent real-audio
        # verifier, not silently lost.
        final_match = endpoint is True
        if not final_match and text == self.last_text:
            return False
        self.last_text = text
        if self.previous_candidate != (strength, token):
            self.previous_candidate = (strength, token)
            self.first_at = sample_cursor
            if not final_match:
                return False
        if (not final_match and
                sample_cursor - self.first_at < self.minimum_samples):
            return False
        self.fired = True
        self.last_strength = strength
        self.last_name = token
        if strength == "weak":
            self.weak_total += 1
        return True


class BrowserWakeAdapter:
    """One shared B-side Vosk instance, one A-side wake policy, one WakeGate.

    The full detector still runs on every canonical 960-sample PCM frame.
    Only exact WakeEvent objects reach A's authoritative HostCore.
    """

    def __init__(self, delegate, gate, *, weak_limit=3):
        self.inner = delegate
        self.gate = gate
        self.matcher = BrowserAddressMatcher(weak_limit=weak_limit)
        self.suppress_events = False
        self.last_candidate_kind = None
        self.last_candidate_token = None
        self.last_wake_event = None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def feed_chunk(self, chunk):
        self.inner.suppress_events = self.suppress_events
        detected = self.inner.feed_chunk(chunk)
        hyp = getattr(self.inner.inner.lab, "last_hypothesis", None)
        custom = False
        if hyp is not None:
            custom = self.matcher.feed(
                text=str(hyp.text or ""), sample_cursor=chunk.end_sample_index,
                stream_epoch=chunk.stream_epoch, updated=bool(hyp.updated),
                suppressed=self.suppress_events,
                endpoint=bool(hyp.endpoint),
            )
        if detected is not None:
            self.last_candidate_kind = "strong"
            self.last_candidate_token = NORMAL_NAME
            self.matcher.fired = True
        elif custom:
            self.last_candidate_kind = self.matcher.last_strength
            self.last_candidate_token = self.matcher.last_name
            detected = WakeEvent(
                stream_epoch=chunk.stream_epoch,
                end_sample_index=chunk.end_sample_index,
                phrase_id="monika",
                detector_id="vosk-browser-address-v1",
                detected_monotonic_ns=chunk.received_monotonic_ns,
                confidence=None,
            )
        if detected is not None:
            self.last_wake_event = detected
        self.gate.feed(chunk, detected)
        return detected

    def reset(self):
        self.inner.reset()
        self.matcher.reset()
        self.last_candidate_kind = None
        self.last_candidate_token = None
