"""Ordered output with independent, bounded audio and control capacity.

PCM producers wait for their own capacity. A full audio reservation must not
reject the following end marker or a control event from another coroutine.
The combined bound remains 128 events, as on the original direct transport.
"""
import asyncio
from collections import deque


class DirectOutputQueue:
    def __init__(self, *, audio_limit=64, control_limit=64):
        self.audio_limit = audio_limit
        self.control_limit = control_limit
        self.maxsize = audio_limit + control_limit
        self._queue = deque()
        self._audio = 0
        self._control = 0
        self._available = asyncio.Event()
        self._capacity = asyncio.Event()

    @staticmethod
    def is_audio(event):
        return event is not None and event.get('type') == 'audio_chunk'

    def qsize(self):
        return len(self._queue)

    def empty(self):
        return not self._queue

    def full(self):
        # Synchronous callers publish control events (including wake sentinels).
        return self._control >= self.control_limit

    def _full_for(self, event):
        return self._audio >= self.audio_limit if self.is_audio(event) else self.full()

    def put_nowait(self, event):
        if self._full_for(event):
            raise asyncio.QueueFull
        self._queue.append(event)
        if self.is_audio(event):
            self._audio += 1
        else:
            self._control += 1
        self._available.set()

    async def put(self, event, *, is_current=lambda: True):
        while is_current():
            if not self._full_for(event):
                # No await between this ownership check and insertion. An old
                # producer cannot enqueue into a reattached subscriber's queue.
                self.put_nowait(event)
                return True
            self._capacity.clear()
            await self._capacity.wait()
        return False

    def get_nowait(self):
        if not self._queue:
            raise asyncio.QueueEmpty
        event = self._queue.popleft()
        if self.is_audio(event):
            self._audio -= 1
        else:
            self._control -= 1
        if not self._queue:
            self._available.clear()
        self._capacity.set()
        return event

    async def get(self):
        while self.empty():
            await self._available.wait()
        return self.get_nowait()
