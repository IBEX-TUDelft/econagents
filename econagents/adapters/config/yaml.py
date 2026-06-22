import importlib
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type, cast
from datetime import datetime, date, time

import yaml
from pydantic import BaseModel, Field, create_model, model_validator

from econagents.runtime import Agent, PhaseEngine
from econagents.runtime.game_runner import (
    GameRunner,
    GameRunnerConfig,
    HybridGameRunnerConfig,
    TurnBasedGameRunnerConfig,
)
from econagents.runtime.experiment_factory import create_game_state
from econagents.domain.state.fields import EventField
from econagents.domain.state.game import (
    GameState,
    MetaInformation,
    PrivateInformation,
    PublicInformation,
)
from econagents.domain.role import Role
from econagents.domain.messages import PhaseId
from econagents.adapters.llm.observability import get_observability_provider
from econagents.personas import Persona

TYPE_MAPPING = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "datetime": datetime,
    "date": date,
    "time": time,
    "any": Any,
}


class EventHandlerSpec(BaseModel):
    """Configuration for an event handler."""

    event: str
    custom_code: Optional[str] = None
    custom_module: Optional[str] = None
    custom_function: Optional[str] = None


class RoleSpec(BaseModel):
    """Configuration for a role."""

    role_id: int
    name: str
    llm_type: str = "ChatOpenAI"
    llm_params: Dict[str, Any] = Field(default_factory=dict)
    prompts: List[Dict[str, str]] = Field(default_factory=list)
    task_phases: List[PhaseId] = Field(default_factory=list)
    task_phases_excluded: List[PhaseId] = Field(default_factory=list)

    def create_role(self, persona: Optional[Persona] = None) -> Role:
        """Create a Role instance from this configuration."""
        # Dynamically create the LLM provider
        llm_class = getattr(importlib.import_module("econagents.adapters.llm"), self.llm_type)
        llm_instance = llm_class(**self.llm_params)

        # Create a dynamic Role subclass
        role_attrs = {
            "role": self.role_id,
            "name": self.name,
            "llm": llm_instance,
            "task_phases": self.task_phases,
            "task_phases_excluded": self.task_phases_excluded,
        }
        role = type(
            f"Dynamic{self.name}Role",
            (Role,),
            role_attrs,
        )

        return role(persona=persona)


class AgentSpec(BaseModel):
    """Configuration for one agent in an experiment.

    Optionally attach a persona via ``persona_id``, which references a persona
    declared in the experiment's top-level ``personas`` list.

    For file-based or bundled-by-id persona resolution, use the code-driven
    entry point with :func:`econagents.personas.load_persona`.
    """

    id: int
    role_id: int
    persona_id: Optional[str] = None


class StateFieldSpec(BaseModel):
    """Configuration for a field in the state."""

    name: str
    type: str
    default: Any = None
    default_factory: Optional[str] = None
    event_key: Optional[str] = None
    exclude_from_mapping: bool = False
    optional: bool = False
    events: Optional[List[str]] = None
    exclude_events: Optional[List[str]] = None


class StateSpec(BaseModel):
    """Configuration for a game state."""

    meta_information: List[StateFieldSpec] = Field(default_factory=list)
    private_information: List[StateFieldSpec] = Field(default_factory=list)
    public_information: List[StateFieldSpec] = Field(default_factory=list)

    def create_state_class(self) -> Type[GameState]:
        """Create a GameState subclass from this configuration using create_model."""

        def resolve_field_type(field_type_str: str) -> Any:
            """Resolve type string to Python type."""
            if field_type_str in TYPE_MAPPING:
                return TYPE_MAPPING[field_type_str]
            else:
                try:
                    resolved_type = eval(field_type_str, {"list": list, "dict": dict, "Any": Any})
                    return resolved_type
                except (NameError, SyntaxError):
                    raise ValueError(f"Unsupported field type: {field_type_str}")

        def get_default_factory(factory_name: str) -> Any:
            """Get default factory function."""
            if factory_name == "list":
                return list
            elif factory_name == "dict":
                return dict
            else:
                raise ValueError(f"Unsupported default_factory: {factory_name}")

        def create_fields_dict(field_configs: List[StateFieldSpec]) -> Dict[str, Any]:
            """Create a dictionary of field definitions for create_model."""
            fields = {}
            for field in field_configs:
                base_type = resolve_field_type(field.type)
                field_type = Optional[base_type] if field.optional else base_type

                event_field_args = {
                    "event_key": field.event_key,
                    "exclude_from_mapping": field.exclude_from_mapping,
                    "events": field.events,
                    "exclude_events": field.exclude_events,
                }
                # Handle default vs default_factory
                if field.default_factory:
                    event_field_args["default_factory"] = get_default_factory(field.default_factory)
                else:
                    # Pydantic handles Optional defaults correctly (None if optional and no default)
                    event_field_args["default"] = field.default

                # EventField needs to be the default value passed to create_model
                field_definition = EventField(**event_field_args)  # type: ignore
                fields[field.name] = (field_type, field_definition)
            return fields

        # Create dynamic classes using create_model
        meta_fields = create_fields_dict(self.meta_information)
        DynamicMeta = create_model(
            "DynamicMeta",
            __base__=MetaInformation,
            **meta_fields,
        )

        private_fields = create_fields_dict(self.private_information)
        DynamicPrivate = create_model(
            "DynamicPrivate",
            __base__=PrivateInformation,
            **private_fields,
        )

        public_fields = create_fields_dict(self.public_information)
        DynamicPublic = create_model(
            "DynamicPublic",
            __base__=PublicInformation,
            **public_fields,
        )

        # Create the final game state class
        DynamicGameState = create_model(
            "DynamicGameState",
            __base__=GameState,
            meta=(DynamicMeta, Field(default_factory=DynamicMeta)),
            private_information=(DynamicPrivate, Field(default_factory=DynamicPrivate)),
            public_information=(DynamicPublic, Field(default_factory=DynamicPublic)),
        )

        # Cast to Type[GameState] for type hinting
        return cast(Type[GameState], DynamicGameState)


class RuntimeSpec(BaseModel):
    """Configuration for agents."""

    mode: Literal["turn_based", "hybrid"] = "turn_based"
    event_handlers: List[EventHandlerSpec] = Field(default_factory=list)

    def create_agent(
        self,
        game_id: int,
        state: GameState,
        role: Role,
        auth_kwargs: Dict[str, Any],
        runner_config: GameRunnerConfig,
    ) -> Agent:
        """Create a configured agent."""
        continuous_phases: set[PhaseId] = set()
        min_action_delay = None
        max_action_delay = None
        if self.mode == "hybrid":
            if not isinstance(runner_config, HybridGameRunnerConfig):
                raise ValueError("Hybrid runtime requires a HybridGameRunner config.")
            continuous_phases = set(runner_config.continuous_phases)
            min_action_delay = runner_config.min_action_delay
            max_action_delay = runner_config.max_action_delay

        if runner_config.observability_provider:
            provider = get_observability_provider(runner_config.observability_provider)
            role.llm.observability = provider

        agent = Agent(
            url=runner_config.server_url(),
            auth_mechanism_kwargs=auth_kwargs,
            state=state,
            role=role,
            prompts_dir=runner_config.prompts_dir,
            phase_transition_event=runner_config.phase_transition_event,
            phase_identifier_key=runner_config.phase_identifier_key,
            phase_engine=PhaseEngine(
                continuous_phases=continuous_phases,
                min_action_delay=min_action_delay,
                max_action_delay=max_action_delay,
            ),
            auth_mechanism=runner_config.auth_mechanism,
            end_game_event=runner_config.end_game_event,
        )
        agent.state.meta.game_id = game_id

        for handler in self.event_handlers:

            async def create_handler(event, handler=handler):
                if handler.custom_code:
                    local_vars = {"agent": agent, "event": event}
                    exec(handler.custom_code, globals(), local_vars)

                if handler.custom_module and handler.custom_function:
                    try:
                        module = importlib.import_module(handler.custom_module)
                        func = getattr(module, handler.custom_function)
                        await func(agent, event)
                    except (ImportError, AttributeError) as e:
                        agent.logger.error(f"Error importing custom handler: {e}")

            agent.register_event_handler(handler.event, create_handler)

        return agent


class RunnerSpec(BaseModel):
    """Configuration for a game runner."""

    type: str = "GameRunner"
    protocol: str = "ws"
    hostname: str
    path: str = "wss"
    port: int
    game_id: int
    logs_dir: str = "logs"
    log_level: str = "INFO"
    prompts_dir: str = "prompts"
    phase_transition_event: str = "phase-transition"
    phase_identifier_key: str = "phase"
    observability_provider: Optional[Literal["langsmith", "langfuse"]] = None

    # For hybrid game runners
    continuous_phases: List[PhaseId] = Field(default_factory=list)
    min_action_delay: int = 5
    max_action_delay: int = 10

    def create_runner_config(self) -> GameRunnerConfig:
        """Create a GameRunnerConfig instance from this configuration."""
        # Map string log level to int
        log_levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }

        log_level_int = log_levels.get(self.log_level.upper(), logging.INFO)

        # Base arguments for constructor - explicitly defining each parameter
        if self.type == "TurnBasedGameRunner":
            return TurnBasedGameRunnerConfig(
                protocol=self.protocol,
                hostname=self.hostname,
                path=self.path,
                port=self.port,
                game_id=self.game_id,
                logs_dir=Path.cwd() / self.logs_dir,
                log_level=log_level_int,
                prompts_dir=Path.cwd() / self.prompts_dir,
                phase_transition_event=self.phase_transition_event,
                phase_identifier_key=self.phase_identifier_key,
                observability_provider=self.observability_provider,
            )
        elif self.type == "HybridGameRunner":
            return HybridGameRunnerConfig(
                protocol=self.protocol,
                hostname=self.hostname,
                path=self.path,
                port=self.port,
                game_id=self.game_id,
                logs_dir=Path.cwd() / self.logs_dir,
                log_level=log_level_int,
                prompts_dir=Path.cwd() / self.prompts_dir,
                phase_transition_event=self.phase_transition_event,
                phase_identifier_key=self.phase_identifier_key,
                observability_provider=self.observability_provider,
                continuous_phases=self.continuous_phases,
                min_action_delay=self.min_action_delay,
                max_action_delay=self.max_action_delay,
            )
        else:
            raise ValueError(f"Invalid runner type: {self.type}")


class ExperimentSpec(BaseModel):
    """Configuration for an entire experiment."""

    name: str
    description: str = ""
    prompt_partials: List[Dict[str, str]] = Field(default_factory=list)
    roles: List[RoleSpec] = Field(default_factory=list)
    personas: List[Persona] = Field(default_factory=list)
    agents: List[AgentSpec] = Field(default_factory=list)
    state: StateSpec
    runtime: RuntimeSpec
    runner: RunnerSpec
    _temp_prompts_dir: Optional[Path] = None

    @model_validator(mode="after")
    def _check_personas_and_references(self) -> "ExperimentSpec":
        # Reject duplicate ids in the top-level personas list.
        seen: set[str] = set()
        for persona in self.personas:
            if persona.id in seen:
                raise ValueError(f"Duplicate persona id in 'personas' list: '{persona.id}'.")
            seen.add(persona.id)
        # Every persona_id on an agent mapping must resolve to a top-level persona.
        for agent in self.agents:
            if agent.persona_id is not None and agent.persona_id not in seen:
                raise ValueError(
                    f"Agent {agent.id} references persona_id '{agent.persona_id}', "
                    "which is not declared in the top-level 'personas' list."
                )
        return self

    def _compile_inline_prompts(self) -> Path:
        """Compile prompts from config into a temporary directory.

        Returns:
            Path to the temporary directory containing compiled prompts
        """
        # Create a temporary directory for prompts
        temp_dir = Path(tempfile.mkdtemp(prefix="econagents_prompts_"))
        self._temp_prompts_dir = temp_dir

        # Create _partials directory
        partials_dir = temp_dir / "_partials"
        partials_dir.mkdir(parents=True, exist_ok=True)

        # Write prompt partials
        for partial in self.prompt_partials:
            partial_file = partials_dir / f"{partial['name']}.jinja2"
            partial_file.write_text(partial["content"])

        # Write prompts for each role
        for role in self.roles:
            if not hasattr(role, "prompts") or not role.prompts:
                continue

            for prompt in role.prompts:
                # Each prompt should be a dict with one key (type) and one value (content)
                for prompt_type, content in prompt.items():
                    # Parse the prompt type to get the base type and phase
                    parts = prompt_type.split("_phase_")
                    base_type = parts[0]  # system or user
                    phase = parts[1] if len(parts) > 1 else None

                    # Create the prompt file name
                    if phase:
                        file_name = f"{role.name.lower()}_{base_type}_phase_{phase}.jinja2"
                    else:
                        file_name = f"{role.name.lower()}_{base_type}.jinja2"

                    # Write the prompt file
                    prompt_file = temp_dir / file_name
                    prompt_file.write_text(content)

        return temp_dir

    async def run_experiment(self, login_payloads: List[Dict[str, Any]], game_id: int) -> None:
        """Run the experiment from this configuration."""
        state_type = self.state.create_state_class()
        role_configs = {role_config.role_id: role_config for role_config in self.roles}
        runner_config = self.runner.create_runner_config()
        runner_config.game_id = game_id

        if any(hasattr(role, "prompts") and role.prompts for role in self.roles):
            prompts_dir = self._compile_inline_prompts()
            runner_config.prompts_dir = prompts_dir

        if not self.roles and self.agents:
            raise ValueError("Configuration has 'agents' but no 'roles'. Cannot determine role configurations.")

        agent_mappings = {agent_map.id: agent_map for agent_map in self.agents}
        personas_by_id = {persona.id: persona for persona in self.personas}

        agents = []
        for payload in login_payloads:
            agent_id = payload.get("agent_id")
            if agent_id is None:
                raise ValueError(f"Login payload missing 'agent_id' field: {payload}")

            mapping = agent_mappings.get(agent_id)
            if mapping is None:
                raise ValueError(f"No role_id mapping found for agent {agent_id}")

            role_id = mapping.role_id
            if role_id not in role_configs:
                raise ValueError(f"No role configuration found for role_id {role_id}")

            resolved_persona = personas_by_id[mapping.persona_id] if mapping.persona_id else None
            role_instance = role_configs[role_id].create_role(persona=resolved_persona)

            agents.append(
                self.runtime.create_agent(
                    game_id=game_id,
                    state=create_game_state(state_type, game_id=game_id),
                    role=role_instance,
                    auth_kwargs=payload,
                    runner_config=runner_config,
                )
            )

        runner = GameRunner(config=runner_config, agents=agents)
        await runner.run_game()

        if self._temp_prompts_dir and self._temp_prompts_dir.exists():
            import shutil

            shutil.rmtree(self._temp_prompts_dir)


class YamlExperimentLoader:
    """Load and run an experiment specification from YAML."""

    def __init__(self, config_path: Path):
        """
        Initialize the loader with a path to a YAML configuration file.

        Args:
            config_path: Path to the YAML configuration file
        """
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self) -> ExperimentSpec:
        """Load the experiment configuration from the YAML file."""
        with open(self.config_path, "r") as file:
            config_data = yaml.safe_load(file)

        return ExperimentSpec(**config_data)

    async def run_experiment(self, login_payloads: List[Dict[str, Any]], game_id: int) -> None:
        """
        Run the experiment from this configuration.

        Args:
            login_payloads: A list of dictionaries containing login information for each agent
        """
        await self.config.run_experiment(login_payloads, game_id)


async def run_experiment_from_yaml(yaml_path: Path, login_payloads: List[Dict[str, Any]], game_id: int) -> None:
    """Run an experiment from a YAML configuration file."""
    parser = YamlExperimentLoader(yaml_path)
    await parser.run_experiment(login_payloads, game_id)
