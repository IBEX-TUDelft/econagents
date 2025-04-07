import asyncio
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type, Union
from datetime import datetime, date, time

import yaml
from pydantic import BaseModel, Field, create_model, validator
from pydantic_core import PydanticUndefined

from econagents import AgentRole
from econagents.core.game_runner import GameRunner, GameRunnerConfig, HybridGameRunnerConfig, TurnBasedGameRunnerConfig
from econagents.core.manager.phase import PhaseManager, TurnBasedPhaseManager
from econagents.core.state.fields import EventField
from econagents.core.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.llm import BaseLLM, ChatOpenAI

# --- Type Mapping ---
# Map type strings to Python types
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


class StateConfig(BaseModel):
    """Configuration for a game state."""

    meta_fields: List[StateFieldConfig] = Field(default_factory=list)
    private_fields: List[StateFieldConfig] = Field(default_factory=list)
    public_fields: List[StateFieldConfig] = Field(default_factory=list)

    def create_state_class(self) -> Type[GameState]:
        """Create a GameState subclass from this configuration."""

        # Function to resolve the field type using the TYPE_MAPPING
        def resolve_field_type(field_type_str: str) -> Any:
            if field_type_str in TYPE_MAPPING:
                return TYPE_MAPPING[field_type_str]
            elif field_type_str.startswith("List[") and field_type_str.endswith("]"):
                inner_type = field_type_str[5:-1]
                return List[resolve_field_type(inner_type)]  # type: ignore
            elif field_type_str.startswith("Dict[") and field_type_str.endswith("]"):
                # Simple handling for Dict[str, Any] pattern
                return Dict[str, Any]  # type: ignore
            else:
                # For complex or custom types not in mapping
                try:
                    return eval(field_type_str)
                except (NameError, SyntaxError):
                    raise ValueError(f"Unsupported field type: {field_type_str}")

        # Function to get the appropriate default factory
        def get_default_factory(factory_name: str) -> Any:
            if factory_name == "list":
                return list
            elif factory_name == "dict":
                return dict
            else:
                return eval(factory_name)

        # Create the dynamic Meta class
        class DynamicMeta(MetaInformation):
            model_config = {"arbitrary_types_allowed": True}
            pass

        # Create the dynamic Private class
        class DynamicPrivate(PrivateInformation):
            model_config = {"arbitrary_types_allowed": True}
            pass

        # Create the dynamic Public class
        class DynamicPublic(PublicInformation):
            model_config = {"arbitrary_types_allowed": True}
            pass

        # Add fields to Meta class
        for field in self.meta_fields:
            event_field = EventField(
                default=field.default if field.default_factory is None else None,
                default_factory=get_default_factory(field.default_factory) if field.default_factory else None,
                event_key=field.event_key,
                exclude_from_mapping=field.exclude_from_mapping,
            )
            setattr(DynamicMeta, field.name, event_field)

        # Add fields to Private class
        for field in self.private_fields:
            event_field = EventField(
                default=field.default if field.default_factory is None else None,
                default_factory=get_default_factory(field.default_factory) if field.default_factory else None,
                event_key=field.event_key,
                exclude_from_mapping=field.exclude_from_mapping,
            )
            setattr(DynamicPrivate, field.name, event_field)

        # Add fields to Public class
        for field in self.public_fields:
            event_field = EventField(
                default=field.default if field.default_factory is None else None,
                default_factory=get_default_factory(field.default_factory) if field.default_factory else None,
                event_key=field.event_key,
                exclude_from_mapping=field.exclude_from_mapping,
            )
            setattr(DynamicPublic, field.name, event_field)

        # Create the game state class
        class DynamicGameState(GameState):
            model_config = {"arbitrary_types_allowed": True}
            meta: DynamicMeta = Field(default_factory=DynamicMeta)
            private_information: DynamicPrivate = Field(default_factory=DynamicPrivate)
            public_information: DynamicPublic = Field(default_factory=DynamicPublic)

            def __init__(self, **kwargs: Any):
                game_id = kwargs.pop("game_id", 0)
                super().__init__(**kwargs)
                # Set game_id explicitly if the field exists
                if hasattr(self.meta, "game_id"):
                    setattr(self.meta, "game_id", game_id)

        return DynamicGameState


class ManagerConfig(BaseModel):
    """Configuration for a manager."""

    type: str = "TurnBasedPhaseManager"
    event_handlers: List[EventHandler] = Field(default_factory=list)

    def create_manager(
        self, game_id: int, state: GameState, agent_role: AgentRole, auth_kwargs: Dict[str, Any]
    ) -> PhaseManager:
        """Create a PhaseManager instance from this configuration."""
        # Determine the manager class based on type
        if self.type == "TurnBasedPhaseManager":
            manager_class = TurnBasedPhaseManager
        else:
            manager_class = getattr(importlib.import_module("econagents.core.manager.phase"), self.type)

        # Create the manager instance
        manager = manager_class(auth_mechanism_kwargs=auth_kwargs, state=state, agent_role=agent_role)

        # Safely set game_id if the manager has this attribute
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
                state_class=None,  # Default to None, will be set later
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
    agent_roles: List[AgentRoleConfig] = Field(default_factory=list)
    agents: List[AgentMappingConfig] = Field(default_factory=list)
    state: StateConfig
    manager: ManagerConfig
    runner: RunnerConfig

    async def run_experiment(self, login_payloads: List[Dict[str, Any]]) -> None:
        """Run the experiment from this configuration."""
        # Create state class and instances
        state_class = self.state.create_state_class()

        # Create agent roles from agent_roles configurations
        role_instances = {role_config.role_id: role_config.create_agent_role() for role_config in self.agent_roles}

        # If we have legacy format with agents instead of agent_roles, use those
        if not self.agent_roles and self.agents:
            raise ValueError(
                "Configuration has 'agents' but no 'agent_roles'. Cannot determine agent role configurations."
            )

        # Create a mapping from agent ID to role ID
        agent_to_role_map = {agent_map.id: agent_map.role_id for agent_map in self.agents}

        # Create managers for each agent, matching login payloads with appropriate agent roles
        # Each login payload should have an 'agent_id' field to match with the agent mapping
        agents = []
        for payload in login_payloads:
            agent_id = payload.get("agent_id")
            if agent_id is None:
                raise ValueError(f"Login payload missing 'agent_id' field: {payload}")

            role_id = agent_to_role_map.get(agent_id)
            if role_id is None:
                raise ValueError(f"No role_id mapping found for agent {agent_id}")

            if role_id not in role_instances:
                raise ValueError(f"No agent role configuration found for role_id {role_id}")

            agents.append(
                self.manager.create_manager(
                    game_id=self.runner.game_id,
                    state=state_class(game_id=self.runner.game_id),
                    agent_role=role_instances[role_id],
                    auth_kwargs=payload,
                )
            )

        # Create runner config
        runner_config = self.runner.create_runner_config()

        # Set state class in runner config
        runner_config.state_class = state_class

        # Create and run game runner
        runner = GameRunner(config=runner_config, agents=agents)
        await runner.run_game()


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
        self, game_id: int, state: GameState, agent_role: AgentRole, auth_kwargs: Dict[str, Any]
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

    async def run_experiment(self, login_payloads: List[Dict[str, Any]]) -> None:
        """
        Run the experiment from this configuration.

        Args:
            login_payloads: A list of dictionaries containing login information for each agent
        """
        # Create state class
        state_class = self.config.state.create_state_class()

        # Create agent roles from agent_roles configurations
        role_instances = {
            role_config.role_id: role_config.create_agent_role() for role_config in self.config.agent_roles
        }

        # Create a mapping from agent ID to role ID
        agent_to_role_map = {agent_map.id: agent_map.role_id for agent_map in self.config.agents}

        # Create managers for each agent
        agents = []
        for payload in login_payloads:
            agent_id = payload.get("agent_id")
            if agent_id is None:
                raise ValueError(f"Login payload missing 'agent_id' field: {payload}")

            role_id = agent_to_role_map.get(agent_id)
            if role_id is None:
                raise ValueError(f"No role_id mapping found for agent {agent_id}")

            if role_id not in role_instances:
                raise ValueError(f"No agent role configuration found for role_id {role_id}")

            state_instance = state_class(game_id=self.config.runner.game_id)

            # Use the create_manager method which can be overridden by subclasses
            agent_manager = self.create_manager(
                game_id=self.config.runner.game_id,
                state=state_instance,
                agent_role=role_instances[role_id],
                auth_kwargs=payload,
            )

            agents.append(agent_manager)

        # Create runner config
        runner_config = self.config.runner.create_runner_config()

        # Set state class in runner config
        runner_config.state_class = state_class

        # Create and run game runner
        runner = GameRunner(config=runner_config, agents=agents)
        await runner.run_game()


async def run_experiment_from_yaml(yaml_path: Path, login_payloads: List[Dict[str, Any]]) -> None:
    """Run an experiment from a YAML configuration file."""
    parser = BaseConfigParser(yaml_path)
    await parser.run_experiment(login_payloads)
