"""End-to-end verification of the Prisoner's Dilemma example.

Runs the bundled mock server and two agents in the same process. The
LLM is replaced with a deterministic stub, so the check needs no API key:

    uv run python examples/prisoner/verify.py
"""

import asyncio
import json
import logging
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional, Type

from dotenv import load_dotenv
from pydantic import BaseModel
from websockets.asyncio.server import serve

from econagents.adapters.llm.base import BaseLLM
from econagents.runtime import Agent
from econagents.runtime.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.prisoner.server import server as server_module
from examples.prisoner.server.server import PrisonersDilemmaServer
from examples.prisoner.agents import create_prisoner_agents

HOST = "localhost"


class StubLLM(BaseLLM):
    """Deterministic LLM stand-in that always returns the same choice."""

    def __init__(self, choice: str = "COOPERATE"):
        self._choice = choice
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
    ):
        self.calls.append({"messages": messages, "tracing_extra": tracing_extra})
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

    with tempfile.TemporaryDirectory() as tmp:
        temp_dir = Path(tmp)
        specs = _write_game_specs(temp_dir)
        game_id = specs["game_id"]
        recovery_codes = specs["recovery_codes"]
        server_module.SPECS_PATH = temp_dir / "games"
        server = PrisonersDilemmaServer(host=HOST, port=0)

        async with serve(server.handle_websocket, HOST, 0) as websocket_server:
            port = websocket_server.sockets[0].getsockname()[1]
            config = TurnBasedGameRunnerConfig(
                game_id=game_id,
                logs_dir=temp_dir / "logs",
                prompts_dir=Path(__file__).parent / "prompts",
                log_level=logging.WARNING,
                hostname=HOST,
                port=port,
                path="",
                max_game_duration=30,
            )
            agents = create_prisoner_agents(config, recovery_codes)
            for agent in agents:
                agent.role.llm = StubLLM("COOPERATE")

            runner = GameRunner(config=config, agents=agents)
            await runner.run_game()

    _assert_game_completed(server, game_id, agents)


def _write_game_specs(temp_dir: Path) -> dict[str, Any]:
    game_id = 1
    recovery_codes = ["code-1", "code-2"]
    games_dir = temp_dir / "games"
    games_dir.mkdir(parents=True)
    specs = {
        "game_id": game_id,
        "game_name": "Verification Prisoner's Dilemma",
        "num_players": 2,
        "recovery_codes": recovery_codes,
        "created_at": "verification",
    }
    (games_dir / f"game_{game_id}.json").write_text(json.dumps(specs))
    return specs


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
        assert agent.state.meta.phase == "decision"
        assert agent.state.meta.round == game.total_rounds

    calls_by_agent = defaultdict(list)
    for agent in agents:
        for call in agent.role.llm.calls:
            calls_by_agent[id(agent)].append(call)

    for i, agent in enumerate(agents, start=1):
        calls = calls_by_agent[id(agent)]
        assert len(calls) == game.total_rounds
        first_user_prompt = calls[0]["messages"][1]["content"]
        final_user_prompt = calls[-1]["messages"][1]["content"]
        assert "Round 1 of 5 rounds" in first_user_prompt
        assert "This is the first round." in first_user_prompt
        assert "Round 5 of 5 rounds" in final_user_prompt
        assert "Previous rounds:" in final_user_prompt

    print("PASS: prisoner example completed end-to-end")
    print(f"  game_id       : {game_id}")
    print(f"  rounds played : {len(game.round_results)}")
    print(f"  final scores  : {server.games[game_id].player_scores}")


if __name__ == "__main__":
    asyncio.run(main())
