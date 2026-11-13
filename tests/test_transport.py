import asyncio
import base64
import json
import logging
import traceback

import pytest
from websockets.asyncio.server import ServerConnection, serve

from browserless_bap import Browserless, __version__
from browserless_bap.errors import BrowserQLError, ConnectionError
from browserless_bap.errors import TimeoutError as BAPTimeoutError
from browserless_bap.transport import Transport


@pytest.mark.parametrize("stall", [False, True])
async def test_no_traceback_frame_holds_token(stall: bool) -> None:
    eof = asyncio.Event()

    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            if stall:
                await reader.readuntil(b"\r\n\r\n")
                assert await reader.read() == b""
                eof.set()
        finally:
            writer.close()
            await writer.wait_closed()

    async with await asyncio.start_server(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with Browserless.connect(
            browser_ws_endpoint=f"ws://127.0.0.1:{port}/bql",
            token="SECRET-TRACEBACK",
            timeout=100,
        ) as browser:
            async with asyncio.timeout(3):
                with pytest.raises(
                    BAPTimeoutError if stall else ConnectionError
                ) as caught:
                    await browser.new_page()
            if stall:
                assert isinstance(caught.value, BAPTimeoutError)
                assert caught.value.operation == "connect"
                assert caught.value.timeout_ms == 100
                await asyncio.wait_for(eof.wait(), 2)
            assert "SECRET-TRACEBACK" not in str(caught.value)
            for frame, _ in traceback.walk_tb(caught.value.__traceback__):
                assert not any(
                    "SECRET-TRACEBACK" in repr(value)
                    for value in frame.f_locals.values()
                ), frame.f_code.co_name


@pytest.mark.asyncio
async def test_connection_traceback_redacts_token() -> None:
    async with Browserless.connect(
        browser_ws_endpoint="https://example.invalid/bql", token="SECRET456"
    ) as browser:
        with pytest.raises(ConnectionError) as caught:
            await browser.new_page()

    assert "SECRET456" not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert "token=<redacted>" in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("userinfo", ["", "sdk-user:sdk-password@"])
async def test_client_debug_log_redacts_token(
    caplog: pytest.LogCaptureFixture, userinfo: str
) -> None:
    authorization_headers: list[str | None] = []

    async def handler(socket: ServerConnection) -> None:
        assert socket.request is not None
        authorization_headers.append(socket.request.headers.get("Authorization"))
        async for _ in socket:
            pass

    caplog.set_level(logging.DEBUG)
    async with serve(handler, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        async with Browserless.connect(
            browser_ws_endpoint=f"ws://{userinfo}127.0.0.1:{port}/bql",
            token="SECRET123",
        ) as browser:
            await browser.new_page()

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "browserless_bap.websockets"
    ]
    assert any("GET /bql?token=<redacted>" in message for message in messages)
    assert all("SECRET123" not in message for message in messages)
    if userinfo:
        credentials = base64.b64encode(userinfo[:-1].encode()).decode()
        assert authorization_headers == [f"Basic {credentials}"]
        assert any("Authorization: <redacted>" in message for message in messages)
        assert all(credentials not in message for message in messages)
    else:
        assert authorization_headers == [None]


@pytest.mark.asyncio
async def test_real_socket_user_agent_and_large_next_frame() -> None:
    user_agents: list[str] = []
    payload = "x" * (1024 * 1024 + 1)

    async def handler(socket: ServerConnection) -> None:
        assert socket.request is not None
        user_agents.append(socket.request.headers["User-Agent"])
        async for raw in socket:
            frame = json.loads(raw)
            if frame["type"] == "connection_init":
                await socket.send(json.dumps({"type": "connection_ack"}))
            elif frame["type"] == "subscribe":
                await socket.send(
                    json.dumps(
                        {
                            "id": frame["id"],
                            "type": "next",
                            "payload": {"data": {"value": payload}},
                        }
                    )
                )
                await socket.send(json.dumps({"id": frame["id"], "type": "complete"}))

    async with serve(handler, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        transport = Transport(f"ws://127.0.0.1:{port}")
        result: dict[str, str] = await transport.send("query { value }")
        await transport.close()

    assert user_agents == [f"browserless-bap/{__version__}"]
    assert result == {"value": payload}


@pytest.mark.asyncio
async def test_real_socket_maps_graphql_errors() -> None:
    async def handler(socket: ServerConnection) -> None:
        async for raw in socket:
            frame = json.loads(raw)
            if frame["type"] == "connection_init":
                await socket.send(json.dumps({"type": "connection_ack"}))
            elif frame["type"] == "subscribe":
                await socket.send(
                    json.dumps(
                        {
                            "id": frame["id"],
                            "type": "next",
                            "payload": {"errors": [{"message": "bad query"}]},
                        }
                    )
                )

    async with serve(handler, "127.0.0.1", 0) as server:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        transport = Transport(f"ws://127.0.0.1:{port}")
        with pytest.raises(BrowserQLError, match="bad query"):
            await transport.send("query { nope }")
        await transport.close()
