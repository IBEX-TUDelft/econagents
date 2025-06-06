import asyncio
import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from econagents.core.events import Message
from econagents.core.manager.base import AgentManager
from econagents.core.transport import WebSocketTransport


class SimpleTestMessage(Message):
    """Simple message class for testing purposes."""


@pytest.fixture
def logger():
    """Provide a logger for tests."""
    return logging.getLogger("test_manager")


@pytest.fixture
def agent_manager(logger):
    """Create a basic agent manager for testing."""
    # Use a non-existent URL since we'll patch the transport
    with patch.object(WebSocketTransport, "__init__", return_value=None):
        manager = AgentManager(url="ws://test-server.com/socket", auth_mechanism_kwargs={"game_id": 123}, logger=logger)
        # Patch the transport to avoid actual connections
        manager.transport = MagicMock()
        manager.transport.send = AsyncMock()
        manager.transport.connect = AsyncMock(return_value=True)
        manager.transport.start_listening = AsyncMock()
        manager.transport.stop = AsyncMock()
        return manager


class TestMessageHandling:
    """Tests for message handling."""

    def test_extract_message_data(self, agent_manager):
        """Test that _extract_message_data correctly parses JSON messages."""
        # Valid message
        valid_json = json.dumps({"type": "event", "eventType": "test-event", "data": {"key": "value"}})
        message = agent_manager._extract_message_data(valid_json)
        assert isinstance(message, Message)
        assert message.message_type == "event"
        assert message.event_type == "test-event"
        assert message.data == {"key": "value"}

        # Invalid JSON
        invalid_json = "not valid json"
        message = agent_manager._extract_message_data(invalid_json)
        assert message is None

    @pytest.mark.asyncio
    async def test_send_message(self, agent_manager):
        """Test that send_message correctly sends data through the transport."""
        test_message = '{"type": "command", "action": "test-action", "data": {"key": "value"}}'

        # Call send_message
        await agent_manager.send_message(test_message)

        # Verify the transport's send method was called with the message
        agent_manager.transport.send.assert_called_once_with(test_message)

    @pytest.mark.asyncio
    async def test_raw_message_received(self, agent_manager, monkeypatch):
        """Test that _raw_message_received processes messages correctly."""
        # Mock the _extract_message_data method
        mock_message = Message(message_type="event", event_type="test-event", data={})
        monkeypatch.setattr(agent_manager, "_extract_message_data", lambda _: mock_message)

        # Mock the on_message method
        mock_on_message = AsyncMock()
        monkeypatch.setattr(agent_manager, "on_message", mock_on_message)

        async def mock_create_task_awaiter(coro, **kwargs):
            await coro
            return MagicMock()

        async def mock_create_task(coro, **kwargs):
            # Immediately schedule and await the coroutine
            asyncio.get_event_loop().create_task(mock_create_task_awaiter(coro))
            return MagicMock()

        monkeypatch.setattr(asyncio, "create_task", mock_create_task)

        # Call _raw_message_received
        agent_manager._raw_message_received("test message")

        # Wait a short time for the task to complete
        await asyncio.sleep(0.1)

        # Check that on_message was called with the message
        mock_on_message.assert_called_once_with(mock_message)

    @pytest.mark.asyncio
    async def test_on_message(self, agent_manager, monkeypatch):
        """Test that on_message correctly routes event messages."""
        # Mock the on_event method
        mock_on_event = AsyncMock()
        monkeypatch.setattr(agent_manager, "on_event", mock_on_event)

        # Test with an event message
        event_message = Message(message_type="event", event_type="test-event", data={"test": "data"})
        await agent_manager.on_message(event_message)

        # Check that on_event was called with the event message
        mock_on_event.assert_called_once_with(event_message)
        mock_on_event.reset_mock()

        # Test with various non-event messages
        non_event_types = ["response", "notification", "command", "error"]

        for msg_type in non_event_types:
            non_event_message = Message(message_type=msg_type, event_type="test-event", data={"test": "data"})
            await agent_manager.on_message(non_event_message)

            # Verify on_event is not called for non-event message types
            mock_on_event.assert_not_called(), f"on_event was called for message type: {msg_type}"


@pytest.mark.asyncio
class TestEventHandling:
    """Tests for event handling and hooks."""

    async def test_register_event_handler(self, agent_manager):
        """Test registering and calling event handlers."""
        # Create a test handler
        test_handler = AsyncMock()

        # Register the handler
        agent_manager.register_event_handler("test-event", test_handler)

        # Check that the handler was registered
        assert "test-event" in agent_manager._event_handlers
        assert test_handler in agent_manager._event_handlers["test-event"]

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})

        # Call on_event
        await agent_manager.on_event(message)

        # Check that the handler was called with the message
        test_handler.assert_called_once_with(message)

    async def test_register_global_event_handler(self, agent_manager):
        """Test registering and calling global event handlers."""
        # Create a test handler
        test_handler = AsyncMock()

        # Register the handler
        agent_manager.register_global_event_handler(test_handler)

        # Check that the handler was registered
        assert test_handler in agent_manager._global_event_handlers

        # Create a test message
        message = Message(message_type="event", event_type="any-event", data={})

        # Call on_event
        await agent_manager.on_event(message)

        # Check that the handler was called with the message
        test_handler.assert_called_once_with(message)

    async def test_register_pre_event_hook(self, agent_manager):
        """Test registering and calling pre-event hooks."""
        # Create test hooks
        test_pre_hook = AsyncMock()
        test_handler = AsyncMock()

        # Register the hooks
        agent_manager.register_pre_event_hook("test-event", test_pre_hook)
        agent_manager.register_event_handler("test-event", test_handler)

        # Check that the hooks were registered
        assert "test-event" in agent_manager._pre_event_hooks
        assert test_pre_hook in agent_manager._pre_event_hooks["test-event"]

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})

        # Call on_event
        await agent_manager.on_event(message)

        # Check that both hooks were called with the message
        test_pre_hook.assert_called_once_with(message)
        test_handler.assert_called_once_with(message)

        # We can't reliably check call order with timestamps in this case
        # So we'll just check both were called

    async def test_register_post_event_hook(self, agent_manager):
        """Test registering and calling post-event hooks."""
        # Create test hooks
        test_handler = AsyncMock()
        test_post_hook = AsyncMock()

        # Register the hooks
        agent_manager.register_event_handler("test-event", test_handler)
        agent_manager.register_post_event_hook("test-event", test_post_hook)

        # Check that the hooks were registered
        assert "test-event" in agent_manager._post_event_hooks
        assert test_post_hook in agent_manager._post_event_hooks["test-event"]

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})

        # Call on_event
        await agent_manager.on_event(message)

        # Check that both hooks were called with the message
        test_handler.assert_called_once_with(message)
        test_post_hook.assert_called_once_with(message)

    async def test_register_global_pre_event_hook(self, agent_manager):
        """Test registering and calling global pre-event hooks."""
        # Create test hooks
        test_global_pre_hook = AsyncMock()
        test_handler = AsyncMock()

        # Register the hooks
        agent_manager.register_global_pre_event_hook(test_global_pre_hook)
        agent_manager.register_event_handler("test-event", test_handler)

        # Check that the hooks were registered
        assert test_global_pre_hook in agent_manager._global_pre_event_hooks

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})

        # Call on_event
        await agent_manager.on_event(message)

        # Check that both hooks were called with the message
        test_global_pre_hook.assert_called_once_with(message)
        test_handler.assert_called_once_with(message)

    async def test_register_global_post_event_hook(self, agent_manager):
        """Test registering and calling global post-event hooks."""
        # Create test hooks
        test_handler = AsyncMock()
        test_global_post_hook = AsyncMock()

        # Register the hooks
        agent_manager.register_event_handler("test-event", test_handler)
        agent_manager.register_global_post_event_hook(test_global_post_hook)

        # Check that the hooks were registered
        assert test_global_post_hook in agent_manager._global_post_event_hooks

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})

        # Call on_event
        await agent_manager.on_event(message)

        # Check that both hooks were called with the message
        test_handler.assert_called_once_with(message)
        test_global_post_hook.assert_called_once_with(message)

    async def test_event_handler_error_handling(self, agent_manager, logger):
        """Test that errors in event handlers are properly caught."""

        # Create a handler that raises an exception
        async def error_handler(message):
            raise Exception("Test error")

        # Register the handler
        agent_manager.register_event_handler("test-event", error_handler)

        # Add a spy to the logger to check that errors are logged
        with patch.object(logger, "error") as mock_error_log:
            # Create a test message
            message = Message(message_type="event", event_type="test-event", data={})

            # Call on_event (should not raise an exception)
            await agent_manager.on_event(message)

            # Verify the error was logged
            mock_error_log.assert_called_once()

            # Check that the error log contains the error message and handler name
            log_args = mock_error_log.call_args[0][0]
            assert "error_handler" in log_args.lower(), "Handler name not in error log"
            assert "test error" in log_args.lower(), "Error message not in log"


@pytest.mark.asyncio
class TestUnregisterHandlers:
    """Tests for unregistering handlers and hooks."""

    async def test_unregister_event_handler(self, agent_manager):
        """Test unregistering specific event handlers."""
        # Create test handlers
        test_handler1 = AsyncMock()
        test_handler2 = AsyncMock()

        # Register the handlers
        agent_manager.register_event_handler("test-event", test_handler1)
        agent_manager.register_event_handler("test-event", test_handler2)

        # Unregister one handler
        agent_manager.unregister_event_handler("test-event", test_handler1)

        # Check that only test_handler2 remains
        assert "test-event" in agent_manager._event_handlers
        assert test_handler1 not in agent_manager._event_handlers["test-event"]
        assert test_handler2 in agent_manager._event_handlers["test-event"]

        # Unregister all handlers for the event
        agent_manager.unregister_event_handler("test-event")

        # Check that the event is removed
        assert "test-event" not in agent_manager._event_handlers

    async def test_unregister_global_event_handler(self, agent_manager):
        """Test unregistering global event handlers."""
        # Create test handlers
        test_handler1 = AsyncMock()
        test_handler2 = AsyncMock()

        # Register the handlers
        agent_manager.register_global_event_handler(test_handler1)
        agent_manager.register_global_event_handler(test_handler2)

        # Unregister one handler
        agent_manager.unregister_global_event_handler(test_handler1)

        # Check that only test_handler2 remains
        assert test_handler1 not in agent_manager._global_event_handlers
        assert test_handler2 in agent_manager._global_event_handlers

        # Unregister all handlers
        agent_manager.unregister_global_event_handler()

        # Check that all global handlers are removed
        assert len(agent_manager._global_event_handlers) == 0

    async def test_unregister_pre_event_hook(self, agent_manager):
        """Test unregistering pre-event hooks."""
        # Create test hooks
        test_hook1 = AsyncMock()
        test_hook2 = AsyncMock()

        # Register the hooks
        agent_manager.register_pre_event_hook("test-event", test_hook1)
        agent_manager.register_pre_event_hook("test-event", test_hook2)

        # Unregister one hook
        agent_manager.unregister_pre_event_hook("test-event", test_hook1)

        # Check that only test_hook2 remains
        assert "test-event" in agent_manager._pre_event_hooks
        assert test_hook1 not in agent_manager._pre_event_hooks["test-event"]
        assert test_hook2 in agent_manager._pre_event_hooks["test-event"]

        # Unregister all hooks for the event
        agent_manager.unregister_pre_event_hook("test-event")

        # Check that the event is removed
        assert "test-event" not in agent_manager._pre_event_hooks

    async def test_unregister_post_event_hook(self, agent_manager):
        """Test unregistering post-event hooks."""
        # Create test hooks
        test_hook1 = AsyncMock()
        test_hook2 = AsyncMock()

        # Register the hooks
        agent_manager.register_post_event_hook("test-event", test_hook1)
        agent_manager.register_post_event_hook("test-event", test_hook2)

        # Unregister one hook
        agent_manager.unregister_post_event_hook("test-event", test_hook1)

        # Check that only test_hook2 remains
        assert "test-event" in agent_manager._post_event_hooks
        assert test_hook1 not in agent_manager._post_event_hooks["test-event"]
        assert test_hook2 in agent_manager._post_event_hooks["test-event"]

        # Unregister all hooks for the event
        agent_manager.unregister_post_event_hook("test-event")

        # Check that the event is removed
        assert "test-event" not in agent_manager._post_event_hooks

    async def test_unregister_global_pre_event_hook(self, agent_manager):
        """Test unregistering global pre-event hooks."""
        # Create test hooks
        test_hook1 = AsyncMock()
        test_hook2 = AsyncMock()

        # Register the hooks
        agent_manager.register_global_pre_event_hook(test_hook1)
        agent_manager.register_global_pre_event_hook(test_hook2)

        # Unregister one hook
        agent_manager.unregister_global_pre_event_hook(test_hook1)

        # Check that only test_hook2 remains
        assert test_hook1 not in agent_manager._global_pre_event_hooks
        assert test_hook2 in agent_manager._global_pre_event_hooks

        # Unregister all hooks
        agent_manager.unregister_global_pre_event_hook()

        # Check that all global hooks are removed
        assert len(agent_manager._global_pre_event_hooks) == 0

    async def test_unregister_global_post_event_hook(self, agent_manager):
        """Test unregistering global post-event hooks."""
        # Create test hooks
        test_hook1 = AsyncMock()
        test_hook2 = AsyncMock()

        # Register the hooks
        agent_manager.register_global_post_event_hook(test_hook1)
        agent_manager.register_global_post_event_hook(test_hook2)

        # Unregister one hook
        agent_manager.unregister_global_post_event_hook(test_hook1)

        # Check that only test_hook2 remains
        assert test_hook1 not in agent_manager._global_post_event_hooks
        assert test_hook2 in agent_manager._global_post_event_hooks

        # Unregister all hooks
        agent_manager.unregister_global_post_event_hook()

        # Check that all global hooks are removed
        assert len(agent_manager._global_post_event_hooks) == 0


@pytest.mark.asyncio
class TestHookExecution:
    """Tests for hook execution order."""

    async def test_execution_order(self, agent_manager):
        """Test that hooks and handlers are executed in the correct order."""
        execution_order = []

        # Create hooks and handlers that append to execution_order
        async def global_pre_hook(message):
            execution_order.append("global_pre")
            return message

        async def specific_pre_hook(message):
            execution_order.append("specific_pre")
            return message

        async def global_handler(message):
            execution_order.append("global_handler")
            return message

        async def specific_handler(message):
            execution_order.append("specific_handler")
            return message

        async def specific_post_hook(message):
            execution_order.append("specific_post")
            return message

        async def global_post_hook(message):
            execution_order.append("global_post")
            return message

        # Register all hooks and handlers with timestamp verification
        agent_manager.register_global_pre_event_hook(global_pre_hook)
        agent_manager.register_pre_event_hook("test-event", specific_pre_hook)
        agent_manager.register_global_event_handler(global_handler)
        agent_manager.register_event_handler("test-event", specific_handler)
        agent_manager.register_post_event_hook("test-event", specific_post_hook)
        agent_manager.register_global_post_event_hook(global_post_hook)

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})

        # Call on_event
        await agent_manager.on_event(message)

        # Check the execution order
        expected_order = [
            "global_pre",
            "specific_pre",
            "global_handler",
            "specific_handler",
            "specific_post",
            "global_post",
        ]
        # Verify both order and completeness
        assert execution_order == expected_order, f"Expected: {expected_order}, Got: {execution_order}"
        assert len(execution_order) == len(expected_order), "Not all hooks/handlers were executed"


class TestSimpleTestMessage:
    """Tests for the SimpleTestMessage class."""

    def test_message_instantiation(self):
        """Test that SimpleTestMessage can be instantiated correctly."""
        message = SimpleTestMessage(message_type="test", event_type="simple-test", data={"key": "value"})

        assert message.message_type == "test"
        assert message.event_type == "simple-test"
        assert message.data == {"key": "value"}

    def test_message_serialization(self):
        """Test that SimpleTestMessage can be serialized to JSON."""
        message = SimpleTestMessage(message_type="test", event_type="simple-test", data={"key": "value"})

        # Use model_dump to serialize
        serialized = message.model_dump()

        assert serialized["message_type"] == "test"
        assert serialized["event_type"] == "simple-test"
        assert serialized["data"] == {"key": "value"}


@pytest.mark.asyncio
class TestConnectionManagement:
    """Tests for connection management functionality."""

    async def test_start_successful_connection(self, agent_manager):
        """Test that start method correctly initiates connection."""
        # Call start
        await agent_manager.start()

        # Verify connection sequence
        agent_manager.transport.connect.assert_called_once()
        agent_manager.transport.start_listening.assert_called_once()
        assert agent_manager.running is True

    async def test_start_failed_connection(self, agent_manager):
        """Test start method behavior when connection fails."""
        # Setup connection to fail
        agent_manager.transport.connect.return_value = False

        # Call start
        await agent_manager.start()

        # Verify correct behavior on failure
        agent_manager.transport.connect.assert_called_once()
        agent_manager.transport.start_listening.assert_not_called()
        assert agent_manager.running is True  # running is still set to True

    async def test_stop(self, agent_manager):
        """Test that stop method correctly terminates connection."""
        # Set initial state
        agent_manager.running = True

        # Call stop
        await agent_manager.stop()

        # Verify connection is terminated
        agent_manager.transport.stop.assert_called_once()
        assert agent_manager.running is False
