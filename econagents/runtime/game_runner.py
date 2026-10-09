import asyncio
import logging
import queue
from contextvars import ContextVar
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from typing import Any, Literal, Optional, List

from pydantic import BaseModel, Field

from econagents.adapters.llm.observability import get_observability_provider
from econagents.adapters.protocol import INTRODUCTION_PHASE
from econagents.adapters.transport import AuthenticationMechanism, JoinPayloadAuth
from econagents.domain.messages import Event, PhaseId
from econagents.runtime.agent import Agent
from econagents.runtime.game_clock import GameClock, TimeoutReason

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
    auth_mechanism: Optional[AuthenticationMechanism] = JoinPayloadAuth()
    """Authentication mechanism to use. Defaults to the join handshake."""

    # Phase transition configuration
    phase_transition_event: str = "phase-transition"
    """Event to use for phase transitions"""
    phase_identifier_key: str = "phase"
    """Key in data to use for phase identification"""

    # Observability configuration
    observability_provider: Optional[Literal["langsmith", "langfuse"]] = None
    """Name of the observability provider to use. Options: 'langsmith' or 'langfuse'"""

    max_game_duration: int = Field(
        default=600,
        description=(
            "Maximum gameplay duration in seconds. Default is 600 (10 minutes). Only time spent in phases outside "
            "pre_game_phases counts, from the first such phase an agent reports; if no agent has reported a phase "
            "yet, it counts from the start of the run. Set to 0 or a negative value to disable the timeout."
        ),
    )
    max_pre_game_duration: Optional[float] = Field(
        default=None,
        description=(
            "Maximum time in seconds spent waiting before gameplay: before the first reported phase and in "
            "pre_game_phases, summed over the run. None (the default), 0 or a negative value means no limit."
        ),
    )
    pre_game_phases: set[PhaseId] = Field(
        default_factory=lambda: {INTRODUCTION_PHASE},
        description="Phases in which the game waits for players (join and ready); they do not count as gameplay.",
    )

    # Agent stop configuration
    end_game_event: str = "game-over"
    """Event type that signals the end of the game and should stop the agent."""

    def server_url(self) -> str:
        """Build the WebSocket URL for agents."""
        base = f"{self.protocol}://{self.hostname}:{self.port}"
        return f"{base}/{self.path}" if self.path else base


class TurnBasedGameRunnerConfig(GameRunnerConfig):
    """Configuration class for TurnBasedGameRunner."""


class HybridGameRunnerConfig(GameRunnerConfig):
    """Configuration class for TurnBasedGameRunner."""

    continuous_phases: list[PhaseId] = Field(default_factory=list)
    min_action_delay: int = Field(default=5)
    max_action_delay: int = Field(default=10)


class GameRunner:
    def __init__(
        self,
        config: GameRunnerConfig,
        agents: list[Agent],
    ):
        """
        Generic game runner for managing agent connections to a game server. This can handle both turn-based and continuous games.

        This class handles:

        - Agent spawning and connection management

        - Logging setup for game and agents

        Args:
            config: GameRunnerConfig instance with server and path settings
            agents: Agents to supervise
        """
        self.config = config
        self.agents = agents
        self.game_log_queues: dict[int, queue.Queue] = {}
        self.game_log_listeners: dict[int, QueueListener] = {}
        self.timeout_reason: Optional[TimeoutReason] = None
        """Which budget stopped the last run: ``"gameplay"``, ``"pre_game"``, or None if none did."""
        self._clock: Optional[GameClock] = None

        # Create log directories if it doesn't exist
        if self.config.logs_dir:
            self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        self._configure_observability()
        self._observe_agent_phases()

    def _observe_agent_phases(self) -> None:
        """Feed each agent's phase events into the game clock.

        Agents without ``register_event_handler`` report nothing; if none reports a phase, the gameplay
        budget counts from the start of the run.
        """
        for agent in self.agents:
            register = getattr(agent, "register_event_handler", None)
            if register is None:
                continue
            event_type = getattr(agent, "phase_transition_event", self.config.phase_transition_event)
            phase_key = getattr(agent, "phase_identifier_key", self.config.phase_identifier_key)

            def observe(event: Event, agent: Agent = agent, phase_key: str = phase_key) -> None:
                if self._clock is not None:
                    self._clock.observe(self._event_round(agent, event), event.data.get(phase_key))

            register(event_type, observe)

    @staticmethod
    def _event_round(agent: Agent, event: Event) -> Any:
        meta_round = getattr(getattr(getattr(agent, "state", None), "meta", None), "round", None)
        return meta_round if meta_round is not None else event.data.get("round")

    def _configure_observability(self) -> None:
        """Attach the configured observability provider to each agent LLM."""
        if not self.config.observability_provider:
            return

        provider = get_observability_provider(self.config.observability_provider)
        for agent in self.agents:
            llm = getattr(getattr(agent, "role", None), "llm", None)
            if llm is not None:
                llm.observability = provider

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

        # Create or clear the agent log file; concurrent agent processes may
        # share this path, so tolerate another process removing it first.
        agent_log_file.unlink(missing_ok=True)
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

    def _inject_agent_logger(self, agent: Agent, agent_id: int) -> None:
        """
        Assign a logger to an agent.

        Args:
            agent: Agent to assign a logger to
            agent_id (int): Agent identifier
        """
        agent_logger = self.get_agent_logger(agent_id, self.config.game_id)
        agent.logger = agent_logger
        transport = getattr(agent, "transport", None)
        if transport is not None and hasattr(transport, "logger"):
            transport.logger = agent_logger

    async def spawn_agent(self, agent: Agent, agent_id: int) -> None:
        """
        Spawn an agent and connect it to the game.

        Args:
            agent: Agent to spawn
            agent_id (int): Agent identifier
        """
        token = ctx_agent_id.set(str(agent_id))
        try:
            self._inject_agent_logger(agent, agent_id)

            agent.logger.info(f"Starting agent for URL: {agent.url}")
            await agent.start()
        except asyncio.CancelledError:
            agent.logger.info(f"Agent {agent_id} spawn_agent task was cancelled.")
            raise
        except Exception:
            agent.logger.exception(f"Error in game for Agent {agent_id}")
            raise
        finally:
            agent.logger.info(f"Agent {agent_id} spawn_agent task finished. Agent running state: {agent.running}")
            ctx_agent_id.reset(token)

    async def _timeout_watchdog(
        self, clock: GameClock, game_logger: logging.Logger, agent_tasks: List[asyncio.Task]
    ) -> None:
        """
        Timeout watchdog that stops the agents once the gameplay or pre-game budget is used up.

        Args:
            clock: Game clock that tracks both budgets
            game_logger: Logger instance for the game
            agent_tasks: List of agent tasks to cancel if timeout occurs
        """
        try:
            self.timeout_reason = await clock.wait_for_timeout()
            game_logger.warning(self._timeout_message(clock))

            stop_agent_tasks = []
            for idx, agent in enumerate(self.agents):
                if agent.running:
                    game_logger.info(f"Timeout: Stopping agent {idx + 1} for game {self.config.game_id}.")
                    stop_agent_tasks.append(
                        asyncio.create_task(agent.stop(), name=f"TimeoutStopAgent-{self.config.game_id}-{idx + 1}")
                    )
            if stop_agent_tasks:
                await asyncio.gather(*stop_agent_tasks, return_exceptions=True)

            game_logger.info(f"Timeout: Checking for lingering agent tasks for game {self.config.game_id}.")
            for agent_task_instance in agent_tasks:
                if not agent_task_instance.done():
                    game_logger.warning(
                        f"Timeout: Agent task {agent_task_instance.get_name()} still running. Cancelling."
                    )
                    agent_task_instance.cancel()
                    # Await the cancellation to ensure it's processed
                    try:
                        await agent_task_instance
                    except asyncio.CancelledError:
                        game_logger.info(f"Agent task {agent_task_instance.get_name()} cancelled by timeout watchdog.")
                    except Exception as e_cancel:
                        game_logger.error(
                            f"Error awaiting cancelled agent task {agent_task_instance.get_name()}: {e_cancel}"
                        )

        except asyncio.CancelledError:
            game_logger.info(f"Timeout watchdog for game {self.config.game_id} was cancelled.")
            raise
        except Exception as e_watchdog:
            game_logger.exception(f"Error in timeout watchdog for game {self.config.game_id}: {e_watchdog}")

    async def run_game(self) -> None:
        """Run a game using provided game data."""

        game_logger = self.get_game_logger(self.config.game_id)
        pre_game_wait = self.config.max_pre_game_duration
        game_logger.info(
            f"Running game with ID: {self.config.game_id}. Max gameplay duration: {self.config.max_game_duration}s, "
            f"max pre-game wait: {f'{pre_game_wait}s' if pre_game_wait and pre_game_wait > 0 else 'unlimited'}"
        )

        agent_tasks: List[asyncio.Task] = []
        timeout_monitor_task: Optional[asyncio.Task] = None
        self.timeout_reason = None
        clock = GameClock(
            max_game_duration=self.config.max_game_duration,
            max_pre_game_duration=self.config.max_pre_game_duration,
            pre_game_phases=self.config.pre_game_phases,
            logger=game_logger,
        )
        self._clock = clock

        try:
            game_logger.info("Configuring and starting agents...")
            for i, agent in enumerate(self.agents, start=1):
                task = asyncio.create_task(self.spawn_agent(agent, i), name=f"AgentTask-{self.config.game_id}-{i}")
                agent_tasks.append(task)

            if clock.enabled:
                timeout_monitor_task = asyncio.create_task(
                    self._timeout_watchdog(clock, game_logger, agent_tasks),
                    name=f"TimeoutWatchdog-{self.config.game_id}",
                )

            if agent_tasks:
                results = await asyncio.gather(*agent_tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        game_logger.error(f"Agent task {agent_tasks[i].get_name()} failed with: {result}")
            else:
                game_logger.debug("No agent tasks to run.")

        except Exception as e_run_game:
            game_logger.exception(f"GameRunner.run_game failed: {e_run_game}")
            raise
        finally:
            if timeout_monitor_task and not timeout_monitor_task.done():
                game_logger.debug(
                    f"Game {self.config.game_id} finished or errored before timeout. Cancelling timeout watchdog."
                )
                timeout_monitor_task.cancel()

            game_logger.info(f"Game {self.config.game_id}: Final cleanup - ensuring all agents are stopped.")
            final_stop_tasks = []
            for idx, agent in enumerate(self.agents):
                if agent.running:
                    game_logger.info(f"Final cleanup: Stopping agent {idx + 1} for game {self.config.game_id}.")
                    final_stop_tasks.append(
                        asyncio.create_task(agent.stop(), name=f"FinalStopAgent-{self.config.game_id}-{idx + 1}")
                    )

            if final_stop_tasks:
                await asyncio.gather(*final_stop_tasks, return_exceptions=True)
                game_logger.info(f"Game {self.config.game_id}: Final agent stop tasks completed.")

            self._clock = None
            self.cleanup_logging()
            game_logger.info(f"Game {self.config.game_id} finished and cleaned up.")

    def _timeout_message(self, clock: GameClock) -> str:
        game_id = self.config.game_id
        if self.timeout_reason == "pre_game":
            where = "before any phase was reported" if clock.phase is None else f"in phase {clock.phase}"
            return (
                f"Game {game_id}: pre-game wait timeout after {clock.pre_game_budget}s (max_pre_game_duration), "
                f"{where}. Initiating shutdown."
            )
        if clock.gameplay_start_phase is None:
            return (
                f"Game {game_id} reached maximum duration of {clock.gameplay_budget}s, counted from the start of the "
                "run because no agent reported a phase. Initiating shutdown."
            )
        return (
            f"Game {game_id} reached maximum duration of {clock.gameplay_budget}s of gameplay, counted from phase "
            f"{clock.gameplay_start_phase}. Initiating shutdown."
        )
