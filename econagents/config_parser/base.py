import importlib
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type, cast
from datetime import datetime, date, time

import yaml
from pydantic import BaseModel, Field, create_model

from econagents.core.game_runner import GameRunner, GameRunnerConfig, HybridGameRunnerConfig, TurnBasedGameRunnerConfig
from econagents.core.manager.phase import PhaseManager, TurnBasedPhaseManager, HybridPhaseManager
from econagents.core.state.fields import EventField
from econagents.core.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.core.state.market import MarketState
from econagents.core.agent_role import AgentRole

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
    "MarketState": MarketState,
}


class EventHandler(BaseModel):
    """Configuration for an event handler."""

    event: str
    custom_code: Optional[str] = None
    custom_module: Optional[str] = None
    custom_function: Optional[str] = None


class AgentRoleConfig(BaseModel):
    """Configuration for an agent role."""

    role_id: int
    name: str
    llm_type: str = "ChatOpenAI"
    llm_params: Dict[str, Any] = Field(default_factory=dict)
    prompts: List[Dict[str, str]] = Field(default_factory=list)
    task_phases: List[int] = Field(default_factory=list)
    task_phases_excluded: List[int] = Field(default_factory=list)

    def create_agent_role(self) -> AgentRole:
        """Create an AgentRole instance from this configuration."""
        # Dynamically create the LLM provider
        llm_class = getattr(importlib.import_module("econagents.llm"), self.llm_type)
        llm_instance = llm_class(**self.llm_params)

        # Create a dynamic AgentRole subclass
        agent_role_attrs = {
            "role": self.role_id,
            "name": self.name,
            "llm": llm_instance,
            "task_phases": self.task_phases,
            "task_phases_excluded": self.task_phases_excluded,
        }
        agent_role = type(
            f"Dynamic{self.name}Role",
            (AgentRole,),
            agent_role_attrs,
        )

        return agent_role()


class AgentMappingConfig(BaseModel):
    """Configuration mapping agent IDs to role IDs."""

    id: int
    role_id: int


class AgentConfig(BaseModel):
    """Configuration for an agent role."""

    role_id: int
    name: str
    llm_type: str = "ChatOpenAI"
    llm_params: Dict[str, Any] = Field(default_factory=dict)

    def create_agent_role(self) -> AgentRole:
        """Create an AgentRole instance from this configuration."""
        # Dynamically create the LLM provider
        llm_class = getattr(importlib.import_module("econagents.llm"), self.llm_type)
        llm_instance = llm_class(**self.llm_params)

        # Create a dynamic AgentRole subclass
        agent_role = type(
            f"Dynamic{self.name}Role", (AgentRole,), {"role": self.role_id, "name": self.name, "llm": llm_instance}
        )

        return agent_role()


class StateFieldConfig(BaseModel):
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


class StateConfig(BaseModel):
    """Configuration for a game state."""

    meta_information: List[StateFieldConfig] = Field(default_factory=list)
    private_information: List[StateFieldConfig] = Field(default_factory=list)
    public_information: List[StateFieldConfig] = Field(default_factory=list)

    def create_state_class(self) -> Type[GameState]:
        """Create a GameState subclass from this configuration using create_model."""

        def resolve_field_type(field_type_str: str) -> Any:
            """Resolve type string to Python type."""
            if field_type_str in TYPE_MAPPING:
                return TYPE_MAPPING[field_type_str]
            else:
                try:
                    resolved_type = eval(
                        field_type_str, {"list": list, "dict": dict, "Any": Any, "MarketState": MarketState}
                    )
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
                try:
                    return eval(factory_name, {"MarketState": MarketState})
                except (NameError, SyntaxError):
                    raise ValueError(f"Unsupported default_factory: {factory_name}")

        def create_fields_dict(field_configs: List[StateFieldConfig]) -> Dict[str, Any]:
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


class ManagerConfig(BaseModel):
    """Configuration for a manager."""

    type: str = "TurnBasedPhaseManager"
    event_handlers: List[EventHandler] = Field(default_factory=list)

    def create_manager(
        self, game_id: int, state: GameState, agent_role: Optional[AgentRole], auth_kwargs: Dict[str, Any]
    ) -> PhaseManager:
        """Create a PhaseManager instance from this configuration."""

        manager_class: Type[PhaseManager]

        if self.type == "TurnBasedPhaseManager":
            manager_class = TurnBasedPhaseManager
        elif self.type == "HybridPhaseManager":
            manager_class = HybridPhaseManager
        else:
            raise ValueError(f"Invalid manager type: {self.type}")

        # Create the manager instance
        manager = manager_class(
            auth_mechanism_kwargs=auth_kwargs,
            state=state,
            agent_role=agent_role,
        )

        # Set Game ID
        if hasattr(manager, "game_id"):
            setattr(manager, "game_id", game_id)

        # Register event handlers
        for handler in self.event_handlers:
            # Create a handler function based on the configuration
            async def create_handler(message, handler=handler):
                # Execute custom code if specified
                if handler.custom_code:
                    # Use exec to run the custom code with access to manager and message
                    local_vars = {"manager": manager, "message": message}
                    exec(handler.custom_code, globals(), local_vars)

                # Import and execute custom function if specified
                if handler.custom_module and handler.custom_function:
                    try:
                        module = importlib.import_module(handler.custom_module)
                        func = getattr(module, handler.custom_function)
                        await func(manager, message)
                    except (ImportError, AttributeError) as e:
                        manager.logger.error(f"Error importing custom handler: {e}")

            # Register the handler
            manager.register_event_handler(handler.event, create_handler)

        return manager


class RunnerConfig(BaseModel):
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
    continuous_phases: List[int] = Field(default_factory=list)
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
                state_class=None,
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


class ExperimentConfig(BaseModel):
    """Configuration for an entire experiment."""

    name: str
    description: str = ""
    prompt_partials: List[Dict[str, str]] = Field(default_factory=list)
    agent_roles: List[AgentRoleConfig] = Field(default_factory=list)
    agents: List[AgentMappingConfig] = Field(default_factory=list)
    state: StateConfig
    manager: ManagerConfig
    runner: RunnerConfig
    _temp_prompts_dir: Optional[Path] = None

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

        # Write prompts for each agent role
        for role in self.agent_roles:
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
        # Create state class
        state_class = self.state.create_state_class()
        role_configs = {role_config.role_id: role_config for role_config in self.agent_roles}

        if not self.agent_roles and self.agents:
            raise ValueError(
                "Configuration has 'agents' but no 'agent_roles'. Cannot determine agent role configurations."
            )

        agent_to_role_map = {agent_map.id: agent_map.role_id for agent_map in self.agents}

        # Create managers for each agent
        agents = []
        for payload in login_payloads:
            agent_id = payload.get("agent_id")
            if agent_id is None:
                raise ValueError(f"Login payload missing 'agent_id' field: {payload}")

            role_id = agent_to_role_map.get(agent_id)
            if role_id is None:
                raise ValueError(f"No role_id mapping found for agent {agent_id}")

            if role_id not in role_configs:
                raise ValueError(f"No agent role configuration found for role_id {role_id}")

            agent_role_instance = role_configs[role_id].create_agent_role()

            agents.append(
                self.manager.create_manager(
                    game_id=game_id,
                    state=state_class(game_id=game_id),
                    agent_role=agent_role_instance,
                    auth_kwargs=payload,
                )
            )

        # Create runner config
        runner_config = self.runner.create_runner_config()
        runner_config.state_class = state_class
        runner_config.game_id = game_id

        # Compile inline prompts if needed
        if any(hasattr(role, "prompts") and role.prompts for role in self.agent_roles):
            prompts_dir = self._compile_inline_prompts()
            runner_config.prompts_dir = prompts_dir

        # Create and run game runner
        runner = GameRunner(config=runner_config, agents=agents)
        await runner.run_game()

        # Clean up temporary prompts directory
        if self._temp_prompts_dir and self._temp_prompts_dir.exists():
            import shutil

            shutil.rmtree(self._temp_prompts_dir)


class BaseConfigParser:
    """Base configuration parser with no custom event handlers."""

    def __init__(self, config_path: Path):
        """
        Initialize the config parser with a path to a YAML configuration file.

        Args:
            config_path: Path to the YAML configuration file
        """
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self) -> ExperimentConfig:
        """Load the experiment configuration from the YAML file."""
        with open(self.config_path, "r") as file:
            config_data = yaml.safe_load(file)

        # Handle backward compatibility with old format
        if not config_data.get("agent_roles") and "agents" in config_data:
            # Check if the agents field contains role configurations
            if config_data["agents"] and "name" in config_data["agents"][0]:
                # Old format with agent configurations in "agents" field
                config_data["agent_roles"] = config_data.pop("agents")
                config_data["agents"] = []

        return ExperimentConfig(**config_data)

    def create_manager(
        self, game_id: int, state: GameState, agent_role: Optional[AgentRole], auth_kwargs: Dict[str, Any]
    ) -> PhaseManager:
        """
        Create a manager instance based on the configuration.
        This base implementation has no custom event handlers.

        Args:
            game_id: The game ID
            state: The game state instance
            agent_role: The agent role instance
            auth_kwargs: Authentication mechanism keyword arguments

        Returns:
            A PhaseManager instance
        """
        return self.config.manager.create_manager(
            game_id=game_id, state=state, agent_role=agent_role, auth_kwargs=auth_kwargs
        )

    async def run_experiment(self, login_payloads: List[Dict[str, Any]], game_id: int) -> None:
        """
        Run the experiment from this configuration.

        Args:
            login_payloads: A list of dictionaries containing login information for each agent
        """
        await self.config.run_experiment(login_payloads, game_id)


async def run_experiment_from_yaml(yaml_path: Path, login_payloads: List[Dict[str, Any]], game_id: int) -> None:
    """Run an experiment from a YAML configuration file."""
    parser = BaseConfigParser(yaml_path)
    await parser.run_experiment(login_payloads, game_id)
