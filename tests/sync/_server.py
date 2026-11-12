from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.typing import Subprotocol

from browserless_bap.transport import SUBPROTOCOL


class ServerThread:
    """A graphql-transport-ws fake on a loop independent from the sync bridge."""

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._url: str | None = None
        self.subscribe_count = 0
        self.complete_count = 0
        self.live_url_variables: dict[str, Any] | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="bap-test-server",
            daemon=True,
        )

    @property
    def url(self) -> str:
        if self._url is None:
            raise RuntimeError("ServerThread has not started")
        return self._url

    @property
    def thread_name(self) -> str:
        return self._thread.name

    def __enter__(self) -> ServerThread:
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("ServerThread failed to start")
        if self._error is not None:
            raise RuntimeError("ServerThread failed to start") from self._error
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._loop is not None and self._shutdown is not None:
            self._loop.call_soon_threadsafe(self._shutdown.set)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("ServerThread failed to stop")
        if self._error is not None:
            raise RuntimeError("ServerThread failed") from self._error

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as error:
            self._error = error
            self._ready.set()

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._shutdown = asyncio.Event()
        async with serve(
            self._handle,
            "127.0.0.1",
            0,
            subprotocols=[Subprotocol(SUBPROTOCOL)],
        ) as server:
            port = server.sockets[0].getsockname()[1]
            self._url = f"ws://127.0.0.1:{port}"
            self._ready.set()
            await self._shutdown.wait()

    async def _handle(self, socket: ServerConnection) -> None:
        live_subscription: str | None = None
        async for raw in socket:
            frame = json.loads(raw)
            frame_type = frame.get("type")
            if frame_type == "connection_init":
                await socket.send(json.dumps({"type": "connection_ack"}))
                continue
            if frame_type == "complete":
                self.complete_count += 1
                continue
            if frame_type != "subscribe":
                continue
            self.subscribe_count += 1
            operation_id = frame["id"]
            query = frame.get("payload", {}).get("query", "")
            if query.lstrip().startswith("subscription") and "console" in query:
                await self._next(
                    socket,
                    operation_id,
                    {
                        "console": {
                            "type": "log",
                            "text": "hello",
                            "args": [],
                            "timestamp": 0,
                        }
                    },
                )
                continue
            if query.lstrip().startswith("subscription") and "liveComplete" in query:
                live_subscription = operation_id
                continue
            if "closeLiveURL" in query:
                data: dict[str, Any] = {"closeLiveURL": {"liveURLId": "link"}}
            elif "liveURL" in query:
                self.live_url_variables = frame["payload"].get("variables", {})
                assert live_subscription is not None
                await self._next(
                    socket,
                    live_subscription,
                    {"liveComplete": {"liveURLId": "link", "reason": "userDone"}},
                )
                data = {
                    "liveURL": {
                        "liveURLId": "link",
                        "liveURL": "https://example.com/live",
                    }
                }
            elif "goto" in query:
                data = {
                    "goto": {
                        "status": 200,
                        "url": "https://example.com",
                    }
                }
            elif "title" in query:
                data = {"title": {"title": "Mock Title", "time": 0}}
            else:
                data = {}
            await self._next(socket, operation_id, data)
            await socket.send(json.dumps({"id": operation_id, "type": "complete"}))

    @staticmethod
    async def _next(
        socket: ServerConnection,
        operation_id: str,
        data: dict[str, Any],
    ) -> None:
        await socket.send(
            json.dumps(
                {
                    "id": operation_id,
                    "type": "next",
                    "payload": {"data": data},
                }
            )
        )
