import json
from typing import ClassVar

import pytest

from econagents.core.agent_role import AgentRole
from econagents.core.state.game import GameStateProtocol


class TestAgentInitialization:
    """Tests for Agent initialization."""

    def test_initialization(self, mock_agent):
        """Test that the agent initializes correctly."""
        assert mock_agent.game_id == 123
        assert mock_agent.name == "test_agent"
        assert mock_agent.role == 1
        assert mock_agent.task_phases == []
        assert mock_agent.task_phases_excluded == []

    def test_initialization_with_both_phase_lists(self, logger, mock_llm, prompts_path):
        """Test that initializing with both task_phases and task_phases_excluded raises an error."""

        class ConflictingAgent(AgentRole):
            role = 1
            name = "test_agent"
            task_phases = [1, 2]
            task_phases_excluded = [3, 4]

        with pytest.raises(ValueError) as exc_info:
            ConflictingAgent(logger=logger, llm=mock_llm, game_id=123, prompts_path=prompts_path)

        assert "Only one of task_phases or task_phases_excluded should be specified" in str(exc_info.value)


class TestPromptHandling:
    """Tests for prompt handling."""

    def test_render_prompt(self, mock_agent, game_state):
        """Test rendering a prompt template."""
        result = mock_agent.render_prompt(context=game_state.model_dump(), prompt_type="system", phase=0)
        assert result == "System prompt for 0"

    def test_render_prompt_phase_specific(self, mock_agent, phase1_game_state):
        """Test rendering a phase-specific prompt template."""
        result = mock_agent.render_prompt(context=phase1_game_state.model_dump(), prompt_type="system", phase=1)
        assert result == "Phase 1 system prompt"

    def test_render_prompt_fallback_to_agent_general(self, mock_agent, game_state, monkeypatch):
        """Test fallback to agent-specific general prompt when phase-specific prompts don't exist."""

        # Try to render a prompt - should fall back to agent-specific general
        result = mock_agent.render_prompt(
            context=game_state.model_dump(),
            prompt_type="system",
            phase=2,  # No phase-specific prompt for phase 2
        )
        assert result == "System prompt for 0"

    def test_render_prompt_fallback_to_general(self, mock_agent, game_state, monkeypatch):
        """Test fallback to all-role general prompt when no agent-specific prompts exist."""
        # Mock the _resolve_prompt_file method to simulate missing agent-specific prompts
        original_resolve = mock_agent._resolve_prompt_file

        def mock_resolve(prompt_type, phase, role):
            # Return None for all agent-specific prompts to force fallback to all-role general
            if role == mock_agent.name:
                return None
            return original_resolve(prompt_type, phase, role)

        monkeypatch.setattr(mock_agent, "_resolve_prompt_file", mock_resolve)

        # Try to render a prompt - should fall back to all-role general
        result = mock_agent.render_prompt(
            context=game_state.model_dump(),
            prompt_type="system",
            phase=2,  # No phase-specific prompt for phase 2
        )
        assert result == "General system prompt for 0"

    def test_render_prompt_file_not_found(self, mock_agent, game_state, monkeypatch):
        """Test that FileNotFoundError is raised when no prompt files are found."""
        # Override _resolve_prompt_file to always return None
        monkeypatch.setattr(mock_agent, "_resolve_prompt_file", lambda *args, **kwargs: None)

        with pytest.raises(FileNotFoundError):
            mock_agent.render_prompt(context=game_state.model_dump(), prompt_type="system", phase=0)

    def test_get_phase_system_prompt(self, mock_agent, phase1_game_state):
        """Test getting system prompt for a phase."""
        result = mock_agent.get_phase_system_prompt(phase1_game_state)
        assert result == "Phase 1 system prompt"

    def test_get_phase_user_prompt(self, mock_agent, phase1_game_state):
        """Test getting user prompt for a phase."""
        result = mock_agent.get_phase_user_prompt(phase1_game_state)
        assert result == "Phase 1 user prompt"

    def test_custom_system_prompt_handler(self, mock_agent, game_state):
        """Test registering and using a custom system prompt handler."""

        def custom_handler(state):
            return f"Custom system prompt for phase {state.meta.phase}"

        mock_agent.register_system_prompt_handler(0, custom_handler)
        result = mock_agent.get_phase_system_prompt(game_state)

        assert result == "Custom system prompt for phase 0"

    def test_custom_user_prompt_handler(self, mock_agent, game_state):
        """Test registering and using a custom user prompt handler."""

        def custom_handler(state):
            return f"Custom user prompt for phase {state.meta.phase}"

        mock_agent.register_user_prompt_handler(0, custom_handler)
        result = mock_agent.get_phase_user_prompt(game_state)

        assert result == "Custom user prompt for phase 0"


@pytest.mark.asyncio
class TestPhaseHandling:
    """Tests for phase handling."""

    async def test_handle_phase_default(self, mock_agent, game_state, mock_llm):
        """Test default phase handling with LLM."""
        result = await mock_agent.handle_phase(0, game_state)

        assert result == {"message": "test_response"}
        mock_llm.build_messages.assert_called_once()
        mock_llm.get_response.assert_called_once()

    async def test_handle_phase_custom_handler(self, mock_agent, game_state):
        """Test custom phase handler."""

        async def custom_handler(phase, state):
            return {"phase": phase, "custom": True}

        mock_agent.register_phase_handler(0, custom_handler)
        result = await mock_agent.handle_phase(0, game_state)

        assert result == {"phase": 0, "custom": True}

    async def test_skip_excluded_phase(self, mock_agent, game_state):
        """Test skipping a phase that's in the excluded list."""
        # Modify task_phases_excluded for the test
        mock_agent.task_phases_excluded = [0]

        result = await mock_agent.handle_phase(0, game_state)

        assert result is None

    async def test_skip_non_task_phase(self, mock_agent, game_state):
        """Test skipping a phase that's not in the task phases list."""
        # Modify task_phases for the test
        mock_agent.task_phases = [1, 2]

        result = await mock_agent.handle_phase(0, game_state)

        assert result is None

    async def test_include_task_phase(self, mock_agent, phase1_game_state):
        """Test handling a phase that's in the task phases list."""
        # Modify task_phases for the test
        mock_agent.task_phases = [1, 2]

        result = await mock_agent.handle_phase(1, phase1_game_state)

        assert result is not None
        assert result == {"message": "test_response"}


@pytest.mark.asyncio
class TestResponseParsing:
    """Tests for response parsing."""

    def test_parse_phase_llm_response_default(self, mock_agent, game_state):
        """Test default JSON response parsing."""
        response = json.dumps({"key": "value"})
        result = mock_agent.parse_phase_llm_response(response, game_state)

        assert result == {"key": "value"}

    def test_parse_phase_llm_response_invalid_json(self, mock_agent, game_state):
        """Test handling invalid JSON in response parsing."""
        response = "not valid json"
        result = mock_agent.parse_phase_llm_response(response, game_state)

        assert "error" in result
        assert result["raw_response"] == "not valid json"

    def test_custom_response_parser(self, mock_agent, game_state):
        """Test registering and using a custom response parser."""

        def custom_parser(response, state):
            return {"parsed": response, "phase": state.meta.phase}

        mock_agent.register_response_parser(0, custom_parser)
        result = mock_agent.parse_phase_llm_response("test response", game_state)

        assert result == {"parsed": "test response", "phase": 0}


@pytest.mark.asyncio
class TestPhaseSpecificMethods:
    """Tests for phase-specific methods defined in subclasses."""

    def test_auto_register_methods(self, logger, mock_llm, prompts_path):
        """Test that phase-specific methods are automatically registered."""

        class SpecializedAgent(AgentRole[GameStateProtocol]):
            role: ClassVar[int] = 1
            name: ClassVar[str] = "specialized_agent"

            def get_phase_1_system_prompt(self, state):
                return "Special system prompt for phase 1"

            def get_phase_1_user_prompt(self, state):
                return "Special user prompt for phase 1"

            def parse_phase_1_llm_response(self, response, state):
                return {"special_parsed": response}

            async def handle_phase_1(self, phase, state):
                return {"special_handled": True}

        agent = SpecializedAgent(logger=logger, llm=mock_llm, game_id=123, prompts_path=prompts_path)

        # Check that methods were registered
        assert 1 in agent._system_prompt_handlers
        assert 1 in agent._user_prompt_handlers
        assert 1 in agent._response_parsers
        assert 1 in agent._phase_handlers

    async def test_llm_error_handling(self, mock_agent, game_state, mocker):
        """Test error handling when LLM raises an exception."""

        # Make the LLM raise an exception
        async def mock_error(*args, **kwargs):
            raise Exception("LLM error")

        mocker.patch.object(mock_agent.llm, "get_response", side_effect=mock_error)

        result = await mock_agent.handle_phase_with_llm(0, game_state)

        assert "error" in result
        assert result["error"] == "LLM error"
        assert result["phase"] == 0
