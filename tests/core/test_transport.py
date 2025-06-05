import json
import logging
import pytest
import pytest_asyncio
import asyncio
from typing import List, Dict, Any, Optional
import socket
from contextlib import closing

import websockets
from websockets.exceptions import ConnectionClosed

from econagents.core.transport import WebSocketTransport, AuthenticationMechanism, SimpleLoginPayloadAuth


def find_free_port():
    """Find a free port on localhost to use for the test server."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("localhost", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


class MockWebSocketServer:
    """A lightweight WebSocket server for testing."""

    def __init__(self, host="localhost", port=None):
        """Initialize the test server."""
        self.host = host
        self.port = port or find_free_port()
        self.url = f"ws://{self.host}:{self.port}"
        self.server = None
        self.connected_clients = []  # Will store connected websocket clients
        self.received_messages: List[str] = []
        self.server_task = None
        self.should_run = False

    async def handler(self, websocket):
        """Handle incoming WebSocket connections."""
        self.connected_clients.append(websocket)
        try:
            async for message in websocket:
                self.received_messages.append(message)
                # If the message is a login message, send a success response
                try:
                    msg_data = json.loads(message)
                    if msg_data.get("type") == "login":
                        response = json.dumps(
                            {
                                "type": "loginResponse",
                                "success": True,
                                "message": "Login successful",
                            }
                        )
                        await websocket.send(response)
                except json.JSONDecodeError:
                    pass  # Not a JSON message, ignore
        except ConnectionClosed:
            pass
        finally:
            if websocket in self.connected_clients:
                self.connected_clients.remove(websocket)

    async def start(self):
        """Start the WebSocket server."""
        self.should_run = True
        self.server = await websockets.serve(handler=self.handler, host=self.host, port=self.port)

    async def stop(self):
        """Stop the WebSocket server."""
        self.should_run = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self.connected_clients = []
        self.received_messages = []

    async def send_to_all(self, message: str):
        """Send a message to all connected clients."""
        if not self.connected_clients:
            return

        for client in self.connected_clients[:]:  # Copy the list to avoid modification during iteration
            try:
                await client.send(message)
            except Exception:
                pass  # Ignore send errors

    async def send_event(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """Send an event message to all connected clients."""
        message = {"type": "event", "eventType": event_type, "data": data or {}}
        await self.send_to_all(json.dumps(message))


@pytest_asyncio.fixture
async def ws_server():
    """Provide a test WebSocket server."""
    server = MockWebSocketServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def logger():
    """Provide a logger for tests."""
    return logging.getLogger("test_logger")


@pytest.fixture
def login_payload():
    """Provide a sample login payload."""
    return {"type": "login", "gameId": 123, "role": 1, "token": "test_token"}


@pytest.fixture
def mock_callback():
    """Provide a mock callback function."""
    return asyncio.Event(), []


@pytest.fixture
def transport(logger, login_payload, mock_callback):
    """
    Provide a WebSocketTransport instance.

    The callback is a tuple of (event, messages),
    where event is triggered when a message is received
    and messages is a list where received messages are stored.
    """

    async def on_message(message_str):
        event, messages = mock_callback
        messages.append(message_str)
        event.set()

    # URL will be updated in tests with the server URL
    url = "ws://placeholder"
    auth_mechanism = SimpleLoginPayloadAuth()

    return WebSocketTransport(
        url=url,
        logger=logger,
        on_message_callback=on_message,
        auth_mechanism=auth_mechanism,
        auth_mechanism_kwargs=login_payload,
    )


class TestWebSocketTransport:
    """Tests for the WebSocketTransport class."""

    def test_initialization(self, transport, logger, mock_callback):
        """Test that the transport initializes correctly."""
        assert transport.url == "ws://placeholder"
        assert isinstance(transport.auth_mechanism, SimpleLoginPayloadAuth)
        assert transport.logger == logger
        assert callable(transport.on_message_callback)
        assert transport.ws is None
        assert transport._running is False

    async def _start_transport_and_wait_for_connection(self, transport, timeout=2.0):
        """Helper method to start transport and wait for connection."""
        # Start listening in background
        listen_task = asyncio.create_task(transport.start_listening())

        # Wait for connection to be established
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if transport.ws is not None and transport._running:
                return listen_task, True
            await asyncio.sleep(0.1)

        # Timeout - clean up
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

        return None, False

    @pytest.mark.asyncio
    async def test_connect_success(self, transport, login_payload, ws_server):
        """Test successful connection to WebSocket server."""
        transport.url = ws_server.url

        listen_task, connected = await self._start_transport_and_wait_for_connection(transport)

        try:
            assert connected is True
            assert transport.ws is not None
            assert transport._running is True

            await asyncio.sleep(0.2)
            assert len(ws_server.received_messages) >= 1

            login_found = False
            for msg in ws_server.received_messages:
                try:
                    msg_data = json.loads(msg)
                    if msg_data.get("type") == "login":
                        login_found = True
                        assert msg_data == login_payload
                        break
                except json.JSONDecodeError:
                    continue

            assert login_found, "Login message not found in received messages"

        finally:
            # Clean up
            await transport.stop()
            if listen_task:
                listen_task.cancel()
                try:
                    await listen_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_connect_failure(self, transport):
        """Test failed connection to WebSocket server."""
        transport.url = "ws://invalid-host:12345"

        listen_task, connected = await self._start_transport_and_wait_for_connection(transport, timeout=1.0)

        assert connected is False
        assert transport.ws is None

    @pytest.mark.asyncio
    async def test_auth_failure(self, transport, ws_server):
        """Test authentication failure."""
        transport.url = ws_server.url

        class FailingAuthMechanism(AuthenticationMechanism):
            async def authenticate(self, transport, **kwargs) -> bool:
                return False

        transport.auth_mechanism = FailingAuthMechanism()

        listen_task, connected = await self._start_transport_and_wait_for_connection(transport, timeout=1.0)

        assert connected is False
        assert transport.ws is None

    @pytest.mark.asyncio
    async def test_send_message(self, transport, ws_server):
        """Test sending a message via WebSocket."""
        transport.url = ws_server.url
        listen_task, connected = await self._start_transport_and_wait_for_connection(transport)

        try:
            assert connected is True

            ws_server.received_messages = []

            test_message = json.dumps({"type": "test", "data": {"value": "test"}})
            await transport.send(test_message)

            await asyncio.sleep(0.2)

            test_message_found = False
            for msg in ws_server.received_messages:
                try:
                    msg_data = json.loads(msg)
                    if msg_data.get("type") == "test":
                        test_message_found = True
                        assert msg_data == {"type": "test", "data": {"value": "test"}}
                        break
                except json.JSONDecodeError:
                    continue

            assert test_message_found, "Test message not found in received messages"

        finally:
            await transport.stop()
            if listen_task:
                listen_task.cancel()
                try:
                    await listen_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_send_message_no_connection(self, transport):
        """Test sending a message when no WebSocket connection exists."""
        transport.ws = None

        await transport.send("Test message")

    @pytest.mark.asyncio
    async def test_receive_message(self, transport, ws_server, mock_callback):
        """Test receiving a message from the server."""
        event, messages = mock_callback

        transport.url = ws_server.url
        listen_task, connected = await self._start_transport_and_wait_for_connection(transport)

        try:
            assert connected is True

            await asyncio.sleep(0.2)

            event.clear()
            messages.clear()

            test_event = {"type": "event", "eventType": "test_event", "data": {"value": "test_data"}}
            await ws_server.send_to_all(json.dumps(test_event))

            try:
                await asyncio.wait_for(event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pytest.fail("Timeout waiting for message to be received")

            assert len(messages) >= 1

            event_found = False
            for msg in messages:
                try:
                    msg_data = json.loads(msg)
                    if msg_data.get("type") == "event" and msg_data.get("eventType") == "test_event":
                        event_found = True
                        assert msg_data == test_event
                        break
                except json.JSONDecodeError:
                    continue

            assert event_found, "Test event not found in received messages"

        finally:
            await transport.stop()
            if listen_task:
                listen_task.cancel()
                try:
                    await listen_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_unrecoverable_connection_closed(self, transport, ws_server, mock_callback):
        """Test handling of connection closure."""
        transport.url = ws_server.url
        listen_task, connected = await self._start_transport_and_wait_for_connection(transport)

        try:
            assert connected is True

            await asyncio.sleep(0.2)

            original_ws = transport.ws

            await ws_server.stop()

            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < 2.0:
                if transport.ws != original_ws or transport._running is False:
                    break
                await asyncio.sleep(0.1)

            assert transport.ws != original_ws or transport.ws is None or transport._running is False

        finally:
            await transport.stop()
            if listen_task and not listen_task.done():
                listen_task.cancel()
                try:
                    await listen_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_recoverable_connection_closed(self, transport, ws_server, mock_callback):
        """Test handling of recoverable connection closure."""
        event, messages = mock_callback

        transport.url = ws_server.url
        listen_task, connected = await self._start_transport_and_wait_for_connection(transport)

        try:
            assert connected is True
            initial_ws = transport.ws

            messages.clear()
            event.clear()

            test_message_1 = {"type": "test", "message": "before_disconnect"}
            await ws_server.send_to_all(json.dumps(test_message_1))

            try:
                await asyncio.wait_for(event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pytest.fail("Timeout waiting for initial message")

            assert len(messages) >= 1

            await ws_server.stop()

            await asyncio.sleep(0.5)

            await ws_server.start()

            start_time = asyncio.get_event_loop().time()
            reconnected = False
            while (asyncio.get_event_loop().time() - start_time) < 5.0:
                if transport.ws is not None and transport.ws != initial_ws and transport._running:
                    reconnected = True
                    break
                await asyncio.sleep(0.2)

            assert reconnected, "Transport did not reconnect after server restart"

            messages.clear()
            event.clear()

            await transport.send(json.dumps({"type": "test", "message": "after_reconnect"}))
            await asyncio.sleep(0.2)

            reconnect_message_found = False
            for msg in ws_server.received_messages:
                try:
                    msg_data = json.loads(msg)
                    if msg_data.get("type") == "test" and msg_data.get("message") == "after_reconnect":
                        reconnect_message_found = True
                        break
                except json.JSONDecodeError:
                    continue

            assert reconnect_message_found, "Message not received after reconnection"

            test_message_2 = {"type": "test", "message": "server_to_client_after_reconnect"}
            await ws_server.send_to_all(json.dumps(test_message_2))

            try:
                await asyncio.wait_for(event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pytest.fail("Timeout waiting for message after reconnection")

            reconnect_event_found = False
            for msg in messages:
                try:
                    msg_data = json.loads(msg)
                    if msg_data.get("type") == "test" and msg_data.get("message") == "server_to_client_after_reconnect":
                        reconnect_event_found = True
                        break
                except json.JSONDecodeError:
                    continue

            assert reconnect_event_found, "Message not received from server after reconnection"

        finally:
            await transport.stop()
            if listen_task:
                listen_task.cancel()
                try:
                    await listen_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_stop(self, transport, ws_server):
        """Test stopping the transport."""
        transport.url = ws_server.url
        listen_task, connected = await self._start_transport_and_wait_for_connection(transport)

        try:
            assert connected is True
            assert transport._running is True

            await transport.stop()

            assert transport._running is False

        finally:
            if listen_task:
                listen_task.cancel()
                try:
                    await listen_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_auth_mechanism_called(self, transport, ws_server, login_payload):
        """Test that the auth_mechanism's authenticate method is called with the correct parameters."""
        transport.url = ws_server.url

        auth_called = False
        received_kwargs = {}

        class MockAuthMechanism(AuthenticationMechanism):
            async def authenticate(self, transport_obj, **kwargs):
                nonlocal auth_called, received_kwargs
                auth_called = True
                received_kwargs = kwargs
                auth_message = json.dumps(kwargs)
                await transport_obj.send(auth_message)
                return True

        transport.auth_mechanism = MockAuthMechanism()

        listen_task, connected = await self._start_transport_and_wait_for_connection(transport)

        try:
            assert connected is True

            assert auth_called is True

            assert received_kwargs == login_payload

        finally:
            await transport.stop()
            if listen_task:
                listen_task.cancel()
                try:
                    await listen_task
                except asyncio.CancelledError:
                    pass
