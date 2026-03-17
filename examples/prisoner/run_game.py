import argparse
import asyncio
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.prisoner.manager import PDManager
from examples.prisoner.state import PDGameState

logger = logging.getLogger("prisoners_dilemma")


async def join_game(game_id: str, hostname: str, api_port: int) -> dict:
    """Call POST /games/:id/join and return the join response."""
    url = f"http://{hostname}:{api_port}/games/{game_id}/join"
    async with httpx.AsyncClient() as client:
        response = await client.post(url)
        response.raise_for_status()
        return response.json()


async def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", required=True)
    args, _ = parser.parse_known_args()

    hostname = os.getenv("HOSTNAME", "localhost")
    ws_port = int(os.getenv("WS_PORT", "3088"))
    api_port = int(os.getenv("API_PORT", "3089"))

    join = await join_game(args.game_id, hostname, api_port)
    logger.info(f"Joined game {args.game_id} as player {join['playerNumber']}, token={join['token']}")

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
        phase_transition_event="round-started",
        phase_identifier_key="round",
    )

    agent = PDManager(
        game_id=args.game_id,
        auth_mechanism_kwargs=auth_payload,
    )
    runner = GameRunner(config=config, agents=[agent])
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
