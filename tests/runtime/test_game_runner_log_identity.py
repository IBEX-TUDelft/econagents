"""GameRunner log naming and identity headers (IBEX-game_suite#10)."""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pytest

from econagents.adapters.llm.base import BaseLLM
from econagents.domain.messages import Event
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime.agent import Agent
from econagents.runtime.game_runner import GameRunner, GameRunnerConfig

GAME_ID = 5


class FailingLLM(BaseLLM):
    async def get_response(self, messages, tracing_extra, response_schema=None, **kwargs) -> str:
        raise ConnectionError("provider outage")


class TraderRole(Role):
    role = 1
    name = "trader"
    llm = FailingLLM()


class OneEventTransport:
    def __init__(self, event: Optional[Event] = None) -> None:
        self.event = event
        self.agent: Optional[Agent] = None
        self.logger = logging.getLogger("unbound")

    async def start_listening(self) -> None:
        if self.event is not None and self.agent is not None:
            await self.agent.on_event(self.event)

    async def send(self, message: str) -> None:
        return None

    async def stop(self) -> None:
        return None


def make_agent(tmp_path: Path, player_number: Optional[int], event: Optional[Event] = None) -> Agent:
    state = GameState()
    state.meta.game_id = GAME_ID
    state.meta.player_number = player_number
    transport = OneEventTransport(event)
    agent = Agent(url="ws://127.0.0.1:9", state=state, role=TraderRole(), prompts_dir=tmp_path, transport=transport)
    transport.agent = agent
    return agent


def config(tmp_path: Path, **changes: Any) -> GameRunnerConfig:
    return GameRunnerConfig(
        hostname="127.0.0.1",
        port=9,
        path="",
        game_id=GAME_ID,
        logs_dir=tmp_path / "logs",
        prompts_dir=tmp_path,
        max_game_duration=0,
        **changes,
    )


def game_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs" / f"game_{GAME_ID}"


def header(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text().splitlines()[0])


@pytest.mark.asyncio
async def test_header_is_the_first_line_and_names_the_seat(tmp_path):
    agent = make_agent(tmp_path, 4)
    await GameRunner(config=config(tmp_path, run_id="run-1"), agents=[agent]).run_game()

    record = header(game_dir(tmp_path) / "agent_4.log")
    assert record["record"] == "agent-identity"
    assert record["trace_schema_version"] == 1
    assert (record["run_id"], record["game_id"], record["player_number"], record["role"]) == (
        "run-1",
        GAME_ID,
        4,
        "trader",
    )
    assert record["agent_instance_id"] == agent.instance_id
    assert (record["seat_kind"], record["launch_index"], record["log_naming"]) == ("agent", 1, "player-number")
    assert record["player_number_source"] == "configured"


@pytest.mark.asyncio
async def test_launch_index_naming_is_selectable(tmp_path):
    agents = [make_agent(tmp_path, 4), make_agent(tmp_path, 9)]
    await GameRunner(config=config(tmp_path, agent_log_naming="launch-index"), agents=agents).run_game()

    assert [header(game_dir(tmp_path) / f"agent_{i}.log")["player_number"] for i in (1, 2)] == [4, 9]
    assert header(game_dir(tmp_path) / "agent_1.log")["log_naming"] == "launch-index"


@pytest.mark.asyncio
async def test_launch_index_never_shares_a_seats_file(tmp_path):
    agents = [make_agent(tmp_path, 2), make_agent(tmp_path, None)]
    await GameRunner(config=config(tmp_path), agents=agents).run_game()

    assert header(game_dir(tmp_path) / "agent_2.log")["player_number"] == 2
    fallback = header(game_dir(tmp_path) / "agent_4.log")
    assert (fallback["player_number"], fallback["launch_index"], fallback["log_naming"]) == (None, 2, "launch-index")


@pytest.mark.asyncio
async def test_two_agents_for_one_seat_are_refused(tmp_path):
    with pytest.raises(ValueError, match="player number"):
        await GameRunner(config=config(tmp_path), agents=[make_agent(tmp_path, 3), make_agent(tmp_path, 3)]).run_game()


@pytest.mark.asyncio
async def test_failed_model_call_is_recorded_with_its_input(tmp_path):
    (tmp_path / "all_system.jinja2").write_text("system text")
    (tmp_path / "all_user.jinja2").write_text("user text")
    agent = make_agent(tmp_path, 6, Event(type="phase-transition", data={"phase": 1}))
    await GameRunner(config=config(tmp_path), agents=[agent]).run_game()

    lines = (game_dir(tmp_path) / "agent_6.model_calls.jsonl").read_text().splitlines()
    record = json.loads(lines[0])
    assert record["record"] == "model-call"
    assert record["player_number"] == 6
    assert [m["content"] for m in record["messages"]] == ["system text", "user text"]
    assert record["error"] == "ConnectionError: provider outage"
    assert "model-call" not in (game_dir(tmp_path) / "agent_6.log").read_text()
