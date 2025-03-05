import asyncio
import json
import logging
import os
import queue
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from typing import Any, Callable, Optional, Type

import requests

from econagents.core.manager.base import AgentManager

# Context variable for agent_id
ctx_agent_id: ContextVar[str] = ContextVar("agent_id", default="N/A")


class ContextInjectingFilter(logging.Filter):
    """Filter that injects agent_id context into log records."""

    def filter(self, record):
        record.agent_id = ctx_agent_id.get()
        return True


class RecoveryCodeError(Exception):
    """Exception raised when failing to get recovery code."""

    pass


class GameRunnerConfig:
    """Configuration class for GameRunner."""

    def __init__(
        self,
        hostname: Optional[str] = None,
        port: Optional[str] = None,
        log_path: Optional[Path] = None,
        games_path: Optional[Path] = None,
    ):
        """
        Initialize GameRunner configuration.

        Args:
            hostname: Host address of the game server
            port: Port for the game server
            log_path: Path to store logs
            games_path: Path to game specification files
        """
        self.hostname = hostname or os.getenv("HOSTNAME")
        self.port = port or os.getenv("PORT")
        self.log_path = log_path
        self.games_path = games_path

        if not self.hostname:
            raise ValueError("Hostname must be provided or set in environment variables")


class GameRunner:
    """
    Generic game runner for managing agent connections to a game server.

    This class handles:
    - Game configuration loading/saving
    - Agent spawning and connection management
    - Logging setup for game and agents
    - Recovery code handling
    """

    def __init__(
        self,
        config: GameRunnerConfig,
        agent_manager_class: Type[AgentManager],
    ):
        """
        Initialize the GameRunner.

        Args:
            config: GameRunnerConfig instance with server and path settings
            agent_manager_class: The AgentManager class to use for connecting agents
        """
        self.config = config
        self.agent_manager_class = agent_manager_class
        self.game_log_queues: dict[int, queue.Queue] = {}
        self.game_log_listeners: dict[int, QueueListener] = {}

        # Create log directories if they don't exist
        if self.config.log_path:
            self.config.log_path.mkdir(parents=True, exist_ok=True)
            (self.config.log_path / "agents").mkdir(parents=True, exist_ok=True)
            (self.config.log_path / "game").mkdir(parents=True, exist_ok=True)

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

        if not self.config.log_path:
            # If no log path, just return a queue without a listener
            log_queue: queue.Queue = queue.Queue()
            self.game_log_queues[game_id] = log_queue
            return log_queue

        game_log_file = self.config.log_path / "game" / f"game_{game_id}.log"
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
            agent_id: Agent identifier
            game_id: Game identifier

        Returns:
            Configured logger instance
        """
        if not self.config.log_path:
            # Return a default logger if no log path is configured
            logger = logging.getLogger(f"agent_{agent_id}")
            logger.setLevel(logging.DEBUG)
            return logger

        # Ensure game log queue is set up
        game_log_queue = self._setup_game_log_queue(game_id)

        agent_log_file = self.config.log_path / "agents" / f"agent_{agent_id}.log"

        agent_logger = logging.getLogger(f"agent_{agent_id}")
        agent_logger.setLevel(logging.DEBUG)

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
            game_id: Game identifier

        Returns:
            Configured logger instance
        """
        if not self.config.log_path:
            # Return a default logger if no log path is configured
            logger = logging.getLogger(f"game_{game_id}")
            logger.setLevel(logging.DEBUG)
            return logger

        # Ensure game log queue is set up
        game_log_queue = self._setup_game_log_queue(game_id)

        game_logger = logging.getLogger(f"game_{game_id}")
        game_logger.setLevel(logging.DEBUG)

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

    # TODO: Should be more generic
    def get_recovery_code(self, game_id: int) -> str:
        """
        Get recovery code for a game from the server.

        Args:
            game_id: ID of the game

        Returns:
            Recovery code as a string

        Raises:
            RecoveryCodeError: If recovery code retrieval fails
        """
        url = f"http://{self.config.hostname}/api/v1/games/get-recovery"
        params = {"game_id": game_id}

        try:
            response = requests.get(url, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                return data["data"]["recovery"]

            raise RecoveryCodeError(f"Failed to get recovery code: {response.text}")
        except requests.RequestException as e:
            raise RecoveryCodeError(f"Request error while getting recovery code: {e}")

    async def spawn_agent(
        self, ws_url: str, auth_mechanism_kwargs: dict[str, Any], game_id: int, agent_id: int
    ) -> None:
        """
        Spawn an agent and connect it to the game.

        Args:
            ws_url: WebSocket URL to connect to
            login_payload: Login payload for the agent
            game_id: Game identifier
            agent_id: Agent identifier
        """
        agent_logger = self.get_agent_logger(agent_id, game_id)
        ctx_agent_id.set(str(agent_id))  # Convert int to str for context variable

        try:
            agent_logger.info(f"Connecting to WebSocket URL: {ws_url}")
            game = self.agent_manager_class(
                url=ws_url, game_id=game_id, logger=agent_logger, auth_mechanism_kwargs=auth_mechanism_kwargs
            )
            await game.start()
        except Exception:
            agent_logger.exception(f"Error in simulation for Agent {agent_id}")
            raise

    def save_game_config(self, game_config: dict[str, Any]) -> None:
        """
        Save game configuration to a file.

        Args:
            game_config: Game configuration dictionary
        """
        if not self.config.log_path:
            return

        config_path = self.config.log_path / "game" / f"game_{game_config['game_id']}.json"
        with config_path.open("w") as f:
            json.dump(game_config, f, indent=4)

    def load_game_config(self, game_id: int) -> dict[str, Any]:
        """
        Load game configuration from a file.

        Args:
            game_id: Game identifier

        Returns:
            Game configuration dictionary
        """
        if not self.config.log_path:
            raise ValueError("Log path not configured, cannot load game config")

        config_path = self.config.log_path / "game" / f"game_{game_id}.json"
        with config_path.open("r") as f:
            return json.load(f)

    def get_game_config(self, game_id: int, agents: int, game_type: str, use_config: str = "auto") -> dict[str, Any]:
        """
        Get game configuration, either from file or create a new one.

        Args:
            game_id: Game identifier
            agents: Number of agents in the game
            game_type: Type of game
            use_config: Configuration usage mode ("auto", True, False)

        Returns:
            Game configuration dictionary
        """
        config_path = None
        if self.config.log_path:
            config_path = self.config.log_path / "game" / f"game_{game_id}.json"

        if use_config == "auto":
            if config_path and config_path.exists():
                game_config = self.load_game_config(game_id)
            else:
                game_config = {"game_id": game_id, "agents": agents, "game_type": game_type, "recovery_codes": []}
                game_config["recovery_codes"] = [self.get_recovery_code(game_id) for _ in range(agents)]
                self.save_game_config(game_config)
        elif use_config:
            if config_path and config_path.exists():
                game_config = self.load_game_config(game_id)
            else:
                raise ValueError("Game config provided but no config file exists")
        else:
            game_config = {"game_id": game_id, "agents": agents, "game_type": game_type, "recovery_codes": []}
            game_config["recovery_codes"] = [self.get_recovery_code(game_id) for _ in range(agents)]
            self.save_game_config(game_config)

        return game_config

    def load_game_spec(self, game_id: int) -> dict[str, Any]:
        """
        Load a game specification from the games directory.

        Args:
            game_id: Game identifier

        Returns:
            Game specification dictionary
        """
        if not self.config.games_path:
            raise ValueError("Games path not configured, cannot load game spec")

        spec_file = self.config.games_path / f"game_{game_id}.json"
        if not spec_file.exists():
            raise ValueError(f"Game spec file not found: {spec_file}")

        with spec_file.open() as f:
            return json.load(f)

    async def spawn_agents_for_game(self, game_id: int) -> None:
        """
        Spawn agents for a game using its specification file.

        Args:
            game_id: Game identifier
        """
        game_logger = self.get_game_logger(game_id)
        game_logger.info(f"Loading spec for game {game_id}")

        try:
            game_spec = self.load_game_spec(game_id)
            game_logger.info(f"Game spec loaded: {game_spec}")

            ws_url = f"ws://{self.config.hostname}:{self.config.port}/wss"
            tasks = []
            game_logger.info("Starting simulations")

            for idx, recovery_code in enumerate(game_spec["recovery_codes"]):
                login_payload = {
                    "gameId": game_id,
                    "type": "join",
                    "recovery": recovery_code,
                }
                tasks.append(
                    self.spawn_agent(
                        ws_url=ws_url, auth_mechanism_kwargs=login_payload, game_id=game_id, agent_id=idx + 1
                    )
                )
            await asyncio.gather(*tasks)

        except Exception:
            game_logger.exception("Error in game setup")
            raise

        finally:
            game_logger.info("Game finished")

    async def create_and_run_game(
        self, specs_path: Path, game_creator_func: Callable[..., int], game_name: Optional[str] = None
    ) -> None:
        """
        Create a new game from specs and run it.

        Args:
            specs_path: Path to game specification file
            game_creator_func: Function to create game from specs, returns game_id
            game_name: Optional name for the game
        """
        if not specs_path.exists():
            raise ValueError(f"Specs file not found at: {specs_path}")

        if game_name is None:
            game_name = f"game {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        game_server_url = f"http://{self.config.hostname}"

        try:
            game_id = game_creator_func(specs_path=specs_path, base_url=game_server_url, game_name=game_name)

            game_logger = self.get_game_logger(game_id)
            game_logger.info(f"Created new game with ID: {game_id}")
            await self.spawn_agents_for_game(game_id)

        except Exception as e:
            # We need to get a logger even if game_id wasn't created
            logger = logging.getLogger("game_creation")
            logger.exception(f"Failed to create and run game: {e}")
            raise
