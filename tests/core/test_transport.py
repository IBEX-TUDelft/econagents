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


class TestWebSocketServer:
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
    server = TestWebSocketServer()
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

    def on_message(message_str):
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

    @pytest.mark.asyncio
    async def test_connect_success(self, transport, login_payload, ws_server):
        """Test successful connection to WebSocket server."""
        # Update the transport URL to point to our test server
        transport.url = ws_server.url

        # Connect to the server
        connected = await transport.connect()

        # Verify connection was successful
        assert connected is True
        assert transport.ws is not None

        # Verify login payload was sent to the server
        await asyncio.sleep(0.2)  # Small delay to ensure message is processed
        assert len(ws_server.received_messages) >= 1

        # Check if any of the received messages match our login payload
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

    @pytest.mark.asyncio
    async def test_connect_failure(self, transport):
        """Test failed connection to WebSocket server."""
        # Set an invalid URL to force connection failure
        transport.url = "ws://invalid-host:12345"

        # Try to connect
        connected = await transport.connect()

        # Verify connection failed
        assert connected is False
        assert transport.ws is None

    @pytest.mark.asyncio
    async def test_auth_failure(self, transport, ws_server):
        """Test authentication failure."""
        # Update the transport URL to point to our test server
        transport.url = ws_server.url

        # Create a failing authentication mechanism
        class FailingAuthMechanism(AuthenticationMechanism):
            async def authenticate(self, transport, **kwargs) -> bool:
                return False

        transport.auth_mechanism = FailingAuthMechanism()

        # Try to connect
        connected = await transport.connect()

        # Verify connection failed due to authentication
        assert connected is False
        assert transport.ws is None

    @pytest.mark.asyncio
    async def test_send_message(self, transport, ws_server):
        """Test sending a message via WebSocket."""
        # Connect to the server
        transport.url = ws_server.url
        await transport.connect()

        # Clear received messages to start fresh
        ws_server.received_messages = []

        # Send a test message
        test_message = json.dumps({"type": "test", "data": {"value": "test"}})
        await transport.send(test_message)

        # Verify the message was received by the server
        await asyncio.sleep(0.2)  # Small delay to ensure message is processed

        # Check if the test message is in the received messages
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

    @pytest.mark.asyncio
    async def test_send_message_no_connection(self, transport):
        """Test sending a message when no WebSocket connection exists."""
        # Ensure WebSocket is None
        transport.ws = None

        # Send a test message (should not raise an exception)
        await transport.send("Test message")
        # No assertions needed - the test passes if no exception is raised

    @pytest.mark.asyncio
    async def test_receive_message(self, transport, ws_server, mock_callback):
        """Test receiving a message from the server."""
        event, messages = mock_callback

        # Connect to the server
        transport.url = ws_server.url
        connected = await transport.connect()
        assert connected is True

        # Start listening for messages
        listen_task = asyncio.create_task(transport.start_listening())

        # Wait for the connection to be established
        await asyncio.sleep(0.2)

        # Reset the event since it might have been set by the login response
        event.clear()
        messages.clear()

        # Send a test event from the server
        test_event = {"type": "event", "eventType": "test_event", "data": {"value": "test_data"}}
        await ws_server.send_to_all(json.dumps(test_event))

        # Wait for the message to be received (with timeout)
        try:
            await asyncio.wait_for(event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("Timeout waiting for message to be received")

        # Stop listening
        transport._running = False
        await transport.stop()

        # Cancel the listen task
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

        # Verify the message was received
        assert len(messages) >= 1

        # Check if the test event is in the received messages
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

    @pytest.mark.asyncio
    async def test_connection_closed(self, transport, ws_server, mock_callback):
        """Test handling of connection closure."""
        # Connect to the server
        transport.url = ws_server.url
        await transport.connect()

        # Start listening
        listen_task = asyncio.create_task(transport.start_listening())

        # Wait for a moment to ensure listening has started
        await asyncio.sleep(0.2)

        # Close the server
        await ws_server.stop()

        # Wait for the listening task to complete (it should detect the closed connection)
        try:
            await asyncio.wait_for(listen_task, timeout=2.0)
        except asyncio.TimeoutError:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
            pytest.fail("Timeout waiting for listening task to complete after connection closed")

        # Verify running state is False after connection closed
        assert transport._running is False

    @pytest.mark.asyncio
    async def test_stop(self, transport, ws_server):
        """Test stopping the transport."""
        # Connect to the server
        transport.url = ws_server.url
        await transport.connect()

        # Ensure it's running
        transport._running = True

        # Stop the transport
        await transport.stop()

        # Verify running state is False
        assert transport._running is False
        # WebSocket should be closed (ws attribute might still exist but the connection is closed)

    @pytest.mark.asyncio
    async def test_auth_mechanism_called(self, transport, ws_server, login_payload):
        """Test that the auth_mechanism's authenticate method is called with the correct parameters."""
        # Update the transport URL to point to our test server
        transport.url = ws_server.url

        # Replace the auth mechanism with a mock that tracks calls
        auth_called = False
        received_kwargs = {}

        class MockAuthMechanism(AuthenticationMechanism):
            async def authenticate(self, transport_obj, **kwargs):
                nonlocal auth_called, received_kwargs
                auth_called = True
                received_kwargs = kwargs
                # Still perform the authentication
                auth_message = json.dumps(kwargs)
                await transport_obj.send(auth_message)
                return True

        transport.auth_mechanism = MockAuthMechanism()

        # Connect to the server
        connected = await transport.connect()

        # Verify connection was successful
        assert connected is True

        # Verify auth mechanism was called
        assert auth_called is True

        # Verify kwargs were passed correctly
        assert received_kwargs == login_payload
