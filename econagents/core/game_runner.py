import asyncio
import logging
import queue
from contextvars import ContextVar
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from typing import Literal, Optional, Type

from pydantic import BaseModel, Field

from econagents.core.manager.phase import PhaseManager
from econagents.core.state.game import GameState
from econagents.core.transport import AuthenticationMechanism, SimpleLoginPayloadAuth
from econagents.llm.observability import get_observability_provider

ctx_agent_id: ContextVar[str] = ContextVar("agent_id", default="N/A")


class ContextInjectingFilter(logging.Filter):
    """Filter that injects agent_id context into log records."""

    def filter(self, record):
        record.agent_id = ctx_agent_id.get()
        return True


class GameRunnerConfig(BaseModel):
    """Configuration class for GameRunner."""

    # Server configuration
    protocol: str = "ws"
    """Protocol to use for the server"""
    hostname: str
    """Hostname of the server"""
    path: str
    """Path to the server"""
    port: int

    # Game configuration
    game_id: int
    """ID of the game"""
    logs_dir: Path = Path.cwd() / "logs"
    """Directory to store logs"""
    log_level: int = logging.INFO
    """Level of logging to use"""
    prompts_dir: Path = Path.cwd() / "prompts"

    # Authentication
    auth_mechanism: Optional[AuthenticationMechanism] = SimpleLoginPayloadAuth()
    """Authentication mechanism to use"""

    # Phase transition configuration
    phase_transition_event: str = "phase-transition"
    """Event to use for phase transitions"""
    phase_identifier_key: str = "phase"
    """Key in data to use for phase identification"""

    # State configuration
    state_class: Optional[Type[GameState]] = None
    """Class to use for the state"""

    # Observability configuration
    observability_provider: Optional[Literal["langsmith", "langfuse"]] = None
    """Name of the observability provider to use. Options: 'langsmith' or 'langfuse'"""

    # Agent stop configuration
    end_game_event: str = "game-over"
    """Event type that signals the end of the game and should stop the agent."""


class TurnBasedGameRunnerConfig(GameRunnerConfig):
    """Configuration class for TurnBasedGameRunner."""


class HybridGameRunnerConfig(GameRunnerConfig):
    """Configuration class for TurnBasedGameRunner."""

    continuous_phases: list[int] = Field(default_factory=list)
    min_action_delay: int = Field(default=5)
    max_action_delay: int = Field(default=10)


class GameRunner:
    def __init__(
        self,
        config: GameRunnerConfig,
        agents: list[PhaseManager],
    ):
        """
        Generic game runner for managing agent connections to a game server. This can handle both turn-based and continuous games.

        This class handles:

        - Agent spawning and connection management

        - Logging setup for game and agents

        Args:
            config: GameRunnerConfig instance with server and path settings
            agents: List of AgentManager instances
        """
        self.config = config
        self.agents = agents
        self.game_log_queues: dict[int, queue.Queue] = {}
        self.game_log_listeners: dict[int, QueueListener] = {}

        # Create log directories if it doesn't exist
        if self.config.logs_dir:
            self.config.logs_dir.mkdir(parents=True, exist_ok=True)

    def _setup_game_log_queue(self, game_id: int) -> queue.Queue:
        """
        Set up a logging queue for a game and its associated QueueListener.

        Args:
            game_id: Game identifier

        Returns:
            Queue used for logging
        """
        if game_id in self.game_log_queues:
            return self.game_log_queues[game_id]

        if not self.config.logs_dir:
            # If no log path, just return a queue without a listener
            log_queue: queue.Queue = queue.Queue()
            self.game_log_queues[game_id] = log_queue
            return log_queue

        # Create a game-specific directory for all logs related to this game
        game_dir = self.config.logs_dir / f"game_{game_id}"
        game_dir.mkdir(parents=True, exist_ok=True)

        game_log_file = game_dir / "all.log"
        Path(game_log_file).touch()

        game_queue: queue.Queue = queue.Queue()
        self.game_log_queues[game_id] = game_queue

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] [AGENT %(agent_id)s] %(message)s")

        # Create a file handler for the game log
        file_handler = logging.FileHandler(game_log_file)
        file_handler.setFormatter(formatter)

        # Create and start the listener
        listener = QueueListener(game_queue, file_handler)
        listener.start()
        self.game_log_listeners[game_id] = listener

        return game_queue

    def get_agent_logger(self, agent_id: int, game_id: int) -> logging.Logger:
        """
        Configure and return a logger for an agent.

        Args:
            agent_id (int): Agent identifier
            game_id (int): Game identifier

        Returns:
            logging.Logger: Configured logger instance
        """
        if not self.config.logs_dir:
            # Return a default logger if no log path is configured
            logger = logging.getLogger(f"agent_{agent_id}")
            logger.setLevel(self.config.log_level)
            return logger

        # Ensure game log queue is set up
        game_log_queue = self._setup_game_log_queue(game_id)

        # Create a game-specific directory for all logs
        game_dir = self.config.logs_dir / f"game_{game_id}"
        game_dir.mkdir(parents=True, exist_ok=True)

        # Store agent logs in the game-specific directory
        agent_log_file = game_dir / f"agent_{agent_id}.log"

        agent_logger = logging.getLogger(f"agent_{agent_id}")
        agent_logger.setLevel(self.config.log_level)

        # Clear existing handlers to avoid duplicates
        for handler in agent_logger.handlers[:]:
            agent_logger.removeHandler(handler)

        # Create or clear the agent log file
        if agent_log_file.exists():
            agent_log_file.unlink()
        Path(agent_log_file).touch()

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] [AGENT %(agent_id)s] %(message)s")

        # Setup file handler for agent log
        file_handler = logging.FileHandler(agent_log_file)
        file_handler.setFormatter(formatter)

        # Add context filter
        context_filter = ContextInjectingFilter()
        file_handler.addFilter(context_filter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(context_filter)

        # Setup queue handler for game log
        queue_handler = QueueHandler(game_log_queue)
        queue_handler.addFilter(context_filter)

        # Add all handlers
        agent_logger.addHandler(file_handler)
        agent_logger.addHandler(console_handler)
        agent_logger.addHandler(queue_handler)  # Use queue handler instead of direct file handler

        return agent_logger

    def get_game_logger(self, game_id: int) -> logging.Logger:
        """
        Configure and return a logger for a game.

        Args:
            game_id (int): Game identifier

        Returns:
            logging.Logger: Configured logger instance
        """
        if not self.config.logs_dir:
            # Return a default logger if no log path is configured
            logger = logging.getLogger(f"game_{game_id}")
            logger.setLevel(self.config.log_level)
            return logger

        # Ensure game log queue is set up
        game_log_queue = self._setup_game_log_queue(game_id)

        game_logger = logging.getLogger(f"game_{game_id}")
        game_logger.setLevel(self.config.log_level)

        # Clear existing handlers to avoid duplicates
        for handler in game_logger.handlers[:]:
            game_logger.removeHandler(handler)

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        # Add context filter
        context_filter = ContextInjectingFilter()

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(context_filter)

        # Setup queue handler for game log
        queue_handler = QueueHandler(game_log_queue)

        # Add handlers
        game_logger.addHandler(console_handler)
        game_logger.addHandler(queue_handler)

        return game_logger

    def cleanup_logging(self) -> None:
        """
        Clean up logging resources, stopping all queue listeners.
        Should be called when shutting down the game runner.
        """
        for game_id, listener in self.game_log_listeners.items():
            try:
                listener.stop()
            except Exception as e:
                print(f"Error stopping listener for game {game_id}: {e}")

        self.game_log_listeners.clear()
        self.game_log_queues.clear()

    def _inject_default_config(self, agent_manager: PhaseManager) -> None:
        """
        Inject default configuration into an agent manager.

        Args:
            agent_manager (PhaseManager): Agent manager to inject configuration into
        """
        if not agent_manager.url:
            agent_manager.url = f"{self.config.protocol}://{self.config.hostname}:{self.config.port}/{self.config.path}"
            agent_manager.logger.debug(f"Injected default configuration into agent manager: {agent_manager.url}")

        if not agent_manager.phase_transition_event:
            agent_manager.phase_transition_event = self.config.phase_transition_event
            agent_manager.logger.debug(
                f"Injected default phase transition event: {agent_manager.phase_transition_event}"
            )

        if not agent_manager.phase_identifier_key:
            agent_manager.phase_identifier_key = self.config.phase_identifier_key
            agent_manager.logger.debug(f"Injected default phase identifier key: {agent_manager.phase_identifier_key}")

        if not agent_manager.prompts_dir:
            agent_manager.prompts_dir = self.config.prompts_dir
            agent_manager.logger.debug(f"Injected default prompts directory: {agent_manager.prompts_dir}")

        if not agent_manager.state and self.config.state_class:
            agent_manager.state = self.config.state_class()
            agent_manager.logger.debug(f"Injected default state: {agent_manager.state}")

        if not agent_manager.auth_mechanism:
            agent_manager.auth_mechanism = self.config.auth_mechanism
            agent_manager.logger.debug(f"Injected default auth mechanism: {agent_manager.auth_mechanism}")

        if agent_manager.end_game_event_type != self.config.end_game_event:
            agent_manager.end_game_event_type = self.config.end_game_event
            agent_manager.logger.debug(f"Injected default end game event: {agent_manager.end_game_event_type}")

        if agent_manager.llm_provider and self.config.observability_provider:
            try:
                provider = get_observability_provider(self.config.observability_provider)
                agent_manager.llm_provider.observability = provider
                agent_manager.logger.debug(
                    f"Injected {self.config.observability_provider} observability provider into LLM provider"
                )
            except Exception as e:
                agent_manager.logger.error(f"Failed to initialize observability provider: {e}")

        if isinstance(self.config, HybridGameRunnerConfig):
            agent_manager.continuous_phases = set(self.config.continuous_phases)
            agent_manager.min_action_delay = self.config.min_action_delay
            agent_manager.max_action_delay = self.config.max_action_delay
            agent_manager.logger.debug(
                f"Injected default continuous-time phases: {agent_manager.continuous_phases}, min action delay: {agent_manager.min_action_delay}, max action delay: {agent_manager.max_action_delay}"
            )

    def _inject_agent_logger(self, agent_manager: PhaseManager, agent_id: int) -> None:
        """
        Inject a logger into an agent manager.

        Args:
            agent_manager (PhaseManager): Agent manager to inject logger into
            agent_id (int): Agent identifier
        """
        agent_logger = self.get_agent_logger(agent_id, self.config.game_id)
        ctx_agent_id.set(str(agent_id))  # Convert int to str for context variable

        agent_manager.logger = agent_logger

    async def spawn_agent(self, agent_manager: PhaseManager, agent_id: int) -> None:
        """
        Spawn an agent and connect it to the game.

        Args:
            agent_manager (PhaseManager): Agent manager to spawn
            agent_id (int): Agent identifier
        """
        try:
            self._inject_agent_logger(agent_manager, agent_id)
            self._inject_default_config(agent_manager)

            agent_manager.logger.info(f"Connecting to WebSocket URL: {agent_manager.url}")
            await agent_manager.start()
        except Exception:
            agent_manager.logger.exception(f"Error in game for Agent {agent_id}")
            raise

    async def run_game(self) -> None:
        """Run a game using provided game data."""

        game_logger = self.get_game_logger(self.config.game_id)
        game_logger.info(f"Running game with ID: {self.config.game_id}")

        try:
            tasks = []
            game_logger.info("Starting game")

            for i, agent_manager in enumerate(self.agents, start=1):
                tasks.append(self.spawn_agent(agent_manager, i))
            await asyncio.gather(*tasks)
        except Exception as e:
            game_logger.exception(f"Failed to run game: {e}")
            raise
        finally:
            game_logger.info("Game over")
            self.cleanup_logging()
