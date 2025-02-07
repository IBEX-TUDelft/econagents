import asyncio
import json
import logging
import os
from contextvars import ContextVar
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv

from experimental.harberger.agent_manager import AgentManager
from experimental.harberger.create_game import create_game_from_specs

load_dotenv()

HOSTNAME = os.getenv("HOSTNAME")
PORT = os.getenv("PORT")

LOG_PATH = Path(__file__).parent / "logs"
GAMES_PATH = Path(__file__).parent / "specs" / "games"

ctx_agent_id = ContextVar("agent_id", default="N/A")


class ContextInjectingFilter(logging.Filter):
    def filter(self, record):
        record.agent_id = ctx_agent_id.get()
        return True


class RecoveryCodeError(Exception):
    """Exception raised when failing to get recovery code."""

    pass


def get_recovery_code(hostname, game_id):
    url = f"http://{hostname}/api/v1/games/get-recovery"
    params = {"game_id": game_id}
    response = requests.get(url, params=params, timeout=30)

    if response.status_code == 200:
        data = response.json()
        return data["data"]["recovery"]

    raise RecoveryCodeError(f"Failed to get recovery code: {response.text}")


def get_agent_logger(agent_id, game_id):
    agent_log_file = LOG_PATH / "agents" / f"agent_{agent_id}.log"
    game_log_file = LOG_PATH / "game" / f"game_{game_id}.log"

    agent_logger = logging.getLogger(f"agent_{agent_id}")
    agent_logger.setLevel(logging.DEBUG)

    if agent_log_file.exists():
        agent_log_file.unlink()

    Path(agent_log_file).touch()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] [AGENT %(agent_id)s] %(message)s")

    file_handler = logging.FileHandler(agent_log_file)
    file_handler.setFormatter(formatter)
    game_file_handler = logging.FileHandler(game_log_file)
    game_file_handler.setFormatter(formatter)

    context_filter = ContextInjectingFilter()
    file_handler.addFilter(context_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)

    agent_logger.addHandler(file_handler)
    agent_logger.addHandler(console_handler)
    agent_logger.addHandler(game_file_handler)

    return agent_logger


def get_game_logger(game_id):
    game_log_file = LOG_PATH / "game" / f"game_{game_id}.log"

    if game_log_file.exists():
        game_log_file.unlink()

    Path(game_log_file).touch()

    game_logger = logging.getLogger(f"game_{game_id}")
    game_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(game_log_file)
    file_handler.setFormatter(formatter)

    context_filter = ContextInjectingFilter()
    file_handler.addFilter(context_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)

    game_logger.addHandler(file_handler)
    game_logger.addHandler(console_handler)

    return game_logger


async def start_simulation(ws_url, login_payload, game_id, agent_id):
    agent_logger = get_agent_logger(agent_id, game_id)
    ctx_agent_id.set(agent_id)

    try:
        agent_logger.info(f"Connecting to WebSocket URL: {ws_url}")
        game = AgentManager(url=ws_url, login_payload=login_payload, game_id=game_id, logger=agent_logger)
        await game.start()

    except Exception:
        agent_logger.exception(f"Error in simulation for Agent {agent_id}")
        raise


def validate_game_params(game_id, agents, game_type, use_config):
    if not game_id:
        raise ValueError("Missing required parameter: 'game_id'")
    if not agents:
        raise ValueError("Missing required parameter: 'agents'")
    if not game_type:
        raise ValueError("Missing required parameter: 'game_type'")


def save_game_config(game_config):
    with Path(LOG_PATH / "game" / f"game_{game_config['game_id']}.json").open("w") as f:
        json.dump(game_config, f, indent=4)


def load_game_config(game_id):
    with Path(LOG_PATH / "game" / f"game_{game_id}.json").open("r") as f:
        return json.load(f)


def get_game_config(game_id, agents, game_type, use_config="auto"):
    if use_config == "auto":
        if Path(LOG_PATH / "game" / f"game_{game_id}.json").exists():
            game_config = load_game_config(game_id)
        else:
            game_config = {"game_id": game_id, "agents": agents, "game_type": game_type, "recovery_codes": []}
            game_config["recovery_codes"] = [get_recovery_code(HOSTNAME, game_id) for _ in range(agents)]
            save_game_config(game_config)
    elif use_config:
        if Path(LOG_PATH / "game" / f"game_{game_id}.json").exists():
            game_config = load_game_config(game_id)
        else:
            raise ValueError("Game config provided but no config file exists")
    else:
        game_config = {"game_id": game_id, "agents": agents, "game_type": game_type, "recovery_codes": []}
        game_config["recovery_codes"] = [get_recovery_code(HOSTNAME, game_id) for _ in range(agents)]
        save_game_config(game_config)

    return game_config


def load_game_spec(game_id: int) -> dict:
    """Load a game specification from the games directory."""
    spec_file = GAMES_PATH / f"game_{game_id}.json"
    if not spec_file.exists():
        raise ValueError(f"Game spec file not found: {spec_file}")

    with spec_file.open() as f:
        return json.load(f)


async def spawn_agents(game_id: int):
    """Spawn agents for a game using its specification file."""
    game_logger = get_game_logger(game_id)
    game_logger.info(f"Loading spec for game {game_id}")

    try:
        game_spec = load_game_spec(game_id)
        game_logger.info(f"Game spec loaded: {game_spec}")

        ws_url = f"ws://{HOSTNAME}:{PORT}/wss"
        tasks = []
        game_logger.info("Starting simulations")

        for idx, recovery_code in enumerate(game_spec["recovery_codes"]):
            login_payload = {
                "gameId": game_id,
                "type": "join",
                "recovery": recovery_code,
            }
            tasks.append(start_simulation(ws_url, login_payload, game_id, idx + 1))
        await asyncio.gather(*tasks)

    except Exception:
        game_logger.exception("Error in game setup")
        raise

    finally:
        game_logger.info("Game finished")


async def create_and_run_game(specs_path: Path) -> None:
    """Create a new game from specs and run it."""
    if not specs_path.exists():
        raise ValueError(f"Specs file not found at: {specs_path}")

    game_name = f"harberger {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    game_server_url = f"http://{HOSTNAME}"

    try:
        game_id = create_game_from_specs(specs_path=specs_path, base_url=game_server_url, game_name=game_name)
        game_logger = get_game_logger(game_id)
        game_logger.info(f"Created new game with ID: {game_id}")
        await spawn_agents(game_id)

    except Exception as e:
        game_logger.error(f"Failed to create and run game: {e}")
        raise


if __name__ == "__main__":
    Path(LOG_PATH).mkdir(parents=True, exist_ok=True)
    Path(LOG_PATH / "agents").mkdir(parents=True, exist_ok=True)
    Path(LOG_PATH / "game").mkdir(parents=True, exist_ok=True)

    # Create and run a new game:
    specs_path = Path(__file__).parent / "specs/example/harberger.json"
    asyncio.run(create_and_run_game(specs_path))

    # Run an existing game:
    # asyncio.run(spawn_agents(game_id=181))
