"""End-to-end verification of the Prisoner's Dilemma example.

Runs the bundled mock server and two agents in the same process. The
LLM is replaced with a deterministic stub, so the check needs no API key:

    uv run python examples/prisoner/verify.py
"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional, Type

from dotenv import load_dotenv
from pydantic import BaseModel
from websockets.asyncio.server import serve

from econagents.adapters.llm.base import BaseLLM
from econagents.runtime import Agent
from econagents.runtime.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.prisoner.server.create_game import create_game_from_specs
from examples.prisoner.server.server import PrisonersDilemmaServer
from examples.prisoner.agents import create_prisoner_agents

HOST = "localhost"
PORT = 8765


class StubLLM(BaseLLM):
    """Deterministic LLM stand-in that always returns the same choice."""

    def __init__(self, choice: str = "COOPERATE"):
        self._choice = choice

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
    ):
        envelope = {
            "meta": {"type": "submit-choice", "component": {"type": "standard:coordination"}},
            "payload": {"choice": self._choice},
        }
        if response_schema is not None:
            return response_schema.model_validate(envelope)
        return json.dumps(envelope)


async def main() -> None:
    load_dotenv()
    logging.getLogger("websockets").setLevel(logging.WARNING)

    specs = create_game_from_specs()
    game_id = specs["game_id"]
    recovery_codes = specs["recovery_codes"]
    server = PrisonersDilemmaServer(host=HOST, port=PORT)

    async with serve(server.handle_websocket, HOST, PORT):
        with tempfile.TemporaryDirectory() as tmp:
            config = TurnBasedGameRunnerConfig(
                game_id=game_id,
                logs_dir=Path(tmp) / "logs",
                prompts_dir=Path(__file__).parent / "prompts",
                log_level=logging.WARNING,
                hostname=HOST,
                port=PORT,
                path="",
                max_game_duration=30,
            )
            agents = create_prisoner_agents(config, recovery_codes)
            for agent in agents:
                agent.role.llm = StubLLM("COOPERATE")

            runner = GameRunner(config=config, agents=agents)
            await runner.run_game()

    _assert_game_completed(server, game_id, agents)


def _assert_game_completed(server: PrisonersDilemmaServer, game_id: int, agents: list[Agent]) -> None:
    game = server.games[game_id]

    assert game.has_two_players(), "expected two players to join"
    assert all(game.player_ready.values()), "expected both players to send ready"
    assert game.state == "finished", f"expected game to finish, got state={game.state!r}"
    assert len(game.round_results) == game.total_rounds

    for i, agent in enumerate(agents, start=1):
        history = agent.state.public_information.history
        assert history, f"agent {i} has no round history"
        assert agent.state.private_information.total_score > 0

    print("PASS: prisoner example completed end-to-end")
    print(f"  game_id       : {game_id}")
    print(f"  rounds played : {len(game.round_results)}")
    print(f"  final scores  : {server.games[game_id].player_scores}")


if __name__ == "__main__":
    asyncio.run(main())
