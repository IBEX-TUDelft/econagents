"""End-to-end verification of the Public Goods example.

Runs the bundled mock server and four agents in the same process. The LLMs are
replaced with deterministic stand-ins, so this check needs no API key:

    uv run python examples/public_goods/verify.py
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
from econagents.adapters.transport import SimpleLoginPayloadAuth
from econagents.runtime import Agent
from econagents.runtime.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.public_goods.agents import Contribution, DoneAction, create_public_goods_agents
from examples.public_goods.server import server as server_module
from examples.public_goods.server.server import PublicGoodsServer

HOST = "localhost"


class PlayerStubLLM(BaseLLM):
    """Deterministic Public Goods model with per-player contributions."""

    def __init__(self, contributions: dict[str, float]):
        self.contributions = contributions
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
    ):
        self.calls.append({"messages": messages, "tracing_extra": tracing_extra})
        state = tracing_extra["state"]
        game_id = state["meta"]["game_id"]
        player_id = state["private_information"]["player_id"]
        if response_schema is Contribution:
            return response_schema.model_validate(
                {
                    "gameId": game_id,
                    "type": "contribution",
                    "contribution": self.contributions[player_id],
                }
            )
        if response_schema is DoneAction:
            return response_schema.model_validate({"gameId": game_id, "type": "action", "action": "done"})
        raise AssertionError(f"Unexpected response schema: {response_schema}")


async def main() -> None:
    load_dotenv()
    logging.getLogger("websockets").setLevel(logging.WARNING)

    with tempfile.TemporaryDirectory() as tmp:
        temp_dir = Path(tmp)
        specs = _write_game_specs(temp_dir)
        game_id = specs["game_id"]
        recovery_codes = specs["recovery_codes"]
        server_module.SPECS_PATH = temp_dir / "games"
        server = PublicGoodsServer(host=HOST, port=0)

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
                auth_mechanism=SimpleLoginPayloadAuth(),
                phase_transition_event="phase-started",
                phase_identifier_key="phase",
                max_game_duration=30,
            )
            personalities = ["selfish", "cooperative", "selfish", "cooperative"]
            agents = create_public_goods_agents(config, recovery_codes, personalities)
            contributions = {"player_1": 0.0, "player_2": 10.0, "player_3": 20.0, "player_4": 5.0}
            for agent in agents:
                agent.role.llm = PlayerStubLLM(contributions)

            runner = GameRunner(config=config, agents=agents)
            await runner.run_game()

    _assert_game_completed(server, game_id, agents)


def _write_game_specs(temp_dir: Path) -> dict[str, Any]:
    game_id = 1
    recovery_codes = ["player-1-code", "player-2-code", "player-3-code", "player-4-code"]
    games_dir = temp_dir / "games"
    games_dir.mkdir(parents=True)
    specs = {
        "game_id": game_id,
        "game_name": "Verification Public Goods Game",
        "num_players": 4,
        "recovery_codes": recovery_codes,
        "initial_endowment": 20.0,
        "public_good_efficiency": 0.5,
        "created_at": "verification",
    }
    (games_dir / f"game_{game_id}.json").write_text(json.dumps(specs))
    return specs


def _assert_game_completed(server: PublicGoodsServer, game_id: int, agents: list[Agent]) -> None:
    game = server.games[game_id]
    payoffs = game.calculate_payoffs()
    total_contribution = sum(game.contributions.values())

    assert game.state == "finished", f"expected game to finish, got state={game.state!r}"
    assert game.contributions == {"player_1": 0.0, "player_2": 10.0, "player_3": 20.0, "player_4": 5.0}
    assert total_contribution == 35.0

    for agent in agents:
        player_id = agent.state.private_information.player_id
        assert agent.state.public_information.total_contribution == total_contribution
        assert agent.state.private_information.your_payoff == payoffs[player_id]
        assert len(agent.role.llm.calls) == 2

    first_system_prompt = agents[0].role.llm.calls[0]["messages"][0]["content"]
    second_system_prompt = agents[1].role.llm.calls[0]["messages"][0]["content"]
    assert "You only care about maximizing your own payoff." in first_system_prompt
    assert "You care about the collective well-being" in second_system_prompt

    phase_2_prompt = agents[1].role.llm.calls[1]["messages"][1]["content"]
    assert "Total Contribution to Public Good: $35.0" in phase_2_prompt
    assert "player_2: $10.0" in phase_2_prompt
    assert f"Your final payoff: ${payoffs['player_2']}" in phase_2_prompt

    print("PASS: public goods example completed end-to-end")
    print(f"  game_id            : {game_id}")
    print(f"  total_contribution : {total_contribution}")
    print(f"  payoffs            : {payoffs}")


if __name__ == "__main__":
    asyncio.run(main())
