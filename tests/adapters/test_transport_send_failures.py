"""Reproduction for IBEX-game_suite#8: a send that does not reach the wire must be observable.

Today ``WebSocketTransport.send`` returns ``None`` when there is no socket and logs-and-swallows
exceptions from the socket, so the Agent cannot tell "sent" from "not sent" (a lost request).
The checks accept any observable signal: an exception, ``False``, or a result whose
``transmitted`` attribute is ``False``.
"""

import asyncio
import json

import pytest
import websockets
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from econagents.adapters.transport import WebSocketTransport

POST_ORDER = json.dumps(
    {
        "meta": {"type": "post-order", "component": {"type": "standard:dam", "name": "no_project"}},
        "payload": {"sender": 2, "type": "bid", "price": 1041, "timestamp": 1791555677396, "now": False},
    }
)


async def _send_outcome(transport: WebSocketTransport, message: str) -> tuple[object, BaseException | None]:
    try:
        return await transport.send(message), None
    except Exception as exc:
        return None, exc


def _reported_failure(result: object, error: BaseException | None) -> bool:
    return error is not None or result is False or getattr(result, "transmitted", None) is False


def _reported_success(result: object, error: BaseException | None) -> bool:
    return error is None and result is not False and getattr(result, "transmitted", True) is not False


class _BrokenSocket:
    """A socket whose peer vanished: every send raises like websockets does after a 1006 close."""

    def __init__(self):
        self.attempts: list[str] = []

    async def send(self, message: str) -> None:
        self.attempts.append(message)
        raise ConnectionClosedError(None, Close(1006, ""), None)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_send_without_socket_is_observable():
    transport = WebSocketTransport(url="ws://127.0.0.1:1")
    assert transport.ws is None

    result, error = await _send_outcome(transport, POST_ORDER)

    assert _reported_failure(result, error), (
        f"send() with no socket returned {result!r} and raised nothing: the lost request is invisible to the caller"
    )


@pytest.mark.asyncio
async def test_send_on_closed_socket_is_observable():
    transport = WebSocketTransport(url="ws://127.0.0.1:1")
    broken = _BrokenSocket()
    transport.ws = broken

    result, error = await _send_outcome(transport, POST_ORDER)

    assert broken.attempts == [POST_ORDER]
    assert _reported_failure(result, error), (
        f"send() on a closed socket returned {result!r} and raised nothing: "
        "the ConnectionClosed was logged and swallowed"
    )


@pytest.mark.asyncio
async def test_send_on_live_socket_delivers_exact_frame():
    """Guard: making failures observable must not turn a successful send into a failure."""
    received: list[str] = []
    arrived = asyncio.Event()

    async def handler(ws):
        async for raw in ws:
            received.append(raw)
            arrived.set()

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    transport = WebSocketTransport(url=f"ws://127.0.0.1:{port}")
    task = asyncio.create_task(transport.start_listening())
    try:
        async with asyncio.timeout(5):
            while transport.ws is None:
                await asyncio.sleep(0.01)

        result, error = await _send_outcome(transport, POST_ORDER)

        assert _reported_success(result, error), f"live send reported failure: result={result!r} error={error!r}"
        async with asyncio.timeout(5):
            await arrived.wait()
        assert received == [POST_ORDER]
    finally:
        await transport.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()
