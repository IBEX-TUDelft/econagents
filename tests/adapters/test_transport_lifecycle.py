"""WebSocketTransport connection lifecycle: one listen loop, re-authentication and send failures."""

import asyncio
import json

import pytest
import pytest_asyncio
import websockets

from econagents.adapters.transport import (
    AuthenticationMechanism,
    JoinPayloadAuth,
    TransportSendError,
    WebSocketTransport,
)


class RecordingServer:
    def __init__(self):
        self.connections: list[list[dict]] = []
        self.server = None
        self.url = ""

    async def handler(self, ws):
        received: list[dict] = []
        self.connections.append(received)
        try:
            async for raw in ws:
                received.append(json.loads(raw))
        except websockets.ConnectionClosed:
            pass

    async def start(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


@pytest_asyncio.fixture
async def server():
    srv = RecordingServer()
    await srv.start()
    yield srv
    await srv.stop()


async def wait_for(pred, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.02)
    return True


async def _shutdown(transport: WebSocketTransport, *tasks: asyncio.Task) -> None:
    await transport.stop()
    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5.0)


@pytest.mark.asyncio
async def test_second_start_listening_does_not_open_a_second_connection(server):
    transport = WebSocketTransport(
        url=server.url, auth_mechanism=JoinPayloadAuth(), auth_mechanism_kwargs={"recovery": "r"}
    )
    first = asyncio.create_task(transport.start_listening())
    assert await wait_for(lambda: len(server.connections) == 1 and server.connections[0])

    second = asyncio.create_task(transport.start_listening())
    await asyncio.wait_for(second, timeout=1.0)
    await asyncio.sleep(0.1)

    assert len(server.connections) == 1
    assert not first.done()
    await _shutdown(transport, first)


@pytest.mark.asyncio
async def test_connection_lost_during_authentication_reconnects_and_authenticates_again(server):
    class DropFirstJoin(AuthenticationMechanism):
        def __init__(self):
            self.attempts = 0

        async def authenticate(self, transport, **kwargs) -> bool:
            self.attempts += 1
            if self.attempts == 1:
                await transport.ws.close()
            await transport.send(json.dumps({"meta": {"type": "join"}, "payload": kwargs}))
            return True

    auth = DropFirstJoin()
    transport = WebSocketTransport(url=server.url, auth_mechanism=auth, auth_mechanism_kwargs={"recovery": "r"})
    task = asyncio.create_task(transport.start_listening())

    assert await wait_for(lambda: len(server.connections) >= 2 and server.connections[-1])
    assert server.connections[-1][0] == {"meta": {"type": "join"}, "payload": {"recovery": "r"}}
    assert auth.attempts == 2
    assert not task.done()
    await _shutdown(transport, task)


@pytest.mark.asyncio
async def test_send_after_stop_raises_transport_send_error(server):
    transport = WebSocketTransport(url=server.url)
    task = asyncio.create_task(transport.start_listening())
    assert await wait_for(lambda: transport.ws is not None)
    await _shutdown(transport, task)

    with pytest.raises(TransportSendError):
        await transport.send("{}")
    assert issubclass(TransportSendError, ConnectionError)


@pytest.mark.asyncio
async def test_send_does_not_relabel_a_programming_error_as_not_transmitted():
    class RejectingSocket:
        async def send(self, message):
            raise TypeError("data must be str or bytes")

    transport = WebSocketTransport(url="ws://127.0.0.1:1")
    transport.ws = RejectingSocket()

    with pytest.raises(TypeError):
        await transport.send({"not": "a string"})
