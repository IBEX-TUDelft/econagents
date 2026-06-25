"""End-to-end verification of the Dictator example.

Runs the bundled mock server and two agents in the same process. The LLMs are
replaced with deterministic stand-ins, so this check needs no API key:

    uv run python examples/dictator/verify.py
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
from examples.dictator.agents import DictatorDecision, DoneAction, create_dictator_agents
from examples.dictator.server import server as server_module
from examples.dictator.server.server import DictatorServer

HOST = "localhost"


class DictatorStubLLM(BaseLLM):
    """Deterministic Dictator model that sends a fixed amount."""

    def __init__(self, money_send: float):
        self.money_send = money_send
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
    ):
        self.calls.append({"messages": messages, "tracing_extra": tracing_extra})
        game_id = tracing_extra["state"]["meta"]["game_id"]
        if response_schema is DictatorDecision:
            return response_schema.model_validate(
                {"gameId": game_id, "type": "decision", "money_send": self.money_send}
            )
        if response_schema is DoneAction:
            return response_schema.model_validate({"gameId": game_id, "type": "action", "action": "done"})
        raise AssertionError(f"Unexpected response schema: {response_schema}")


class ReceiverStubLLM(BaseLLM):
    """Deterministic Receiver model that acknowledges payout."""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
    ):
        self.calls.append({"messages": messages, "tracing_extra": tracing_extra})
        game_id = tracing_extra["state"]["meta"]["game_id"]
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
        server = DictatorServer(host=HOST, port=0)

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
            agents = create_dictator_agents(config, recovery_codes)
            agents[0].role.llm = DictatorStubLLM(money_send=4.0)
            agents[1].role.llm = ReceiverStubLLM()

            runner = GameRunner(config=config, agents=agents)
            await runner.run_game()

    _assert_game_completed(server, game_id, agents)


def _write_game_specs(temp_dir: Path) -> dict[str, Any]:
    game_id = 1
    recovery_codes = ["dictator-code", "receiver-code"]
    games_dir = temp_dir / "games"
    games_dir.mkdir(parents=True)
    specs = {
        "game_id": game_id,
        "game_name": "Verification Dictator Game",
        "num_players": 2,
        "recovery_codes": recovery_codes,
        "money_available": 10.0,
        "exchange_rate": 3.0,
        "created_at": "verification",
    }
    (games_dir / f"game_{game_id}.json").write_text(json.dumps(specs))
    return specs


def _assert_game_completed(server: DictatorServer, game_id: int, agents: list[Agent]) -> None:
    game = server.games[game_id]
    payouts = game.calculate_payouts()

    assert game.state == "finished", f"expected game to finish, got state={game.state!r}"
    assert game.money_sent == 4.0
    assert payouts == {"dictator": 6.0, "receiver": 12.0}

    dictator_agent, receiver_agent = agents
    assert dictator_agent.state.public_information.money_sent == 4.0
    assert dictator_agent.state.private_information.payout == 6.0
    assert receiver_agent.state.private_information.payout == 12.0

    dictator_phase_2_prompt = dictator_agent.role.llm.calls[1]["messages"][1]["content"]
    receiver_phase_2_prompt = receiver_agent.role.llm.calls[0]["messages"][1]["content"]
    assert "You decided to send: $4.0" in dictator_phase_2_prompt
    assert "You kept: $6.0" in dictator_phase_2_prompt
    assert "You received: $12.0" in receiver_phase_2_prompt

    print("PASS: dictator example completed end-to-end")
    print(f"  game_id    : {game_id}")
    print(f"  money_sent : {game.money_sent}")
    print(f"  payouts    : {payouts}")


if __name__ == "__main__":
    asyncio.run(main())
