"""Brain's supported SansIO protocol with flow control for installed Uvicorn.

Uvicorn 0.49 exposes a writable event but lacks the asyncio pause/resume hooks
and lost-connection wakeup present in newer releases. Keep audio sends bounded
without the legacy protocol's competing drain waiters, or a dependency upgrade.
"""

from uvicorn.protocols.utils import ClientDisconnected
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol


class BrainWebSocketProtocol(WebSocketsSansIOProtocol):
    _gobot_disconnected = False

    def pause_writing(self) -> None:
        self.writable.clear()

    def resume_writing(self) -> None:
        self.writable.set()

    def connection_lost(self, exc: Exception | None) -> None:
        self._gobot_disconnected = True
        try:
            super().connection_lost(exc)
        finally:
            # asyncio won't resume a writer whose transport has been lost.
            self.writable.set()

    async def send(self, message) -> None:
        if self._gobot_disconnected:
            raise ClientDisconnected()
        await self.writable.wait()
        if self._gobot_disconnected:
            raise ClientDisconnected()
        await super().send(message)
