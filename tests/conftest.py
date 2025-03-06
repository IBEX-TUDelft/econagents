import json
import logging
import pytest
from pathlib import Path
from typing import ClassVar, Dict, Optional

import nest_asyncio
from pytest_mock import MockFixture

from econagents.core.agent_role import AgentRole
from econagents.core.state.game import GameState, GameStateProtocol
from econagents.llm.openai import ChatOpenAI

# Apply nest_asyncio to allow running asyncio code in pytest
nest_asyncio.apply()


class SimpleGameState(GameState):
    """Simple game state for testing."""


class MockAgent(AgentRole[GameStateProtocol]):
    """Mock Agent implementation for testing."""

    role: ClassVar[int] = 1
    name: ClassVar[str] = "test_agent"
    task_phases: ClassVar[list[int]] = []
    task_phases_excluded: ClassVar[list[int]] = []

    async def get_response_for_testing(self, response_text: str):
        """Helper method for testing custom responses."""
        return response_text


@pytest.fixture
def logger():
    """Provide a logger for tests."""
    return logging.getLogger("test_logger")


@pytest.fixture
def mock_llm(mocker: MockFixture):
    """Provide a mocked LLM client."""
    mock = mocker.MagicMock(spec=ChatOpenAI)

    # Setup for async get_response method
    async def mock_get_response(*args, **kwargs):
        return json.dumps({"message": "test_response"})

    mock.get_response.side_effect = mock_get_response
    mock.build_messages.return_value = [
        {"role": "system", "content": "system_prompt"},
        {"role": "user", "content": "user_prompt"},
    ]
    return mock


@pytest.fixture
def prompts_path(tmp_path):
    """Create a temporary directory with test prompt files."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    # Create some test prompt templates
    system_prompt = prompts_dir / "test_agent_system.jinja2"
    system_prompt.write_text("System prompt for {{ meta.phase }}")

    user_prompt = prompts_dir / "test_agent_user.jinja2"
    user_prompt.write_text("User prompt for {{ meta.phase }}")

    # Phase-specific prompts
    phase_system_prompt = prompts_dir / "test_agent_system_phase_1.jinja2"
    phase_system_prompt.write_text("Phase 1 system prompt")

    phase_user_prompt = prompts_dir / "test_agent_user_phase_1.jinja2"
    phase_user_prompt.write_text("Phase 1 user prompt")

    # General prompts for all roles
    all_system_prompt = prompts_dir / "all_system.jinja2"
    all_system_prompt.write_text("General system prompt for {{ meta.phase }}")

    return prompts_dir


@pytest.fixture
def mock_agent(logger, mock_llm, prompts_path):
    """Provide a mock agent instance."""
    return MockAgent(logger=logger, llm=mock_llm, game_id=123, prompts_path=prompts_path)


@pytest.fixture
def game_state():
    """Provide a simple game state for testing."""
    state = SimpleGameState()
    state.meta.phase = 0
    state.meta.game_id = 123
    return state


@pytest.fixture
def phase1_game_state():
    """Provide a game state for phase 1."""
    state = SimpleGameState()
    state.meta.phase = 1
    state.meta.game_id = 123
    return state
