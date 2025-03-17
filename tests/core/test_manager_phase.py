import asyncio
import json
import logging
import pytest
import random
from unittest.mock import AsyncMock, MagicMock, patch

from econagents.core.agent_role import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import PhaseManager, TurnBasedPhaseManager, HybridPhaseManager
from econagents.core.state.game import GameState
from econagents.core.transport import WebSocketTransport, SimpleLoginPayloadAuth


class SimpleGameState(GameState):
    """Simple game state for testing."""


class SimplePhaseManager(PhaseManager):
    """Concrete implementation of PhaseManager for testing."""

    async def execute_phase_action(self, phase: int):
        """Simple implementation of abstract method."""
        return {"action": f"phase-{phase}-action"}


@pytest.fixture
def logger():
    """Provide a logger for tests."""
    return logging.getLogger("test_phase_manager")


@pytest.fixture
def game_state():
    """Provide a simple game state for testing."""
    state = SimpleGameState()
    state.meta.phase = 0
    state.meta.game_id = 123
    return state


@pytest.fixture
def mock_agent():
    """Provide a mock agent for testing."""
    agent = MagicMock(spec=AgentRole)
    agent.handle_phase = AsyncMock(return_value={"message": "agent_response"})
    agent.name = "MockAgent"
    return agent


@pytest.fixture
def phase_manager(logger, game_state, mock_agent):
    """Create a simple phase manager for testing."""
    with patch.object(WebSocketTransport, "__init__", return_value=None):
        manager = SimplePhaseManager(
            url="ws://test-server.com/socket",
            logger=logger,
            state=game_state,
            agent_role=mock_agent,
            phase_transition_event="phase-transition",
            phase_identifier_key="phase",
            continuous_phases={1, 3},
            min_action_delay=1,
            max_action_delay=2,
        )
        # Patch the transport to avoid actual connections
        manager.transport = MagicMock()
        manager.transport.send = AsyncMock()
        manager.transport.connect = AsyncMock(return_value=True)
        manager.transport.start_listening = AsyncMock()
        manager.transport.stop = AsyncMock()

        # Patch random.randint to return a predictable value for testing
        with patch.object(random, "randint", return_value=1):
            yield manager


@pytest.fixture
def discrete_phase_manager(logger, game_state, mock_agent):
    """Create a discrete phase manager for testing."""
    with patch.object(WebSocketTransport, "__init__", return_value=None):
        manager = TurnBasedPhaseManager(
            url="ws://test-server.com/socket", logger=logger, state=game_state, agent_role=mock_agent
        )
        # Patch the transport to avoid actual connections
        manager.transport = MagicMock()
        manager.transport.send = AsyncMock()
        manager.transport.connect = AsyncMock(return_value=True)
        manager.transport.start_listening = AsyncMock()
        manager.transport.stop = AsyncMock()
        yield manager


@pytest.fixture
def hybrid_phase_manager(logger, game_state, mock_agent):
    """Create a hybrid phase manager for testing."""
    with patch.object(WebSocketTransport, "__init__", return_value=None):
        manager = HybridPhaseManager(
            url="ws://test-server.com/socket",
            logger=logger,
            state=game_state,
            agent_role=mock_agent,
            continuous_phases={1, 3},
        )
        # Patch the transport to avoid actual connections
        manager.transport = MagicMock()
        manager.transport.send = AsyncMock()
        manager.transport.connect = AsyncMock(return_value=True)
        manager.transport.start_listening = AsyncMock()
        manager.transport.stop = AsyncMock()

        # Patch random.randint to return a predictable value for testing
        with patch.object(random, "randint", return_value=1):
            yield manager


@pytest.mark.asyncio
class TestPhaseTransition:
    """Tests for phase transitions."""

    async def test_on_phase_transition_event(self, phase_manager, monkeypatch):
        """Test that _on_phase_transition_event calls handle_phase_transition."""
        # Mock handle_phase_transition
        mock_handle = AsyncMock()
        monkeypatch.setattr(phase_manager, "handle_phase_transition", mock_handle)

        # Create a test message with phase data
        message = Message(message_type="event", event_type="phase-transition", data={"phase": 1})

        # Call _on_phase_transition_event
        await phase_manager._on_phase_transition_event(message)

        # Check that handle_phase_transition was called with the phase
        mock_handle.assert_called_once_with(1)

    async def test_handle_phase_transition_to_continuous(self, phase_manager, monkeypatch):
        """Test transitioning to a continuous-time phase."""
        # Mock methods
        mock_on_phase_end = AsyncMock()
        mock_on_phase_start = AsyncMock()
        mock_execute_phase_action = AsyncMock()
        monkeypatch.setattr(phase_manager, "on_phase_end", mock_on_phase_end)
        monkeypatch.setattr(phase_manager, "on_phase_start", mock_on_phase_start)
        monkeypatch.setattr(phase_manager, "execute_phase_action", mock_execute_phase_action)

        # Set current phase
        phase_manager.current_phase = 0

        # Call handle_phase_transition with a continuous-time phase
        await phase_manager.handle_phase_transition(1)  # 1 is in continuous_phases

        # Check that methods were called
        mock_on_phase_end.assert_called_once_with(0)
        mock_on_phase_start.assert_called_once_with(1)
        mock_execute_phase_action.assert_called_once_with(1)

        # Check that state was updated
        assert phase_manager.current_phase == 1
        assert phase_manager.in_continuous_phase is True
        assert phase_manager._continuous_task is not None

        # Clean up the continuous task to avoid warnings
        if phase_manager._continuous_task and not phase_manager._continuous_task.done():
            phase_manager._continuous_task.cancel()
            # Add a small sleep to allow task cancellation to process
            await asyncio.sleep(0.1)

    async def test_handle_phase_transition_to_discrete(self, phase_manager, monkeypatch):
        """Test transitioning to a discrete phase."""
        # Mock methods
        mock_on_phase_end = AsyncMock()
        mock_on_phase_start = AsyncMock()
        mock_execute_phase_action = AsyncMock()
        monkeypatch.setattr(phase_manager, "on_phase_end", mock_on_phase_end)
        monkeypatch.setattr(phase_manager, "on_phase_start", mock_on_phase_start)
        monkeypatch.setattr(phase_manager, "execute_phase_action", mock_execute_phase_action)

        # Set current phase (a continuous-time phase)
        phase_manager.current_phase = 1
        phase_manager.in_continuous_phase = True
        phase_manager._continuous_task = asyncio.create_task(asyncio.sleep(0))  # Dummy task

        # Call handle_phase_transition with a discrete phase
        await phase_manager.handle_phase_transition(2)  # 2 is not in continuous_phases

        # Check that methods were called
        mock_on_phase_end.assert_called_once_with(1)
        mock_on_phase_start.assert_called_once_with(2)
        mock_execute_phase_action.assert_called_once_with(2)

        # Check that state was updated
        assert phase_manager.current_phase == 2
        assert phase_manager.in_continuous_phase is False

    async def test_handle_phase_transition_to_none(self, phase_manager, monkeypatch):
        """Test transitioning to None phase."""
        # Mock methods
        mock_on_phase_end = AsyncMock()
        mock_on_phase_start = AsyncMock()
        mock_execute_phase_action = AsyncMock()
        monkeypatch.setattr(phase_manager, "on_phase_end", mock_on_phase_end)
        monkeypatch.setattr(phase_manager, "on_phase_start", mock_on_phase_start)
        monkeypatch.setattr(phase_manager, "execute_phase_action", mock_execute_phase_action)

        # Set current phase
        phase_manager.current_phase = 0

        # Call handle_phase_transition with None
        await phase_manager.handle_phase_transition(None)

        # Check that on_phase_end was called
        mock_on_phase_end.assert_called_once_with(0)

        # Check that on_phase_start and execute_phase_action were not called
        mock_on_phase_start.assert_not_called()
        mock_execute_phase_action.assert_not_called()

        # Check that state was updated
        assert phase_manager.current_phase is None

    async def test_continuous_phase_loop(self, phase_manager, monkeypatch):
        """Test the continuous-time phase loop."""
        # Mock execute_phase_action to track calls
        mock_execute = AsyncMock()
        monkeypatch.setattr(phase_manager, "execute_phase_action", mock_execute)

        # Set up for a continuous-time phase
        phase_manager.current_phase = 1
        phase_manager.in_continuous_phase = True

        # Start continuous-time phase loop
        task = asyncio.create_task(phase_manager._continuous_phase_loop(1))

        try:
            # Let it run for a bit (should run at least twice)
            await asyncio.sleep(2.5)  # Wait for 2.5 seconds (more than 2 iterations with 1-second delay)

            # Cancel the task
            phase_manager.in_continuous_phase = False
            task.cancel()
            await asyncio.sleep(0.1)  # Allow cancellation to process

            # Check that execute_phase_action was called at least twice
            assert mock_execute.call_count >= 2

            # Check that it was called with the correct phase
            for call in mock_execute.call_args_list:
                assert call[0][0] == 1
        finally:
            # Ensure task cleanup
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=0.5)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

    async def test_stop_with_continuous_phase(self, phase_manager):
        """Test stopping a manager with a continuous-time phase."""
        # Set up for a continuous-time phase
        phase_manager.current_phase = 1
        phase_manager.in_continuous_phase = True
        continuous_task = asyncio.create_task(asyncio.sleep(10))  # Long-running task
        phase_manager._continuous_task = continuous_task

        # Stop the manager
        await phase_manager.stop()

        # Check that continuous-time phase was stopped
        assert phase_manager.in_continuous_phase is False
        assert phase_manager._continuous_task is None

        # Check that transport.stop was called
        phase_manager.transport.stop.assert_called_once()

        # Ensure task cleanup
        if not continuous_task.done():
            continuous_task.cancel()
            try:
                await asyncio.wait_for(continuous_task, timeout=0.1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass


class TestDiscretePhaseManager:
    """Tests for DiscretePhaseManager."""

    @pytest.mark.asyncio
    async def test_execute_phase_action(self, discrete_phase_manager, mock_agent):
        """Test execute_phase_action method."""
        # Call execute_phase_action
        await discrete_phase_manager.execute_phase_action(1)

        # Check that agent.handle_phase was called with correct parameters
        mock_agent.handle_phase.assert_called_once_with(
            1, discrete_phase_manager.state, discrete_phase_manager.prompts_dir
        )

        # Check that send_message was called with the agent response
        expected_payload = json.dumps({"message": "agent_response"})
        discrete_phase_manager.transport.send.assert_called_once_with(expected_payload)

    @pytest.mark.asyncio
    async def test_execute_phase_action_with_custom_handler(self, discrete_phase_manager):
        """Test execute_phase_action with a custom phase handler."""
        # Create a custom phase handler
        custom_handler = AsyncMock(return_value={"custom": True})

        # Register the handler
        discrete_phase_manager.register_phase_handler(1, custom_handler)

        # Call execute_phase_action
        await discrete_phase_manager.execute_phase_action(1)

        # Check that custom_handler was called
        custom_handler.assert_called_once_with(1, discrete_phase_manager.state)

        # Check that send_message was called with the custom response
        expected_payload = json.dumps({"custom": True})
        discrete_phase_manager.transport.send.assert_called_once_with(expected_payload)

    @pytest.mark.asyncio
    async def test_execute_phase_action_no_agent(self, discrete_phase_manager):
        """Test execute_phase_action without an agent."""
        # Set agent to None
        discrete_phase_manager._agent_role = None  # Fixed attribute name from _agent to _agent_role

        # Call execute_phase_action
        await discrete_phase_manager.execute_phase_action(1)

        # Check that send_message was not called
        discrete_phase_manager.transport.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_phase_handler(self, discrete_phase_manager):
        """Test registering a phase handler."""
        # Create a handler
        test_handler = AsyncMock()

        # Register the handler
        discrete_phase_manager.register_phase_handler(1, test_handler)

        # Check that the handler was registered
        assert 1 in discrete_phase_manager._phase_handlers
        assert discrete_phase_manager._phase_handlers[1] is test_handler


class TestHybridPhaseManager:
    """Tests for HybridPhaseManager."""

    @pytest.mark.asyncio
    async def test_execute_phase_action_continuous(self, hybrid_phase_manager, mock_agent):
        """Test execute_phase_action for a continuous-time phase."""
        # Set up for a continuous-time phase
        hybrid_phase_manager.current_phase = 1
        hybrid_phase_manager.in_continuous_phase = True

        # Call execute_phase_action
        await hybrid_phase_manager.execute_phase_action(1)

        # Check that agent.handle_phase was called with correct parameters
        mock_agent.handle_phase.assert_called_once_with(1, hybrid_phase_manager.state, hybrid_phase_manager.prompts_dir)

        # Check that send_message was called with the agent response
        expected_payload = json.dumps({"message": "agent_response"})
        hybrid_phase_manager.transport.send.assert_called_once_with(expected_payload)

    @pytest.mark.asyncio
    async def test_execute_phase_action_discrete(self, hybrid_phase_manager, mock_agent):
        """Test execute_phase_action for a discrete phase."""
        # Call execute_phase_action for a discrete phase
        await hybrid_phase_manager.execute_phase_action(2)

        # Check that agent.handle_phase was called with correct parameters
        mock_agent.handle_phase.assert_called_once_with(2, hybrid_phase_manager.state, hybrid_phase_manager.prompts_dir)

        # Check that send_message was called with the agent response
        expected_payload = json.dumps({"message": "agent_response"})
        hybrid_phase_manager.transport.send.assert_called_once_with(expected_payload)

    @pytest.mark.asyncio
    async def test_execute_phase_action_with_custom_handler(self, hybrid_phase_manager):
        """Test execute_phase_action with a custom phase handler."""
        # Create a custom phase handler
        custom_handler = AsyncMock(return_value={"custom": True})

        # Register the handler
        hybrid_phase_manager.register_phase_handler(1, custom_handler)

        # Call execute_phase_action
        await hybrid_phase_manager.execute_phase_action(1)

        # Check that custom_handler was called
        custom_handler.assert_called_once_with(1, hybrid_phase_manager.state)

        # Check that send_message was called with the custom response
        expected_payload = json.dumps({"custom": True})
        hybrid_phase_manager.transport.send.assert_called_once_with(expected_payload)


@pytest.mark.asyncio
class TestPhaseLifecycleHooks:
    """Tests for phase lifecycle hooks."""

    async def test_on_phase_start(self, phase_manager, monkeypatch):
        """Test the on_phase_start hook."""
        # Create a mock for on_phase_start
        mock_hook = AsyncMock()
        monkeypatch.setattr(phase_manager, "on_phase_start", mock_hook)

        # Call handle_phase_transition (which should call on_phase_start)
        await phase_manager.handle_phase_transition(1)

        # Check that on_phase_start was called
        mock_hook.assert_called_once_with(1)

        # Clean up the continuous task to avoid warnings
        if phase_manager._continuous_task and not phase_manager._continuous_task.done():
            phase_manager._continuous_task.cancel()
            await asyncio.sleep(0.1)  # Allow cancellation to process

    async def test_on_phase_end(self, phase_manager, monkeypatch):
        """Test the on_phase_end hook."""
        # Create a mock for on_phase_end
        mock_hook = AsyncMock()
        monkeypatch.setattr(phase_manager, "on_phase_end", mock_hook)

        # Set current phase
        phase_manager.current_phase = 1

        # Call handle_phase_transition (which should call on_phase_end)
        await phase_manager.handle_phase_transition(2)

        # Check that on_phase_end was called
        mock_hook.assert_called_once_with(1)

        # Clean up any continuous task that might have been created
        if phase_manager._continuous_task and not phase_manager._continuous_task.done():
            phase_manager._continuous_task.cancel()
            await asyncio.sleep(0.1)  # Allow cancellation to process
