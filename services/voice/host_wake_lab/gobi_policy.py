"""Owner-directed GoBot HOST-B 2026-11-16: independently benchmark Gobi / Globi.

Do not change the project name or enable any wake in the live gateway.
One and ONLY one candidate is evaluated per detector instance. In particular,
"гоби" is not a spelling alias for "глоби" or "а гоби". The optional "эй
гоби" is likewise an independent reserve candidate, not silently enabled.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Literal

from .detect import WakeLab
from .engines import VoskOnline, make_backend

CandidateId = Literal["gobi", "globi", "a_gobi", "hey_gobi"]

# Exact token patterns, not fuzzy matches or forced Vosk grammars.
CANDIDATES = {
    "gobi": ("гоби",),
    "globi": ("глоби",),
    "a_gobi": ("а", "гоби"),
    "hey_gobi": ("эй", "гоби"),
}
CANDIDATE_DISPLAY = {
    "gobi": "Го́би",
    "globi": "Гло́би",
    "a_gobi": "А, Го́би",
    "hey_gobi": "Эй, Го́би",
}


def candidate_for(text: str, candidate_id: str) -> str | None:
    """Whole Cyrillic words, anchored to FIRST token; accents removed by ASR.

    No long-string substring matches; matching a prefix is forbidden when
    that prefix is part of another candidate (e.g. 'а гоби' must not fire
    'гоби').
    """
    if candidate_id not in CANDIDATES:
        raise ValueError("unknown_candidate")
    tokens = re.findall(r"[а-яё]+", str(text).casefold())
    pattern = CANDIDATES[candidate_id]
    return candidate_id if tuple(tokens[:len(pattern)]) == pattern else None


class CandidateMatcher:
    """Exact candidate + 2 independent ASR updates separated by >=100ms.

    Preserve stable-first-phrase behavior from HOST-B; no change to the existing
    GoBot/Gabot policy. Candidate and required lexicon are immutable by design.
    """
    def __init__(self, candidate_id: str, *, min_stability_samples: int = 1600):
        if candidate_id not in CANDIDATES:
            raise ValueError("unknown_candidate")
        if type(min_stability_samples) is not int or min_stability_samples < 1:
            raise ValueError("invalid_stability")
        self.candidate_id = candidate_id
        self.minimum = min_stability_samples
        self.reset()

    def reset(self):
        self.first_at = None
        self.fired = False

    def observe(self, text: str, end_sample_index: int) -> str | None:
        if self.fired:
            return None
        if candidate_for(text, self.candidate_id) is None:
            self.first_at = None
            return None
        if self.first_at is None:
            self.first_at = end_sample_index
            return None
        if end_sample_index - self.first_at < self.minimum:
            return None
        self.fired = True
        return self.candidate_id


def make_candidate_backend(engine_name: str, models_root, candidate_id: str,
                           threads: int = 1):
    if candidate_id not in CANDIDATES:
        raise ValueError("unknown_candidate")
    if engine_name == "vosk":
        # Precise existing dictionary gate. No fake custom-word grammar.
        return VoskOnline(models_root, num_threads=threads,
                          required_words=CANDIDATES[candidate_id])
    return make_backend(engine_name, models_root, threads=threads)


def make_candidate_lab(engine_name: str, models_root, candidate_id: str, *,
                       threads: int = 1, clock=None):
    backend = make_candidate_backend(engine_name, models_root, candidate_id,
                                     threads=threads)
    kwargs = {"matcher": CandidateMatcher(candidate_id)}
    if clock is not None:
        kwargs["clock"] = clock
    return WakeLab(backend, **kwargs)
