"""In-RAM cache of deterministic local time voice replies for HOST-A testing.

Piper may require seconds of CPU per short answer. Preparing a handful of
current/near-future minute phrases once during idle startup keeps replies
instant after a verified time command. No disk audio, no network/cloud, no
command performed before verification. Clock-minute key prevents stale time.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import threading

from host_local_command import TZ, time_reply
from host_local_tts import offline_russian_packets


class TimeAnswerCache:
    def __init__(self, voice_path: str | Path, *, synth=offline_russian_packets,
                 clock=None, ahead_minutes=4):
        if not 1 <= ahead_minutes <= 5:
            raise ValueError("bounded_time_audio_cache_required")
        self.voice_path = Path(voice_path)
        self.synth = synth
        self.clock = clock or (lambda: datetime.now(TZ))
        self.ahead_minutes = ahead_minutes
        self._cache = {}
        self._lock = threading.Lock()
        self._thread = None
        self._warmed_minutes = 0
        self._failed_minutes = 0

    @staticmethod
    def _key(moment):
        return moment.strftime("%Y-%m-%dT%H:%M%z")

    def _make(self, moment):
        return tuple(self.synth(self.voice_path, text=time_reply(moment)))

    def warm(self):
        """Run only in dedicated local startup thread, never on audio queue."""
        baseline = self.clock().replace(second=0, microsecond=0)
        for offset in range(self.ahead_minutes):
            moment = baseline + timedelta(minutes=offset)
            key = self._key(moment)
            with self._lock:
                if key in self._cache:
                    continue
            try:
                packets = self._make(moment)
                if not packets or len(packets) > 64:
                    raise ValueError("local_time_audio_packets_outside_bound")
            except Exception:
                with self._lock:
                    self._failed_minutes += 1
                continue
            with self._lock:
                self._cache[key] = packets
                self._warmed_minutes += 1
                # Never accumulate old audio beyond bounded horizon.
                if len(self._cache) > 5:
                    for expired in sorted(self._cache)[:-5]:
                        del self._cache[expired]

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self.warm, name="host-a-time-cache-startup", daemon=True
        )
        self._thread.start()

    def get(self):
        """Only called AFTER cloud name + time-command verification."""
        moment = self.clock()
        key = self._key(moment)
        with self._lock:
            reply = self._cache.get(key)
        if reply is not None:
            return reply, True
        # Correct time beats stale voice. Slow fallback is still safe.
        return self._make(moment), False

    def stats(self):
        with self._lock:
            return {"ready_minutes": len(self._cache),
                    "prepared": self._warmed_minutes,
                    "failed": self._failed_minutes}
