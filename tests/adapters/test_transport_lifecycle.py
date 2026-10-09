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


class RejectingServer:
    """Answers every join like IBEX logIn with an unknown recovery key: auth-error, then close."""

    def __init__(self, clean: bool):
        self.clean = clean
        self.connections: list[list[dict]] = []
        self.server = None
        self.url = ""

    async def handler(self, ws):
        received: list[dict] = []
        self.connections.append(received)
        try:
            async for raw in ws:
                received.append(json.loads(raw))
                await ws.send(json.dumps({"meta": {"type": "auth-error"}, "payload": {"reason": "unknown"}}))
                if self.clean:
                    await ws.close(1000)
                else:
                    ws.transport.abort()
                return
        except websockets.ConnectionClosed:
            pass

    async def start(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("clean", [False, True])
async def test_rejected_join_backs_off_instead_of_reconnecting_in_a_hot_loop(clean):
    srv = RejectingServer(clean=clean)
    await srv.start()
    delivered: list[str] = []

    async def on_message(raw):
        delivered.append(raw)

    transport = WebSocketTransport(
        url=srv.url,
        auth_mechanism=JoinPayloadAuth(),
        auth_mechanism_kwargs={"recovery": "stale"},
        on_message_callback=on_message,
    )
    task = asyncio.create_task(transport.start_listening())
    try:
        await asyncio.sleep(2.0)
        assert 2 <= len(srv.connections) <= 8, f"{len(srv.connections)} connections in 2 s"
        assert all(frames and frames[0]["meta"]["type"] == "join" for frames in srv.connections)
        assert not task.done()
    finally:
        await _shutdown(transport, task)
        await srv.stop()


@pytest.mark.asyncio
async def test_stop_interrupts_a_reconnect_backoff():
    srv = RejectingServer(clean=True)
    await srv.start()
    transport = WebSocketTransport(
        url=srv.url,
        auth_mechanism=JoinPayloadAuth(),
        auth_mechanism_kwargs={"recovery": "stale"},
        reconnect_delay=60.0,
        max_reconnect_delay=60.0,
    )
    task = asyncio.create_task(transport.start_listening())
    try:
        assert await wait_for(lambda: len(srv.connections) >= 2 and srv.connections[1])
        await asyncio.sleep(0.1)
        await transport.stop()
        await asyncio.wait_for(task, timeout=1.0)
        assert len(srv.connections) == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await srv.stop()


@pytest.mark.asyncio
async def test_reconnect_after_a_stable_connection_is_immediate():
    connections: list[list[dict]] = []

    async def close_after_half_a_second(ws):
        received: list[dict] = []
        connections.append(received)
        try:
            await asyncio.wait_for(_collect(ws, received), timeout=0.5)
        except asyncio.TimeoutError:
            await ws.close(1001)

    async def _collect(ws, received):
        async for raw in ws:
            received.append(json.loads(raw))

    server = await websockets.serve(close_after_half_a_second, "127.0.0.1", 0)
    transport = WebSocketTransport(
        url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}",
        auth_mechanism=JoinPayloadAuth(),
        auth_mechanism_kwargs={"recovery": "r"},
        reconnect_delay=60.0,
        stable_connection_seconds=0.3,
    )
    task = asyncio.create_task(transport.start_listening())
    try:
        assert await wait_for(lambda: len(connections) >= 4, timeout=4.0), f"{len(connections)} connections"
        assert all(frames and frames[0]["meta"]["type"] == "join" for frames in connections[:3])
    finally:
        await _shutdown(transport, task)
        server.close()
        await server.wait_closed()
