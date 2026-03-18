import argparse
import asyncio
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.prisoner.manager import PDManager
from examples.prisoner.state import PDGameState

logger = logging.getLogger("prisoners_dilemma")


def join_game(game_id: str, hostname: str, api_port: int) -> dict:
    """Call POST /games/:id/join and return the join response."""
    url = f"http://{hostname}:{api_port}/games/{game_id}/join"
    response = requests.post(url)
    response.raise_for_status()
    return response.json()


def get_game_state(game_id: str, token: str, hostname: str, api_port: int) -> dict:
    """Call GET /games/:id/state to retrieve the current phase."""
    url = f"http://{hostname}:{api_port}/games/{game_id}/state"
    response = requests.get(url, params={"recovery": token})
    response.raise_for_status()
    return response.json()


async def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--personality", default=None)
    args, _ = parser.parse_known_args()

    hostname = os.getenv("HOSTNAME", "localhost")
    ws_port = int(os.getenv("WS_PORT", "3088"))
    api_port = int(os.getenv("API_PORT", "3089"))

    join = join_game(args.game_id, hostname, api_port)
    logger.info(f"Joined game {args.game_id} as player {join['playerNumber']}, token={join['token']}")
    state = get_game_state(args.game_id, join["token"], hostname, api_port)
    initial_phase = state["phaseIndex"]
    logger.info(f"Current phase: {initial_phase} ({state['phaseName']})")

    auth_payload = {
        "meta": {"type": "join", "gameId": args.game_id},
        "payload": {"recovery": join["token"]},
    }

    config = TurnBasedGameRunnerConfig(
        game_id=args.game_id,
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.INFO,
        hostname=hostname,
        port=ws_port,
        path="",
        state_class=PDGameState,
        phase_transition_event="phase_transition:phase-transition",
        phase_identifier_key="phase",
        end_game_event="system:game-over",
    )

    agent = PDManager(
        game_id=args.game_id,
        auth_mechanism_kwargs=auth_payload,
        initial_phase=initial_phase,
        personality=args.personality,
    )
    runner = GameRunner(config=config, agents=[agent])
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
