"""Translate the existing Brain presentation for a Spotpear whose wall clock may be unset."""
import time
from gobot.presentation import Presentation, esp32_projection


def project_scene(data, *, now=None):
    frame = Presentation.model_validate(data)
    command = esp32_projection(frame)
    payload = command["payload"]
    if frame.type == "timer_widget" and frame.metadata.deadline is not None:
        seconds = frame.metadata.deadline - (time.time() if now is None else now)
        payload["remaining_ms"] = max(0, min(86400000, round(seconds * 1000)))
    return command
