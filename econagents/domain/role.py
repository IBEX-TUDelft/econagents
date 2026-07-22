import logging
import re
from abc import ABC
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, Generic, Optional, Pattern, Protocol, Type, TypeVar, Union

from pydantic import BaseModel

from econagents.domain.logging import LoggerMixin
from econagents.domain.messages import PhaseId
from econagents.domain.state.game import GameStateProtocol
from econagents.ports.llm import LLMProvider
from econagents.ports.parsing import ResponseParserPort
from econagents.ports.prompts import PromptRendererPort, PromptType
from econagents.ports.tools import Tool, ToolCall, ToolContext
from econagents.personas import Persona

StateT_contra = TypeVar("StateT_contra", bound=GameStateProtocol, contravariant=True)


PERSONA_INSTRUCTION = (
    "Stay in character. Decide as this person would, given who they are — "
    "their situation, tendencies, and outlook — rather than as a neutral "
    "analyst optimising the payoff table."
)
"""Directive appended after the persona block so the description is treated as
a role to inhabit rather than background colour. Override this module-level
constant to change the wording."""


def _format_persona_block(persona: Persona) -> str:
    """Render a Persona as a standard prompt-friendly markdown block.

    Sections with empty underlying data are omitted, so the output is a tight
    block with no placeholder noise. Returns an empty string if the persona
    has no demographics, traits, or bio populated. When any section is present,
    ``PERSONA_INSTRUCTION`` is appended telling the model to act in character.
    """
    parts: list[str] = []
    if persona.demographics:
        parts.append("## About You")
        parts.append("")
        for key, value in persona.demographics.items():
            parts.append(f"- {key.replace('_', ' ')}: {value}")
        parts.append("")
    if persona.traits:
        parts.append("Tendencies:")
        for trait, level in persona.traits.items():
            parts.append(f"- {trait.replace('_', ' ')}: {level}")
        parts.append("")
    if persona.bio:
        parts.append(persona.bio.rstrip())
    if not parts:
        return ""
    parts.append("")
    parts.append(PERSONA_INSTRUCTION)
    return "\n".join(parts).rstrip()


class RoleProtocol(Protocol):
    role: ClassVar[int]
    name: ClassVar[str]
    llm: LLMProvider
    task_phases: ClassVar[list[PhaseId]]


SystemPromptHandler = Callable[[StateT_contra], str]
UserPromptHandler = Callable[[StateT_contra], str]
ResponseParser = Callable[[Union[str, BaseModel], StateT_contra], dict]
PhaseHandler = Callable[[PhaseId, StateT_contra], Any]


class Role(ABC, Generic[StateT_contra], LoggerMixin):
    """Base role class with common attributes and phase handling.

    This class provides a flexible framework for handling different phases in a game or task workflow.
    It uses injected prompt rendering and response parsing ports and allows customization for specific phases.

    Args:
        logger (Optional[logging.Logger]): External logger to use, defaults to None
    """

    role: ClassVar[int]
    """Unique identifier for this role"""
    name: ClassVar[str]
    """Human-readable name for this role"""
    llm: LLMProvider
    """Language model instance for generating responses"""
    task_phases: ClassVar[list[PhaseId]] = []  # Empty list means no specific phases are required
    """List of phases this agent should participate in (empty means all phases)"""
    task_phases_excluded: ClassVar[list[PhaseId]] = []  # Empty list means no phases are excluded
    """ Alternative way to specify phases this agent should participate in, listed phases are excluded (empty means nothing excluded)"""
    response_schemas: ClassVar[Dict[PhaseId, Type[BaseModel]]] = {}
    """Phase-specific Pydantic schemas used as structured output formats."""
    default_response_schema: ClassVar[Optional[Type[BaseModel]]] = None
    """Fallback schema used for phases not listed in ``response_schemas``."""
    prompt_renderer: PromptRendererPort | None = None
    """Renderer used by the default prompt path."""
    response_parser: ResponseParserPort | None = None
    """Parser used by the default LLM response path."""
    # Regex patterns for method name extraction
    _SYSTEM_PROMPT_PATTERN: ClassVar[Pattern] = re.compile(r"get_phase_(\d+)_system_prompt")
    _USER_PROMPT_PATTERN: ClassVar[Pattern] = re.compile(r"get_phase_(\d+)_user_prompt")
    _RESPONSE_PARSER_PATTERN: ClassVar[Pattern] = re.compile(r"parse_phase_(\d+)_llm_response")
    _PHASE_HANDLER_PATTERN: ClassVar[Pattern] = re.compile(r"handle_phase_(\d+)$")

    persona: Optional[Persona] = None
    """Optional persona injected into the prompt context as ``persona``."""
    tools: ClassVar[list[Tool]] = []
    """Read-only tools the LLM may call while handling a phase. Override per
    role, or pass ``tools=`` to the constructor."""
    max_tool_iterations: ClassVar[int] = 5
    """Safety cap on tool-call rounds per LLM response."""
    auto_render_persona: ClassVar[bool] = True
    """When ``True`` and a persona is attached, append a standard markdown block
    describing the persona to the end of the system prompt. Set to ``False`` to
    take full control via ``{{ persona }}`` in your own template."""

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        persona: Optional[Persona] = None,
        prompt_renderer: PromptRendererPort | None = None,
        response_parser: ResponseParserPort | None = None,
        tools: Optional[list[Tool]] = None,
    ):
        if logger:
            self.logger = logger

        if persona is not None:
            self.persona = persona

        resolved_tools = tools if tools is not None else self.tools
        self._tools_by_name: Dict[str, Tool] = {tool.name: tool for tool in resolved_tools}

        if prompt_renderer is not None:
            self.prompt_renderer = prompt_renderer
        if response_parser is not None:
            self.response_parser = response_parser

        # Validate that only one of task_phases or task_phases_excluded is specified
        if self.task_phases and self.task_phases_excluded:
            raise ValueError(
                f"Only one of task_phases or task_phases_excluded should be specified, not both. "
                f"Got task_phases={self.task_phases} and task_phases_excluded={self.task_phases_excluded}"
            )

        # Handler registries
        self._system_prompt_handlers: Dict[PhaseId, SystemPromptHandler] = {}
        self._user_prompt_handlers: Dict[PhaseId, UserPromptHandler] = {}
        self._response_parsers: Dict[PhaseId, ResponseParser] = {}
        self._response_schemas: Dict[PhaseId, Type[BaseModel]] = dict(self.response_schemas)
        self._phase_handlers: Dict[PhaseId, PhaseHandler] = {}

        # Auto-register phase-specific methods if they exist
        self._register_phase_specific_methods()

    def _resolve_prompt_file(
        self, prompt_type: PromptType, phase: PhaseId, role: str, prompts_path: Path
    ) -> Optional[Path]:
        """Resolve the prompt file path for the given parameters.

        Args:
            prompt_type: Type of prompt (system, user)
            phase (int): Game phase number
            role (str): Agent role name
            prompts_path (Path): Path to prompt templates directory

        Returns:
            Path to the prompt file if found, None otherwise

        Raises:
            FileNotFoundError: If no matching prompt template is found
        """
        phase_file = prompts_path / f"{role.lower()}_{prompt_type}_phase_{phase}.jinja2"
        if phase_file.exists():
            return phase_file

        general_file = prompts_path / f"{role.lower()}_{prompt_type}.jinja2"
        if general_file.exists():
            return general_file

        return None

    def render_prompt(self, context: dict, prompt_type: PromptType, phase: PhaseId, prompts_path: Path) -> str:
        """Render a prompt template with the given context.

        Template resolution order:

        1. Role-specific phase prompt (e.g., "role_name_system_phase_1.jinja2")

        2. Role-specific general prompt (e.g., "role_name_system.jinja2")

        3. All-role phase prompt (e.g., "all_system_phase_1.jinja2")

        4. All-role general prompt (e.g., "all_system.jinja2")

        Args:
            context (dict): Template context variables
            prompt_type: Type of prompt (system, user)
            phase (int): Game phase number
            prompts_path (Path): Path to prompt templates directory

        Returns:
            str: Rendered prompt

        Raises:
            FileNotFoundError: If no matching prompt template is found
        """
        if self.prompt_renderer is None:
            raise RuntimeError("Role requires a prompt renderer to render prompts.")

        return self.prompt_renderer.render(
            context=context,
            prompt_type=prompt_type,
            phase=phase,
            prompts_path=prompts_path,
            role_names=[self.name, "all"],
            resolver=self._resolve_prompt_file,
            logger=self.logger,
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

    def register_system_prompt_handler(self, phase: PhaseId, handler: SystemPromptHandler) -> None:
        """Register a custom system prompt handler for a specific phase.

        Args:
            phase (int): Game phase number
            handler (SystemPromptHandler): Function that generates system prompts for this phase
        """
        self._system_prompt_handlers[phase] = handler
        self.logger.debug(f"Registered system prompt handler for phase {phase}")

    def register_user_prompt_handler(self, phase: PhaseId, handler: UserPromptHandler) -> None:
        """Register a custom user prompt handler for a specific phase.

        Args:
            phase (int): Game phase number
            handler (UserPromptHandler): Function that generates user prompts for this phase
        """
        self._user_prompt_handlers[phase] = handler
        self.logger.debug(f"Registered user prompt handler for phase {phase}")

    def register_response_parser(self, phase: PhaseId, parser: ResponseParser) -> None:
        """Register a custom response parser for a specific phase.

        Args:
            phase (int): Game phase number
            parser (ResponseParser): Function that parses LLM responses for this phase
        """
        self._response_parsers[phase] = parser
        self.logger.debug(f"Registered response parser for phase {phase}")

    def register_response_schema(self, phase: PhaseId, schema: Type[BaseModel]) -> None:
        """Register a Pydantic response schema for a specific phase.

        When a schema is registered, the LLM is asked to emit structured
        output matching it, and the parsed instance is used as the phase
        result.

        Args:
            phase (int): Game phase number
            schema (Type[BaseModel]): Pydantic model describing the output
        """
        self._response_schemas[phase] = schema
        self.logger.debug(f"Registered response schema for phase {phase}")

    def get_response_schema(self, phase: PhaseId) -> Optional[Type[BaseModel]]:
        """Return the schema to use for a given phase, if any."""
        if phase in self._response_schemas:
            return self._response_schemas[phase]
        return self.default_response_schema

    def register_phase_handler(self, phase: PhaseId, handler: PhaseHandler) -> None:
        """Register a custom phase handler for a specific phase.

        Args:
            phase (int): Game phase number
            handler (PhaseHandler): Function that handles this phase
        """
        self._phase_handlers[phase] = handler
        self.logger.debug(f"Registered phase handler for phase {phase}")

    def _build_context(self, state: StateT_contra) -> dict:
        """Build the prompt render context from state plus optional persona.

        State keys win on collision; persona is decoration.
        """
        context: dict = {"persona": self.persona.model_dump() if self.persona is not None else None}
        context.update(state.model_dump())
        return context

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
        rendered = self.render_prompt(
            context=self._build_context(state), prompt_type="system", phase=phase, prompts_path=prompts_path
        )
        if self.auto_render_persona and self.persona is not None:
            block = _format_persona_block(self.persona)
            if block:
                rendered = rendered.rstrip() + "\n\n" + block
        return rendered

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
            context=self._build_context(state), prompt_type="user", phase=phase, prompts_path=prompts_path
        )

    def parse_phase_llm_response(self, response: Union[str, BaseModel], state: StateT_contra) -> dict:
        """Parse the LLM response for the current phase.

        Resolution order:

        1. A phase-specific parser registered via ``register_response_parser``.
        2. If the provider returned a validated Pydantic instance, its
           ``model_dump()``.
        3. If a response schema is registered for this phase (or a default
           schema is set), validate the raw string against it.
        4. Fall back to ``json.loads`` on the raw string.

        Args:
            response: Either a raw LLM response string or a Pydantic instance
                produced by a structured-output-capable provider.
            state: Current game state.

        Returns:
            dict: Parsed response as a dictionary.
        """
        phase = state.meta.phase
        if phase in self._response_parsers:
            return self._response_parsers[phase](response, state)

        if self.response_parser is None:
            raise RuntimeError("Role requires a response parser to parse LLM responses.")

        return self.response_parser.parse(
            response=response,
            state=state,
            phase=phase,
            response_schema=self.get_response_schema(phase),
            logger=self.logger,
        )

    async def handle_phase(self, phase: PhaseId, state: StateT_contra, prompts_path: Path) -> Optional[dict]:
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

    async def handle_phase_with_llm(self, phase: PhaseId, state: StateT_contra, prompts_path: Path) -> Optional[dict]:
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

        tool_kwargs = self._build_tool_kwargs(phase, state)

        try:
            response = await self.llm.get_response(
                messages=messages,
                tracing_extra={
                    "state": state.model_dump(),
                },
                response_schema=self.get_response_schema(phase),
                **tool_kwargs,
            )
            return self.parse_phase_llm_response(response, state)
        except Exception as e:
            self.logger.error(f"Error getting LLM response: {e}")
            return {"error": str(e), "phase": phase}

    def _build_tool_kwargs(self, phase: PhaseId, state: StateT_contra) -> dict[str, Any]:
        """Build the ``tools``/``tool_executor`` kwargs for the LLM call.

        Returns an empty dict when the role has no tools, leaving the plain
        single-shot LLM path unchanged.
        """
        if not self._tools_by_name:
            return {}

        ctx = ToolContext(state=state, phase=phase, logger=self.logger)

        async def executor(call: ToolCall) -> Any:
            tool = self._tools_by_name.get(call.name)
            if tool is None:
                return {"error": f"Unknown tool: {call.name}"}
            try:
                return await tool.run(call.arguments, ctx)
            except Exception as exc:  # noqa: BLE001 - surfaced back to the model
                self.logger.error(f"Tool {call.name!r} failed: {exc}")
                return {"error": f"Tool {call.name} failed: {exc}"}

        return {
            "tools": [tool.spec() for tool in self._tools_by_name.values()],
            "tool_executor": executor,
            "max_tool_iterations": self.max_tool_iterations,
        }
