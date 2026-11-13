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
        if frame.metadata.timer_id:
            payload["timer_key"] = frame.metadata.timer_id
    weather = frame.metadata.weather
    if frame.type == "weather_card" and weather:
        payload["weather_icon"] = weather.icon
        payload["text"] = weather.condition
        if weather.days:
            day = weather.days[0]
            payload["title"] = f"{day.low:g}…{day.high:g} °C"
        elif "temperature" in frame.metadata.facts:
            payload["title"] = frame.metadata.facts["temperature"] + " °C"
    return command
