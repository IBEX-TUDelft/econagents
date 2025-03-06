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
        manager = AgentManager(url="ws://test-server.com/socket", game_id=123, logger=logger)
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
    async def test_raw_message_received(self, agent_manager, monkeypatch):
        """Test that _raw_message_received processes messages correctly."""
        # Mock the _extract_message_data method
        mock_message = Message(message_type="event", event_type="test-event", data={})
        monkeypatch.setattr(agent_manager, "_extract_message_data", lambda _: mock_message)

        # Mock the on_message method and create_task
        mock_on_message = AsyncMock()
        monkeypatch.setattr(agent_manager, "on_message", mock_on_message)

        # Mock asyncio.create_task to directly await the coroutine
        original_create_task = asyncio.create_task

        def mock_create_task(coro, **kwargs):
            asyncio.get_event_loop().create_task(coro)
            return MagicMock()

        monkeypatch.setattr(asyncio, "create_task", mock_create_task)

        # Call _raw_message_received
        agent_manager._raw_message_received("test message")

        # Wait a short time for the task to be processed
        await asyncio.sleep(0.1)

        # Check that on_message was called with the message
        mock_on_message.assert_called_once_with(mock_message)

        # Restore original create_task
        monkeypatch.setattr(asyncio, "create_task", original_create_task)

    @pytest.mark.asyncio
    async def test_on_message(self, agent_manager, monkeypatch):
        """Test that on_message correctly routes event messages."""
        # Mock the on_event method
        mock_on_event = AsyncMock()
        monkeypatch.setattr(agent_manager, "on_event", mock_on_event)

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})
        await agent_manager.on_message(message)

        # Check that on_event was called with the message
        mock_on_event.assert_called_once_with(message)

        # Create a non-event message
        message = Message(message_type="not-event", event_type="test-event", data={})
        await agent_manager.on_message(message)

        # Check that on_event was not called again
        mock_on_event.assert_called_once()


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

        # Create a test message
        message = Message(message_type="event", event_type="test-event", data={})

        # Call on_event (should not raise an exception)
        await agent_manager.on_event(message)

        # No assertions needed, test passes if no exception is raised


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

        async def specific_pre_hook(message):
            execution_order.append("specific_pre")

        async def global_handler(message):
            execution_order.append("global_handler")

        async def specific_handler(message):
            execution_order.append("specific_handler")

        async def specific_post_hook(message):
            execution_order.append("specific_post")

        async def global_post_hook(message):
            execution_order.append("global_post")

        # Register all hooks and handlers
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
        assert execution_order == expected_order
