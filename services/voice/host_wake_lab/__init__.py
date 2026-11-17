"""GoBot HOST-B: isolated, no-network wake-recognition laboratory.

No production gateway, Brain, device connection, or paid provider is imported.
The source-of-truth PCM -> WakeEvent contract belongs to HOST-A (#5).
"""
from .detect import WakeLab, Hypothesis, WakeMatcher, DiscontinuousAudio

__all__ = ["WakeLab", "Hypothesis", "WakeMatcher", "DiscontinuousAudio"]
