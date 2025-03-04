import json
import logging
import re
from abc import ABC
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, Generic, Optional, Pattern, Protocol, TypeVar

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


SystemPromptHandler = Callable[[StateT_contra], str]
UserPromptHandler = Callable[[StateT_contra], str]
ResponseParser = Callable[[str, StateT_contra], dict]
PhaseHandler = Callable[[int, StateT_contra], Any]


class Agent(ABC, Generic[StateT_contra]):
    """Base agent class with common attributes and turn-based functionality.

    This class provides a flexible framework for handling different phases in a turn-based game.
    It allows for:
    1. Default behavior for all phases
    2. Custom handlers for specific phases
    3. Custom prompt generators for specific phases
    4. Custom response parsers for specific phases

    To customize behavior for a specific phase, subclasses can:
    1. Override the default methods (get_phase_system_prompt, get_phase_user_prompt, parse_phase_llm_response)
    2. Register custom handlers using the register_* methods
    3. Implement phase-specific methods following the naming convention:
       - get_phase_p{phase_number}_system_prompt
       - get_phase_p{phase_number}_user_prompt
       - parse_phase_p{phase_number}_llm_response
       - handle_phase_p{phase_number}
    """

    # Class attributes
    role: ClassVar[int]
    name: ClassVar[str]
    task_phases: ClassVar[list[int]] = []  # Empty list means no specific phases are required
    task_phases_excluded: ClassVar[list[int]] = []  # Empty list means no phases are excluded

    # Regex patterns for method name extraction
    _SYSTEM_PROMPT_PATTERN: ClassVar[Pattern] = re.compile(r"get_phase_(\d+)_system_prompt")
    _USER_PROMPT_PATTERN: ClassVar[Pattern] = re.compile(r"get_phase_(\d+)_user_prompt")
    _RESPONSE_PARSER_PATTERN: ClassVar[Pattern] = re.compile(r"parse_phase_(\d+)_llm_response")
    _PHASE_HANDLER_PATTERN: ClassVar[Pattern] = re.compile(r"handle_phase_(\d+)$")

    def __init__(self, logger: logging.Logger, llm: ChatOpenAI, game_id: int, prompts_path: Path):
        """Initialize the agent.

        Args:
            logger: Logger instance for this agent
            llm: Language model client
            game_id: ID of the current game
            prompts_path: Path to prompt templates
        """
        self.llm = llm
        self.game_id = game_id
        self.logger = logger
        self.prompts_path = prompts_path

        # Validate that only one of task_phases or task_phases_excluded is specified
        if self.task_phases and self.task_phases_excluded:
            raise ValueError(
                f"Only one of task_phases or task_phases_excluded should be specified, not both. "
                f"Got task_phases={self.task_phases} and task_phases_excluded={self.task_phases_excluded}"
            )

        # Handler registries
        self._system_prompt_handlers: Dict[int, SystemPromptHandler] = {}
        self._user_prompt_handlers: Dict[int, UserPromptHandler] = {}
        self._response_parsers: Dict[int, ResponseParser] = {}
        self._phase_handlers: Dict[int, PhaseHandler] = {}

        # Auto-register phase-specific methods if they exist
        self._register_phase_specific_methods()

    def _resolve_prompt_file(self, prompt_type: str, phase: int, role: str) -> Optional[Path]:
        """Resolve the prompt file path for the given parameters.

        Args:
            prompt_type: Type of prompt (system, user)
            phase: Game phase number
            role: Agent role name

        Returns:
            Path to the prompt file if found, None otherwise
        """
        # Try phase-specific prompt first
        phase_file = self.prompts_path / f"{role.lower()}_{prompt_type}_phase_{phase}.jinja2"
        if phase_file.exists():
            return phase_file

        # Fall back to general prompt
        general_file = self.prompts_path / f"{role.lower()}_{prompt_type}.jinja2"
        if general_file.exists():
            return general_file

        return None

    def render_prompt(self, context: dict, prompt_type: str, phase: int) -> str:
        """Render a prompt template with the given context.

        Args:
            context: Template context variables
            prompt_type: Type of prompt (system, user)
            phase: Game phase number

        Returns:
            Rendered prompt string

        Raises:
            FileNotFoundError: If no matching prompt template is found
        """
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

    def _extract_phase_from_pattern(self, attr_name: str, pattern: Pattern) -> Optional[int]:
        """Extract phase number from a method name using regex pattern.

        Args:
            attr_name: Method name
            pattern: Regex pattern with a capturing group for the phase number

        Returns:
            Phase number if found and valid, None otherwise
        """
        if match := pattern.match(attr_name):
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                self.logger.warning(f"Failed to extract phase number from {attr_name}")
        return None

    def _register_phase_specific_methods(self) -> None:
        """Automatically register phase-specific methods if they exist in the subclass."""
        for attr_name in dir(self):
            # Skip special methods and non-callable attributes
            if attr_name.startswith("__") or not callable(getattr(self, attr_name, None)):
                continue

            # Check for phase-specific system prompt handlers
            if phase := self._extract_phase_from_pattern(attr_name, self._SYSTEM_PROMPT_PATTERN):
                self.register_system_prompt_handler(phase, getattr(self, attr_name))

            # Check for phase-specific user prompt handlers
            elif phase := self._extract_phase_from_pattern(attr_name, self._USER_PROMPT_PATTERN):
                self.register_user_prompt_handler(phase, getattr(self, attr_name))

            # Check for phase-specific response parsers
            elif phase := self._extract_phase_from_pattern(attr_name, self._RESPONSE_PARSER_PATTERN):
                self.register_response_parser(phase, getattr(self, attr_name))

            # Check for phase-specific handlers
            elif phase := self._extract_phase_from_pattern(attr_name, self._PHASE_HANDLER_PATTERN):
                self.register_phase_handler(phase, getattr(self, attr_name))

    def register_system_prompt_handler(self, phase: int, handler: SystemPromptHandler) -> None:
        """Register a custom system prompt handler for a specific phase.

        Args:
            phase: Game phase number
            handler: Function that generates system prompts for this phase
        """
        self._system_prompt_handlers[phase] = handler
        self.logger.debug(f"Registered system prompt handler for phase {phase}")

    def register_user_prompt_handler(self, phase: int, handler: UserPromptHandler) -> None:
        """Register a custom user prompt handler for a specific phase.

        Args:
            phase: Game phase number
            handler: Function that generates user prompts for this phase
        """
        self._user_prompt_handlers[phase] = handler
        self.logger.debug(f"Registered user prompt handler for phase {phase}")

    def register_response_parser(self, phase: int, parser: ResponseParser) -> None:
        """Register a custom response parser for a specific phase.

        Args:
            phase: Game phase number
            parser: Function that parses LLM responses for this phase
        """
        self._response_parsers[phase] = parser
        self.logger.debug(f"Registered response parser for phase {phase}")

    def register_phase_handler(self, phase: int, handler: PhaseHandler) -> None:
        """Register a custom phase handler for a specific phase.

        Args:
            phase: Game phase number
            handler: Function that handles this phase
        """
        self._phase_handlers[phase] = handler
        self.logger.debug(f"Registered phase handler for phase {phase}")

    def get_phase_system_prompt(self, state: StateT_contra) -> str:
        """Get the system prompt for the current phase.

        This method will use a phase-specific handler if registered,
        otherwise it falls back to the default implementation.

        Args:
            state: Current game state

        Returns:
            System prompt string
        """
        phase = state.meta.phase
        if phase in self._system_prompt_handlers:
            return self._system_prompt_handlers[phase](state)
        return self.render_prompt(context=state.model_dump(), prompt_type="system", phase=phase)

    def get_phase_user_prompt(self, state: StateT_contra) -> str:
        """Get the user prompt for the current phase.

        This method will use a phase-specific handler if registered,
        otherwise it falls back to the default implementation.

        Args:
            state: Current game state

        Returns:
            User prompt string
        """
        phase = state.meta.phase
        if phase in self._user_prompt_handlers:
            return self._user_prompt_handlers[phase](state)
        return self.render_prompt(context=state.model_dump(), prompt_type="user", phase=phase)

    def parse_phase_llm_response(self, response: str, state: StateT_contra) -> dict:
        """Parse the LLM response for the current phase.

        This method will use a phase-specific parser if registered,
        otherwise it falls back to the default implementation.

        Args:
            response: Raw LLM response string
            state: Current game state

        Returns:
            Parsed response as a dictionary
        """
        phase = state.meta.phase
        if phase in self._response_parsers:
            return self._response_parsers[phase](response, state)

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse LLM response as JSON: {e}")
            self.logger.debug(f"Raw response: {response}")
            return {"error": "Failed to parse response", "raw_response": response}

    async def handle_phase(self, phase: int, state: StateT_contra) -> Optional[dict]:
        """Handle the phase.

        This method will use a phase-specific handler if registered,
        otherwise it falls back to the default implementation.

        By default, the agent acts in all phases unless:
        1. task_phases is non-empty and the phase is not in task_phases, or
        2. phase is explicitly listed in task_phases_excluded

        Args:
            phase: Game phase number
            state: Current game state

        Returns:
            Phase result dictionary or None if phase is not handled
        """
        # Skip the phase if it's in the excluded list
        if phase in self.task_phases_excluded:
            self.logger.debug(f"Phase {phase} is in excluded phases {self.task_phases_excluded}, skipping")
            return None

        # Skip the phase if task_phases is non-empty and phase is not in it
        if self.task_phases and phase not in self.task_phases:
            self.logger.debug(f"Phase {phase} not in task phases {self.task_phases}, skipping")
            return None

        if phase in self._phase_handlers:
            self.logger.debug(f"Using custom handler for phase {phase}")
            return await self._phase_handlers[phase](phase, state)

        self.logger.debug(f"Using default LLM handler for phase {phase}")
        return await self.handle_phase_with_llm(phase, state)

    async def handle_phase_with_llm(self, phase: int, state: StateT_contra) -> Optional[dict]:
        """Handle the phase with LLM.

        This is the default implementation that uses the LLM to handle the phase.

        Args:
            phase: Game phase number
            state: Current game state

        Returns:
            Phase result dictionary
        """
        system_prompt = self.get_phase_system_prompt(state)
        user_prompt = self.get_phase_user_prompt(state)

        messages = self.llm.build_messages(system_prompt, user_prompt)

        try:
            response = await self.llm.get_response(
                messages=messages,
                tracing_extra={
                    "game_id": self.game_id,
                    "state": state.model_dump(),
                },
            )
            return self.parse_phase_llm_response(response, state)
        except Exception as e:
            self.logger.error(f"Error getting LLM response: {e}")
            return {"error": str(e), "phase": phase}
