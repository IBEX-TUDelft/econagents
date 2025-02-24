import json
import logging
from abc import ABC
from pathlib import Path
from typing import ClassVar, Optional, Protocol, TypeVar

from jinja2.sandbox import SandboxedEnvironment

from econagents.core.state.game import GameStateProtocol
from econagents.llm.openai import ChatOpenAI

StateT_contra = TypeVar("StateT_contra", bound=GameStateProtocol, contravariant=True)


class AgentProtocol(Protocol):
    """Base protocol for all agents."""

    role: ClassVar[int]
    name: ClassVar[str]
    llm: ChatOpenAI
    task_phases: ClassVar[list[int]]


class TurnBasedAgentProtocol(AgentProtocol, Protocol[StateT_contra]):
    """Protocol for agents that handle turn-based game phases."""

    async def handle_phase(self, phase: int, state: StateT_contra) -> Optional[dict]: ...


class MarketAgentProtocol(AgentProtocol, Protocol[StateT_contra]):
    """Protocol for agents that handle market-based interactions."""

    async def handle_phase_tick(self, state: StateT_contra) -> Optional[dict]: ...


class BaseAgent(ABC):
    """Base agent class with common attributes."""

    role: ClassVar[int]
    name: ClassVar[str]
    llm: ChatOpenAI
    task_phases: ClassVar[list[int]]

    def __init__(self, logger: logging.Logger, llm: ChatOpenAI, game_id: int, prompts_path: Path):
        self.llm = llm
        self.game_id = game_id
        self.logger = logger
        self.prompts_path = prompts_path

    def parse_llm_response(self, response: str, state: GameStateProtocol) -> dict:
        """Parse the LLM response."""
        return json.loads(response)

    def _resolve_prompt_file(self, prompt_type: str, phase: int, role: str) -> Path | None:
        """Resolve the prompt file path for the given parameters."""
        # Try phase-specific prompt first
        phase_file = self.prompts_path / f"{role.lower()}_{prompt_type}_p{phase}.jinja2"
        if phase_file.exists():
            return phase_file

        # Fall back to general prompt
        general_file = self.prompts_path / f"{role.lower()}_{prompt_type}.jinja2"
        if general_file.exists():
            return general_file

        return None

    def render_prompt(self, context: dict, prompt_type: str, phase: int) -> str:
        """Render a prompt template with the given context."""
        # Try role-specific prompt first, then fall back to 'all'
        for role in [self.name, "all"]:
            if prompt_file := self._resolve_prompt_file(prompt_type, phase, role):
                with prompt_file.open() as f:
                    template = SandboxedEnvironment().from_string(f.read())
                return template.render(**context)

        raise FileNotFoundError(
            f"No prompt template found for type={prompt_type}, phase={phase}, "
            f"roles=[{self.name}, all] in {self.prompts_path}"
        )


class TurnBasedAgent(BaseAgent, TurnBasedAgentProtocol[StateT_contra]):
    """Base class for agents that handle turn-based game phases."""

    def get_phase_system_prompt(self, state: GameStateProtocol) -> str:
        """Get the system prompt."""
        return self.render_prompt(context=state.model_dump(), prompt_type="system", phase=state.meta.phase)

    def get_phase_user_prompt(self, state: GameStateProtocol) -> str:
        """Get the user prompt."""
        return self.render_prompt(context=state.model_dump(), prompt_type="user", phase=state.meta.phase)

    def parse_phase_llm_response(self, response: str, state: GameStateProtocol) -> dict:
        """Parse the LLM response."""
        return json.loads(response)

    async def handle_phase(self, phase: int, state: StateT_contra) -> Optional[dict]:
        """Handle the phase."""
        if phase in self.task_phases:
            return await self.handle_phase_with_llm(phase, state)
        else:
            return None

    async def handle_phase_with_llm(self, phase: int, state: StateT_contra) -> Optional[dict]:
        """Handle the phase with LLM."""
        system_prompt = self.get_phase_system_prompt(state)
        user_prompt = self.get_phase_user_prompt(state)

        messages = self.llm.build_messages(system_prompt, user_prompt)

        response = await self.llm.get_response(
            messages=messages,
            # TODO: This should not be OpenAI-specific
            tracing_extra={
                "game_id": self.game_id,
                "state": state.model_dump(),
            },
        )
        return self.parse_llm_response(response, state)


class MarketAgent(BaseAgent, MarketAgentProtocol[StateT_contra]):
    """Base class for agents that handle market-based interactions."""

    def get_phase_tick_system_prompt(self, state: GameStateProtocol) -> str:
        """Get the system prompt."""
        return self.render_prompt(context=state.model_dump(), prompt_type="system", phase=state.meta.phase)

    def get_phase_tick_user_prompt(self, state: GameStateProtocol) -> str:
        """Get the user prompt."""
        return self.render_prompt(context=state.model_dump(), prompt_type="user", phase=state.meta.phase)

    def parse_phase_tick_llm_response(self, response: str, state: GameStateProtocol) -> dict:
        """Parse the LLM response."""
        return json.loads(response)

    async def handle_phase_tick(self, state: StateT_contra) -> Optional[dict]:
        """Handle the phase tick."""
        return await self.handle_phase_tick_with_llm(state)

    async def handle_phase_tick_with_llm(self, state: StateT_contra) -> Optional[dict]:
        """Handle the phase tick with LLM."""
        system_prompt = self.get_phase_tick_system_prompt(state)
        user_prompt = self.get_phase_tick_user_prompt(state)

        messages = self.llm.build_messages(system_prompt, user_prompt)

        response = await self.llm.get_response(
            messages=messages,
            # TODO: This should not be OpenAI-specific
            tracing_extra={
                "game_id": self.game_id,
                "state": state.model_dump(),
            },
        )
        return self.parse_phase_tick_llm_response(response, state)


class HybridAgent(TurnBasedAgent[StateT_contra], MarketAgent[StateT_contra]):
    """Agent that can handle both turn-based and market-based interactions."""

    pass
