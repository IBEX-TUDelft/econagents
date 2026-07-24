import json
from typing import ClassVar, Literal

import pytest
from pydantic import BaseModel

from econagents.domain.role import Role
from econagents.domain.state.game import GameStateProtocol
from tests.conftest import MockLLM


class _SampleSchema(BaseModel):
    gameId: int
    action: Literal["go", "stop"]


class TestRoleInitialization:
    """Tests for Role initialization."""

    def test_initialization(self, mock_role):
        """Test that the role initializes correctly."""
        assert mock_role.name == "test_role"
        assert mock_role.role == 1
        assert mock_role.task_phases == []
        assert mock_role.task_phases_excluded == []

    def test_initialization_with_both_phase_lists(self, logger, prompts_path):
        """Test that initializing with both task_phases and task_phases_excluded raises an error."""

        class ConflictingRole(Role):
            role = 1
            name = "test_role"
            task_phases = [1, 2]
            task_phases_excluded = [3, 4]

        with pytest.raises(ValueError) as exc_info:
            ConflictingRole(logger=logger)

        assert "Only one of task_phases or task_phases_excluded should be specified" in str(exc_info.value)


class TestPromptHandling:
    """Tests for prompt handling."""

    def test_render_prompt(self, mock_role, game_state, prompts_path):
        """Test rendering a prompt template."""
        result = mock_role.render_prompt(
            context=game_state.model_dump(), prompt_type="system", phase=0, prompts_path=prompts_path
        )
        assert result == "System prompt for 0"

    def test_render_prompt_phase_specific(self, mock_role, phase1_game_state, prompts_path):
        """Test rendering a phase-specific prompt template."""
        result = mock_role.render_prompt(
            context=phase1_game_state.model_dump(), prompt_type="system", phase=1, prompts_path=prompts_path
        )
        assert result == "Phase 1 system prompt"

    def test_render_prompt_fallback_to_role_general(self, mock_role, game_state, monkeypatch, prompts_path):
        """Test fallback to role-specific general prompt when phase-specific prompts do not exist."""

        # Update the phase in the game state to match the expected phase
        game_state.meta.phase = 2

        # Try to render a prompt - should fall back to role-specific general
        result = mock_role.render_prompt(
            context=game_state.model_dump(),
            prompt_type="system",
            phase=2,  # No phase-specific prompt for phase 2
            prompts_path=prompts_path,
        )
        assert result == "System prompt for 2"

    def test_render_prompt_fallback_to_general(self, mock_role, game_state, monkeypatch, prompts_path):
        """Test fallback to all-role general prompt when no role-specific prompts exist."""
        # Mock the _resolve_prompt_file method to simulate missing role-specific prompts
        original_resolve = mock_role._resolve_prompt_file

        # Update the phase in the game state to match the expected phase
        game_state.meta.phase = 2

        def mock_resolve(prompt_type, phase, role, prompts_path):
            # Return None for all role-specific prompts to force fallback to all-role general
            if role == mock_role.name:
                return None
            return original_resolve(prompt_type, phase, role, prompts_path)

        monkeypatch.setattr(mock_role, "_resolve_prompt_file", mock_resolve)

        # Try to render a prompt - should fall back to all-role general
        result = mock_role.render_prompt(
            context=game_state.model_dump(),
            prompt_type="system",
            phase=2,  # No phase-specific prompt for phase 2
            prompts_path=prompts_path,
        )
        assert result == "General system prompt for 2"

    def test_render_prompt_file_not_found(self, mock_role, game_state, monkeypatch, prompts_path):
        """Test that FileNotFoundError is raised when no prompt files are found."""
        # Override _resolve_prompt_file to always return None
        monkeypatch.setattr(mock_role, "_resolve_prompt_file", lambda *args, **kwargs: None)

        with pytest.raises(FileNotFoundError):
            mock_role.render_prompt(
                context=game_state.model_dump(), prompt_type="system", phase=0, prompts_path=prompts_path
            )

    def test_get_phase_system_prompt(self, mock_role, phase1_game_state, prompts_path):
        """Test getting system prompt for a phase."""
        result = mock_role.get_phase_system_prompt(phase1_game_state, prompts_path=prompts_path)
        assert result == "Phase 1 system prompt"

    def test_get_phase_user_prompt(self, mock_role, phase1_game_state, prompts_path):
        """Test getting user prompt for a phase."""
        result = mock_role.get_phase_user_prompt(phase1_game_state, prompts_path=prompts_path)
        assert result == "Phase 1 user prompt"

    def test_custom_system_prompt_handler(self, mock_role, game_state, prompts_path):
        """Test registering and using a custom system prompt handler."""

        def custom_handler(state):
            return f"Custom system prompt for phase {state.meta.phase}"

        mock_role.register_system_prompt_handler(0, custom_handler)
        result = mock_role.get_phase_system_prompt(game_state, prompts_path=prompts_path)

        assert result == "Custom system prompt for phase 0"

    def test_custom_user_prompt_handler(self, mock_role, game_state, prompts_path):
        """Test registering and using a custom user prompt handler."""

        def custom_handler(state):
            return f"Custom user prompt for phase {state.meta.phase}"

        mock_role.register_user_prompt_handler(0, custom_handler)
        result = mock_role.get_phase_user_prompt(game_state, prompts_path=prompts_path)

        assert result == "Custom user prompt for phase 0"

    def test_render_prompt_with_partial(self, mock_role, game_state, prompts_path):
        """Test rendering a prompt that includes a partial template."""
        # Set phase to 2 to match the prompt file name
        game_state.meta.phase = 2
        result = mock_role.render_prompt(
            context=game_state.model_dump(), prompt_type="user", phase=2, prompts_path=prompts_path
        )
        expected_output = "Phase 2 instructions.\nShared info: game ID is 123\nMore instructions."
        assert result == expected_output


@pytest.mark.asyncio
class TestPhaseHandling:
    """Tests for phase handling."""

    async def test_handle_phase_default(self, mock_role, game_state, prompts_path, mocker):
        """Test default phase handling with LLM."""
        # Mock the LLM methods to track calls
        mocker.spy(mock_role.llm, "build_messages")
        mocker.spy(mock_role.llm, "get_response")

        result = await mock_role.handle_phase(0, game_state, prompts_path)

        assert result == {"message": "test_response"}
        mock_role.llm.build_messages.assert_called_once()
        mock_role.llm.get_response.assert_called_once()

    async def test_handle_phase_passes_logger_to_llm(self, mock_role, game_state, prompts_path, mocker):
        """The role's logger is forwarded so the adapter can log the full LLM response."""
        spy = mocker.spy(mock_role.llm, "get_response")

        await mock_role.handle_phase(0, game_state, prompts_path)

        assert spy.call_args.kwargs["logger"] is mock_role.logger

    async def test_handle_phase_custom_handler(self, mock_role, game_state, prompts_path):
        """Test custom phase handler."""

        async def custom_handler(phase, state):
            return {"phase": phase, "custom": True}

        mock_role.register_phase_handler(0, custom_handler)
        result = await mock_role.handle_phase(0, game_state, prompts_path)

        assert result == {"phase": 0, "custom": True}

    async def test_skip_excluded_phase(self, mock_role, game_state, prompts_path):
        """Test skipping a phase that's in the excluded list."""
        # Modify task_phases_excluded for the test
        mock_role.task_phases_excluded = [0]

        result = await mock_role.handle_phase(0, game_state, prompts_path)

        assert result is None

    async def test_skip_non_task_phase(self, mock_role, game_state, prompts_path):
        """Test skipping a phase that's not in the task phases list."""
        # Modify task_phases for the test
        mock_role.task_phases = [1, 2]

        result = await mock_role.handle_phase(0, game_state, prompts_path)

        assert result is None

    async def test_include_task_phase(self, mock_role, phase1_game_state, prompts_path, mocker):
        """Test handling a phase that's in the task phases list."""
        # Modify task_phases for the test
        mock_role.task_phases = [1, 2]

        # Mock the LLM methods to track calls
        mocker.spy(mock_role.llm, "build_messages")
        mocker.spy(mock_role.llm, "get_response")

        result = await mock_role.handle_phase(1, phase1_game_state, prompts_path)

        assert result == {"message": "test_response"}
        mock_role.llm.build_messages.assert_called_once()
        mock_role.llm.get_response.assert_called_once()


class TestResponseParsing:
    """Tests for response parsing."""

    def test_parse_phase_llm_response_default(self, mock_role, game_state):
        """Test default response parsing."""
        response = json.dumps({"message": "Hello"})
        result = mock_role.parse_phase_llm_response(response, game_state)
        assert result == {"message": "Hello"}

    def test_parse_phase_llm_response_invalid_json(self, mock_role, game_state):
        """Test handling invalid JSON responses."""
        response = "Not valid JSON"
        result = mock_role.parse_phase_llm_response(response, game_state)
        assert "error" in result
        assert result["raw_response"] == "Not valid JSON"

    def test_custom_response_parser(self, mock_role, game_state):
        """Test registering and using a custom response parser."""

        def custom_parser(response, state):
            return {"custom": True, "phase": state.meta.phase}

        mock_role.register_response_parser(0, custom_parser)
        result = mock_role.parse_phase_llm_response("Any response", game_state)

        assert result == {"custom": True, "phase": 0}

    def test_parse_pydantic_response(self, mock_role, game_state):
        """A validated Pydantic instance from the provider is passed through."""
        response = _SampleSchema(gameId=game_state.meta.game_id, action="go")
        result = mock_role.parse_phase_llm_response(response, game_state)
        assert result == {"gameId": game_state.meta.game_id, "action": "go"}

    def test_parse_with_registered_schema(self, mock_role, game_state):
        """Raw JSON is validated when a schema is registered for the phase."""
        mock_role.register_response_schema(game_state.meta.phase, _SampleSchema)
        result = mock_role.parse_phase_llm_response('{"gameId": 7, "action": "stop"}', game_state)
        assert result == {"gameId": 7, "action": "stop"}

    def test_parse_with_registered_schema_invalid(self, mock_role, game_state):
        """Invalid JSON surfaces a validation error payload when a schema is registered."""
        mock_role.register_response_schema(game_state.meta.phase, _SampleSchema)
        result = mock_role.parse_phase_llm_response('{"gameId": 7, "action": "sideways"}', game_state)
        assert result["error"] == "Failed to validate response"
        assert result["raw_response"] == '{"gameId": 7, "action": "sideways"}'


class TestPhaseSpecificMethods:
    """Tests for phase-specific methods."""

    def test_auto_register_methods(self, logger, prompts_path):
        """Test auto-registration of phase-specific methods."""

        class SpecializedRole(Role[GameStateProtocol]):
            role: ClassVar[int] = 1
            name: ClassVar[str] = "specialized_role"
            llm = MockLLM()

            def get_phase_1_system_prompt(self, state):
                return "Specialized system prompt"

            def get_phase_1_user_prompt(self, state):
                return "Specialized user prompt"

            def parse_phase_1_llm_response(self, response, state):
                return {"specialized": True}

            async def handle_phase_1(self, phase, state):
                return {"handled_by": "specialized"}

        role = SpecializedRole(logger=logger)
        assert 1 in role._system_prompt_handlers
        assert 1 in role._user_prompt_handlers
        assert 1 in role._response_parsers
        assert 1 in role._phase_handlers

    def test_class_level_response_schemas(self, logger):
        """Class-level ``response_schemas`` / ``default_response_schema`` are exposed via the registry."""

        class OtherSchema(BaseModel):
            reply: str

        class WithSchema(Role[GameStateProtocol]):
            role: ClassVar[int] = 1
            name: ClassVar[str] = "schema_role"
            llm = MockLLM()
            response_schemas = {2: _SampleSchema}
            default_response_schema = OtherSchema

        role = WithSchema(logger=logger)
        assert role.get_response_schema(2) is _SampleSchema
        assert role.get_response_schema(99) is OtherSchema

    @pytest.mark.asyncio
    async def test_llm_error_handling(self, mock_role, game_state, mocker, prompts_path):
        """Test error handling when LLM raises an exception."""

        # Make the LLM raise an exception
        async def mock_error(*args, **kwargs):
            raise Exception("LLM error")

        mocker.patch.object(mock_role.llm, "get_response", side_effect=mock_error)

        result = await mock_role.handle_phase_with_llm(0, game_state, prompts_path)

        assert "error" in result
        assert result["phase"] == 0
        assert "LLM error" in result["error"]
