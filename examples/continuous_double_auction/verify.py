"""End-to-end verification of the Continuous Double Auction example.

Runs the local server and agents in the same process. The LLM provider is
replaced with a deterministic stub, but actions still go through the role's
LLM prompt and structured-output path:

    uv run python examples/continuous_double_auction/verify.py
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
from econagents.runtime.game_runner import GameRunner, HybridGameRunnerConfig
from examples.continuous_double_auction.agents import MARKET_PHASE, SUMMARY_PHASE, MarketAction, create_cda_agents
from examples.continuous_double_auction.server import server as server_module
from examples.continuous_double_auction.server.server import ContinuousDoubleAuctionServer

HOST = "localhost"


class TraderStubLLM(BaseLLM):
    """Deterministic stand-in used to verify the LLM role path without network calls."""

    def __init__(self) -> None:
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
        private = state["private_information"]
        public = state["public_information"]

        action = _stub_action(game_id, private, public)
        if response_schema is not None:
            return response_schema.model_validate(action)
        return action


def _stub_action(game_id: int, private: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    if private["remaining_units"] <= 0 or private["limit_price"] is None:
        return {
            "meta": {"type": "hold", "component": {"type": "continuous-double-auction:order"}},
            "payload": {"gameId": game_id, "reason": "no remaining units"},
        }

    if private["trader_type"] == "buyer":
        best_ask = public["best_ask"]
        best_bid = public["best_bid"]
        value = private["limit_price"]
        if best_ask is not None and best_ask <= value:
            price = best_ask
        elif best_bid is None:
            price = min(value, 60.0)
        else:
            price = min(value, best_bid + 5.0)
        side = "buy"
    elif private["trader_type"] == "seller":
        best_bid = public["best_bid"]
        best_ask = public["best_ask"]
        cost = private["limit_price"]
        if best_bid is not None and best_bid >= cost:
            price = best_bid
        elif best_ask is None:
            price = max(cost, 100.0)
        else:
            price = max(cost, best_ask - 5.0)
        side = "sell"
    else:
        return {
            "meta": {"type": "hold", "component": {"type": "continuous-double-auction:order"}},
            "payload": {"gameId": game_id, "reason": "unassigned trader role"},
        }

    return {
        "meta": {"type": "submit-order", "component": {"type": "continuous-double-auction:order"}},
        "payload": {"gameId": game_id, "side": side, "price": round(price, 2)},
    }


async def main() -> None:
    load_dotenv()
    logging.getLogger("websockets").setLevel(logging.WARNING)

    with tempfile.TemporaryDirectory() as tmp:
        temp_dir = Path(tmp)
        specs = _write_game_specs(temp_dir)
        game_id = specs["game_id"]
        recovery_codes = specs["recovery_codes"]
        server_module.SPECS_PATH = temp_dir / "games"
        server = ContinuousDoubleAuctionServer(host=HOST, port=0)

        async with serve(server.handle_websocket, HOST, 0) as websocket_server:
            port = websocket_server.sockets[0].getsockname()[1]
            config = HybridGameRunnerConfig(
                game_id=game_id,
                logs_dir=temp_dir / "logs",
                prompts_dir=Path(__file__).parent / "prompts",
                log_level=logging.WARNING,
                hostname=HOST,
                port=port,
                path="",
                continuous_phases=[MARKET_PHASE],
                min_action_delay=1,
                max_action_delay=1,
                max_game_duration=20,
            )
            agents = create_cda_agents(config, recovery_codes)
            for agent in agents:
                agent.role.llm = TraderStubLLM()
            runner = GameRunner(config=config, agents=agents)
            await runner.run_game()

    _assert_game_completed(server, game_id, agents)


def _write_game_specs(temp_dir: Path) -> dict[str, Any]:
    game_id = 1
    traders = [
        {
            "name": "Buyer 1",
            "trader_type": "buyer",
            "limit_prices": [110.0, 100.0, 90.0, 80.0, 70.0],
            "cash_endowment": 450.0,
            "recovery": "buyer-1",
        },
        {
            "name": "Buyer 2",
            "trader_type": "buyer",
            "limit_prices": [105.0, 95.0, 85.0, 75.0, 65.0],
            "cash_endowment": 425.0,
            "recovery": "buyer-2",
        },
        {
            "name": "Seller 1",
            "trader_type": "seller",
            "limit_prices": [35.0, 45.0, 55.0, 65.0, 75.0],
            "recovery": "seller-1",
        },
        {
            "name": "Seller 2",
            "trader_type": "seller",
            "limit_prices": [40.0, 50.0, 60.0, 70.0, 80.0],
            "recovery": "seller-2",
        },
    ]
    recovery_codes = [trader["recovery"] for trader in traders]
    games_dir = temp_dir / "games"
    games_dir.mkdir(parents=True)
    specs = {
        "game_id": game_id,
        "game_name": "Verification Continuous Double Auction",
        "num_players": len(traders),
        "recovery_codes": recovery_codes,
        "traders": traders,
        "market_duration": 15,
        "summary_duration": 1,
        "created_at": "verification",
    }
    (games_dir / f"game_{game_id}.json").write_text(json.dumps(specs))
    return specs


def _assert_game_completed(server: ContinuousDoubleAuctionServer, game_id: int, agents: list[Agent]) -> None:
    game = server.games[game_id]

    assert game.state == "finished", f"expected game to finish, got state={game.state!r}"
    assert len(game.transactions) > 4, "expected the expanded unit schedule to produce more than four trades"
    assert sum(game.actions_submitted.values()) > len(agents), "expected repeated continuous-phase actions"
    assert game.market_summary()["total_trades"] == len(game.transactions)
    assert all(game.cash_balance[player] >= 0 for player in (1, 2)), "buyers should not overspend cash balance"

    for agent in agents:
        assert agent.state.meta.phase == "finished"
        assert agent.state.public_information.transactions
        assert agent.state.public_information.market_summary["total_trades"] == len(game.transactions)
        assert isinstance(agent.role.llm, TraderStubLLM)
        assert agent.role.llm.calls
        assert agent.role.get_response_schema(MARKET_PHASE) is MarketAction
        assert agent.role.get_response_schema(SUMMARY_PHASE) is None

    print("PASS: continuous double auction example completed end-to-end")
    print(f"  game_id        : {game_id}")
    print(f"  actions sent   : {sum(game.actions_submitted.values())}")
    print(f"  trades executed: {len(game.transactions)}")
    print(f"  transactions   : {game.transactions}")


if __name__ == "__main__":
    asyncio.run(main())
