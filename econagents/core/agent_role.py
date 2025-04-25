import json
import logging
import re
from abc import ABC
from pathlib import Path
from jinja2 import FileSystemLoader
from typing import Any, Callable, ClassVar, Dict, Generic, Literal, Optional, Pattern, Protocol, TypeVar

from jinja2.sandbox import SandboxedEnvironment

from econagents.core.logging_mixin import LoggerMixin
from econagents.core.state.game import GameStateProtocol
from econagents.llm.base import BaseLLM

StateT_contra = TypeVar("StateT_contra", bound=GameStateProtocol, contravariant=True)


class AgentProtocol(Protocol):
    role: ClassVar[int]
    name: ClassVar[str]
    llm: BaseLLM
    task_phases: ClassVar[list[int]]


SystemPromptHandler = Callable[[StateT_contra], str]
UserPromptHandler = Callable[[StateT_contra], str]
ResponseParser = Callable[[str, StateT_contra], dict]
PhaseHandler = Callable[[int, StateT_contra], Any]


class AgentRole(ABC, Generic[StateT_contra], LoggerMixin):
    """Base agent role class with common attributes and phase handling.

    This class provides a flexible framework for handling different phases in a game or task workflow.
    It uses template-based prompts and allows customization of behavior for specific phases.

    Args:
        logger (Optional[logging.Logger]): External logger to use, defaults to None
    """

    role: ClassVar[int]
    """Unique identifier for this role"""
    name: ClassVar[str]
    """Human-readable name for this role"""
    llm: BaseLLM
    """Language model instance for generating responses"""
    task_phases: ClassVar[list[int]] = []  # Empty list means no specific phases are required
    """List of phases this agent should participate in (empty means all phases)"""
    task_phases_excluded: ClassVar[list[int]] = []  # Empty list means no phases are excluded
    """ Alternative way to specify phases this agent should participate in, listed phases are excluded (empty means nothing excluded)"""
    # Regex patterns for method name extraction
    _SYSTEM_PROMPT_PATTERN: ClassVar[Pattern] = re.compile(r"get_phase_(\d+)_system_prompt")
    _USER_PROMPT_PATTERN: ClassVar[Pattern] = re.compile(r"get_phase_(\d+)_user_prompt")
    _RESPONSE_PARSER_PATTERN: ClassVar[Pattern] = re.compile(r"parse_phase_(\d+)_llm_response")
    _PHASE_HANDLER_PATTERN: ClassVar[Pattern] = re.compile(r"handle_phase_(\d+)$")

    def __init__(self, logger: Optional[logging.Logger] = None):
        if logger:
            self.logger = logger

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

    def _resolve_prompt_file(
        self, prompt_type: Literal["system", "user"], phase: int, role: str, prompts_path: Path
    ) -> Optional[Path]:
        """Resolve the prompt file path for the given parameters.

        Args:
            prompt_type (Literal["system", "user"]): Type of prompt (system, user)
            phase (int): Game phase number
            role (str): Agent role name
            prompts_path (Path): Path to prompt templates directory

        Returns:
            Path to the prompt file if found, None otherwise

        Raises:
            FileNotFoundError: If no matching prompt template is found
        """
        # Try phase-specific prompt first
        phase_file = prompts_path / f"{role.lower()}_{prompt_type}_phase_{phase}.jinja2"
        if phase_file.exists():
            return phase_file

        # Fall back to general prompt
        general_file = prompts_path / f"{role.lower()}_{prompt_type}.jinja2"
        if general_file.exists():
            return general_file

        return None

    def render_prompt(
        self, context: dict, prompt_type: Literal["system", "user"], phase: int, prompts_path: Path
    ) -> str:
        """Render a prompt template with the given context.

        Template resolution order:

        1. Role-specific phase prompt (e.g., "role_name_system_phase_1.jinja2")

        2. Role-specific general prompt (e.g., "role_name_system.jinja2")

        3. All-role phase prompt (e.g., "all_system_phase_1.jinja2")

        4. All-role general prompt (e.g., "all_system.jinja2")

        Args:
            context (dict): Template context variables
            prompt_type (Literal["system", "user"]): Type of prompt (system, user)
            phase (int): Game phase number
            prompts_path (Path): Path to prompt templates directory

        Returns:
            str: Rendered prompt

        Raises:
            FileNotFoundError: If no matching prompt template is found
        """
        # Initialize Jinja environment with a file system loader
        env = SandboxedEnvironment(loader=FileSystemLoader(prompts_path))

        # Try role-specific prompt first, then fall back to 'all'
        for role in [self.name, "all"]:
            if prompt_file_path := self._resolve_prompt_file(prompt_type, phase, role, prompts_path):
                # Get filename relative to the prompts_path for the loader
                template_filename = str(prompt_file_path.relative_to(prompts_path))
                try:
                    template = env.get_template(template_filename)
                    return template.render(**context)
                except Exception as e:  # Catch potential Jinja errors during loading/rendering
                    self.logger.error(f"Error loading/rendering template {template_filename}: {e}")
                    raise  # Re-raise after logging

        raise FileNotFoundError(
            f"No prompt template found for type={prompt_type}, phase={phase}, "
            f"roles=[{self.name}, all] in {prompts_path}"
        )

    def _extract_phase_from_pattern(self, attr_name: str, pattern: Pattern) -> Optional[int]:
        """Extract phase number from a method name using regex pattern.

        Args:
            attr_name (str): Method name
            pattern (Pattern): Regex pattern with a capturing group for the phase number

        Returns:
            Optional[int]: Phase number if found and valid, None otherwise
        """
        if match := pattern.match(attr_name):
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                self.logger.warning(f"Failed to extract phase number from {attr_name}")
        return None

    def _register_phase_specific_methods(self) -> None:
        """Automatically register phase-specific methods if they exist in the subclass.

        This method scans the class for methods matching the naming patterns for
        phase-specific handlers and registers them automatically.
        """
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
            phase (int): Game phase number
            handler (SystemPromptHandler): Function that generates system prompts for this phase
        """
        self._system_prompt_handlers[phase] = handler
        self.logger.debug(f"Registered system prompt handler for phase {phase}")

    def register_user_prompt_handler(self, phase: int, handler: UserPromptHandler) -> None:
        """Register a custom user prompt handler for a specific phase.

        Args:
            phase (int): Game phase number
            handler (UserPromptHandler): Function that generates user prompts for this phase
        """
        self._user_prompt_handlers[phase] = handler
        self.logger.debug(f"Registered user prompt handler for phase {phase}")

    def register_response_parser(self, phase: int, parser: ResponseParser) -> None:
        """Register a custom response parser for a specific phase.

        Args:
            phase (int): Game phase number
            parser (ResponseParser): Function that parses LLM responses for this phase
        """
        self._response_parsers[phase] = parser
        self.logger.debug(f"Registered response parser for phase {phase}")

    def register_phase_handler(self, phase: int, handler: PhaseHandler) -> None:
        """Register a custom phase handler for a specific phase.

        Args:
            phase (int): Game phase number
            handler (PhaseHandler): Function that handles this phase
        """
        self._phase_handlers[phase] = handler
        self.logger.debug(f"Registered phase handler for phase {phase}")

    def get_phase_system_prompt(self, state: StateT_contra, prompts_path: Path) -> str:
        """Get the system prompt for the current phase.

        This method will use a phase-specific handler if registered,
        otherwise it falls back to the default implementation using templates.

        Args:
            state (StateT_contra): Current game state
            prompts_path (Path): Path to prompt templates directory

        Returns:
            str: System prompt string
        """
        phase = state.meta.phase
        if phase in self._system_prompt_handlers:
            return self._system_prompt_handlers[phase](state)
        return self.render_prompt(
            context=state.model_dump(), prompt_type="system", phase=phase, prompts_path=prompts_path
        )

    def get_phase_user_prompt(self, state: StateT_contra, prompts_path: Path) -> str:
        """Get the user prompt for the current phase.

        This method will use a phase-specific handler if registered,
        otherwise it falls back to the default implementation using templates.

        Args:
            state (StateT_contra): Current game state
            prompts_path (Path): Path to prompt templates directory

        Returns:
            str: User prompt string
        """
        phase = state.meta.phase
        if phase in self._user_prompt_handlers:
            return self._user_prompt_handlers[phase](state)
        return self.render_prompt(
            context=state.model_dump(), prompt_type="user", phase=phase, prompts_path=prompts_path
        )

    def parse_phase_llm_response(self, response: str, state: StateT_contra) -> dict:
        """Parse the LLM response for the current phase.

        This method will use a phase-specific parser if registered,
        otherwise it falls back to the default implementation which attempts
        to parse the response as JSON.

        Args:
            response (str): Raw LLM response string
            state (StateT_contra): Current game state

        Returns:
            dict: Parsed response as a dictionary
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

    async def handle_phase(self, phase: int, state: StateT_contra, prompts_path: Path) -> Optional[dict]:
        """Handle the current phase of the task or game.

        This method will use a phase-specific handler if registered,
        otherwise it falls back to the default implementation using the LLM.

        By default, the agent acts in all phases unless:
        1. task_phases is non-empty and the phase is not in task_phases, or
        2. phase is explicitly listed in task_phases_excluded

        Args:
            phase (int): Game phase number
            state (StateT_contra): Current game state
            prompts_path (Path): Path to prompt templates directory

        Returns:
            Optional[dict]: Phase result dictionary or None if phase is not handled
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
        return await self.handle_phase_with_llm(phase, state, prompts_path=prompts_path)

    async def handle_phase_with_llm(self, phase: int, state: StateT_contra, prompts_path: Path) -> Optional[dict]:
        """Handle the phase using the LLM.

        This is the default implementation that uses the LLM to handle the phase
        by generating prompts, sending them to the LLM, and parsing the response.

        Args:
            phase (int): Game phase number
            state (StateT_contra): Current game state
            prompts_path (Path): Path to prompt templates directory

        Returns:
            Optional[dict]: Phase result dictionary or None if phase is not handled
        """
        system_prompt = self.get_phase_system_prompt(state, prompts_path=prompts_path)
        self.logger.debug("\n+-----SYSTEM PROMPT----+\n" + f"{system_prompt}\n+------------------+")

        user_prompt = self.get_phase_user_prompt(state, prompts_path=prompts_path)
        self.logger.debug("\n+-----USER PROMPT----+\n" + f"{user_prompt}\n+------------------+")

        messages = self.llm.build_messages(system_prompt, user_prompt)

        try:
            response = await self.llm.get_response(
                messages=messages,
                tracing_extra={
                    "state": state.model_dump(),
                },
            )
            return self.parse_phase_llm_response(response, state)
        except Exception as e:
            self.logger.error(f"Error getting LLM response: {e}")
            return {"error": str(e), "phase": phase}
