import pytest
from pathlib import Path

from econagents.core.agent import Agent
from econagents.core.state.game import GameStateProtocol


class TestHelperMethods:
    """Tests for internal helper methods of the Agent class."""

    def test_extract_phase_from_pattern(self, mock_agent):
        """Test extracting phase numbers from method names using regex patterns."""
        # Valid method names
        assert (
            mock_agent._extract_phase_from_pattern("get_phase_1_system_prompt", mock_agent._SYSTEM_PROMPT_PATTERN) == 1
        )
        assert mock_agent._extract_phase_from_pattern("get_phase_42_user_prompt", mock_agent._USER_PROMPT_PATTERN) == 42
        assert (
            mock_agent._extract_phase_from_pattern("parse_phase_7_llm_response", mock_agent._RESPONSE_PARSER_PATTERN)
            == 7
        )
        assert mock_agent._extract_phase_from_pattern("handle_phase_15", mock_agent._PHASE_HANDLER_PATTERN) == 15

        # Invalid method names
        assert mock_agent._extract_phase_from_pattern("invalid_method_name", mock_agent._SYSTEM_PROMPT_PATTERN) is None
        assert (
            mock_agent._extract_phase_from_pattern("get_phase_x_system_prompt", mock_agent._SYSTEM_PROMPT_PATTERN)
            is None
        )

    def test_resolve_prompt_file(self, mock_agent):
        """Test resolving prompt file paths."""
        # Phase-specific prompt should be found
        phase_file = mock_agent._resolve_prompt_file("system", 1, "test_agent")
        assert phase_file is not None
        assert phase_file.name == "test_agent_system_phase_1.jinja2"

        # General prompt should be found when no phase-specific exists
        general_file = mock_agent._resolve_prompt_file("system", 2, "test_agent")
        assert general_file is not None
        assert general_file.name == "test_agent_system.jinja2"

        # Non-existent prompt should return None
        nonexistent_file = mock_agent._resolve_prompt_file("nonexistent", 1, "test_agent")
        assert nonexistent_file is None

    def test_register_phase_specific_methods(self, logger, mock_llm, prompts_path):
        """Test the automatic registration of phase-specific methods during initialization."""

        # Define a class with various phase-specific methods
        class PhaseSpecificAgent(Agent[GameStateProtocol]):
            """Agent with phase-specific methods."""

            role = 1
            name = "phase_specific"

            # Valid phase-specific methods
            def get_phase_1_system_prompt(self, state):
                return "Phase 1 system"

            def get_phase_2_user_prompt(self, state):
                return "Phase 2 user"

            def parse_phase_3_llm_response(self, response, state):
                return {"phase": 3}

            async def handle_phase_4(self, phase, state):
                return {"handled": 4}

            # Regular methods (should not be registered)
            def normal_method(self):
                return "normal"

            def get_phase_invalid_system_prompt(self, state):
                return "invalid"

        agent = PhaseSpecificAgent(logger=logger, llm=mock_llm, game_id=123, prompts_path=prompts_path)

        # Check correct registration
        assert 1 in agent._system_prompt_handlers
        assert 2 in agent._user_prompt_handlers
        assert 3 in agent._response_parsers
        assert 4 in agent._phase_handlers

        # Check incorrect methods were not registered
        assert "invalid" not in agent._system_prompt_handlers
        assert len(agent._system_prompt_handlers) == 1
        assert len(agent._user_prompt_handlers) == 1
        assert len(agent._response_parsers) == 1
        assert len(agent._phase_handlers) == 1

        # Test calling the registered methods
        assert agent._system_prompt_handlers[1](None) == "Phase 1 system"
        assert agent._user_prompt_handlers[2](None) == "Phase 2 user"
        assert agent._response_parsers[3]("test", None) == {"phase": 3}
