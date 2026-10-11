"""Reproduction for IBEX-game_suite#10 (FPM-23): agent logs carry no authenticated player identity.

GameRunner names every agent log and every ``[AGENT n]`` tag by launch index. When a human takes a
seat, run_game leaves that seat out of the agent list, so ``agent_1.log`` holds player 2's records
and nothing in the file says so. Tests are grouped by kind:

- behavioral: each agent log records the authenticated player number and role.
- interface proposal: a replacement agent instance for the same seat (a second runner after a crash,
  same logs_dir) keeps the actor, does not erase the first instance's records, and is recorded with
  its own instance identifier.
- decision-gated (log naming): no file name or ``[AGENT n]`` tag points at another seat's number.
- guard: agents without a player identity keep the launch-index ``agent_<i>.log`` files.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import pytest

from econagents.adapters.llm.base import BaseLLM
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime.agent import Agent
from econagents.runtime.game_runner import GameRunner, GameRunnerConfig

GAME_ID = 21
HUMAN_SEATS = {1: "owner"}
AGENT_SEATS = [(2, "developer"), (3, "owner"), (7, "speculator"), (8, "speculator")]


class UnusedLLM(BaseLLM):
    async def get_response(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("no model call is expected in these tests")


def role_class(role_name: str) -> type[Role]:
    return type(
        f"{role_name.title()}Role",
        (Role,),
        {"role": 1, "name": role_name, "llm": UnusedLLM()},
    )


class MarkerTransport:
    """Transport stand-in: start_listening writes one record through the logger the runner injected."""

    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.logger = logging.getLogger("unbound-transport")

    async def start_listening(self) -> None:
        self.logger.info(self.marker)

    async def send(self, message: str) -> None:
        return None

    async def stop(self) -> None:
        return None


def make_agent(player_number: Optional[int], role_name: str, marker: str, tmp_path: Path) -> Agent:
    state = GameState()
    state.meta.game_id = GAME_ID
    state.meta.player_number = player_number
    return Agent(
        url="ws://127.0.0.1:9",
        state=state,
        role=role_class(role_name)(),
        prompts_dir=tmp_path,
        transport=MarkerTransport(marker),
    )


def marker_for(player_number: int, instance: str = "a") -> str:
    return f"seat-record player={player_number} instance={instance}"


@pytest.fixture
def config(tmp_path):
    return GameRunnerConfig(
        hostname="127.0.0.1",
        port=9,
        path="",
        game_id=GAME_ID,
        logs_dir=tmp_path / "logs",
        prompts_dir=tmp_path,
        log_level=logging.INFO,
        max_game_duration=0,
    )


def game_dir(config: GameRunnerConfig) -> Path:
    return config.logs_dir / f"game_{GAME_ID}"


def agent_logs(config: GameRunnerConfig) -> list[Path]:
    return sorted(p for p in game_dir(config).glob("*.log") if p.name != "all.log")


def identity_record(path: Path) -> Optional[dict[str, Any]]:
    """The first machine-readable identity record near the top of a log (format left to the fix)."""
    for line in path.read_text(errors="replace").splitlines()[:5]:
        start = line.find("{")
        if start < 0:
            continue
        try:
            record = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            if isinstance(record.get("identity"), dict):
                record = record["identity"]
            if "player_number" in record:
                return record
    return None


def identity_governing(path: Path, marker: str) -> Optional[dict[str, Any]]:
    """The latest identity record written before ``marker`` in ``path`` (one file per instance, or appended)."""
    current = None
    for line in path.read_text(errors="replace").splitlines():
        if marker in line:
            return current
        start = line.find("{")
        if start < 0:
            continue
        try:
            record = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            record = record["identity"] if isinstance(record.get("identity"), dict) else record
            if "player_number" in record:
                current = record
    return None


def instance_ids(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if "instance" in k.lower() and v is not None}


def file_holding(config: GameRunnerConfig, marker: str) -> list[Path]:
    return [p for p in agent_logs(config) if marker in p.read_text(errors="replace")]


async def run_mixed_game(config: GameRunnerConfig, tmp_path: Path) -> list[Agent]:
    agents = [make_agent(n, role, marker_for(n), tmp_path) for n, role in AGENT_SEATS]
    await GameRunner(config=config, agents=agents).run_game()
    return agents


@pytest.mark.asyncio
async def test_agent_logs_record_authenticated_player_identity(config, tmp_path):
    """behavioral: with human seat 1, every agent log names its authenticated seat, not its launch index."""
    await run_mixed_game(config, tmp_path)
    logs = agent_logs(config)
    assert len(logs) == len(AGENT_SEATS)

    for player_number, role_name in AGENT_SEATS:
        holders = file_holding(config, marker_for(player_number))
        assert len(holders) == 1, f"player {player_number}'s records are in {[p.name for p in holders]}"
        record = identity_record(holders[0])
        assert record is not None, (
            f"{holders[0].name} holds player {player_number}'s records (human seat(s) "
            f"{sorted(HUMAN_SEATS)} shifted the launch index) but has no machine-readable identity record; "
            f"first line: {holders[0].read_text(errors='replace').splitlines()[0]!r}"
        )
        assert record.get("player_number") == player_number, (
            f"{holders[0].name} identity says player {record.get('player_number')}, records are player {player_number}"
        )
        assert record.get("role") == role_name, (
            f"{holders[0].name} identity role {record.get('role')!r} != {role_name!r}"
        )
        assert record.get("game_id") == GAME_ID, f"{holders[0].name} identity game {record.get('game_id')!r}"


@pytest.mark.asyncio
async def test_replacement_instance_keeps_actor_and_is_recorded_separately(config, tmp_path):
    """interface proposal: a replacement runner for seat 7 keeps player 7, keeps instance a's records, and
    records its own instance identifier (any identity field whose name contains 'instance')."""
    await GameRunner(
        config=config,
        agents=[
            make_agent(7, "speculator", marker_for(7, "a"), tmp_path),
            make_agent(8, "speculator", marker_for(8), tmp_path),
        ],
    ).run_game()
    await GameRunner(config=config, agents=[make_agent(7, "speculator", marker_for(7, "b"), tmp_path)]).run_game()

    records = {}
    for instance in ("a", "b"):
        holders = file_holding(config, marker_for(7, instance))
        assert len(holders) == 1, (
            f"instance {instance} of player 7 is in {[p.name for p in holders]} after the replacement runner "
            f"started (files: {[p.name for p in agent_logs(config)]}); the replacement erased its records"
        )
        record = identity_governing(holders[0], marker_for(7, instance))
        assert record is not None, f"{holders[0].name} (player 7, instance {instance}) has no identity record"
        assert record.get("player_number") == 7, f"instance {instance} recorded as player {record.get('player_number')}"
        assert record.get("role") == "speculator", f"instance {instance} recorded as role {record.get('role')!r}"
        records[instance] = record
    ids = {instance: instance_ids(record) for instance, record in records.items()}
    assert ids["a"] and ids["b"], f"identity records carry no instance identifier field: {ids}"
    assert ids["a"] != ids["b"], f"both instances of player 7 carry the same instance identifier: {ids}"


@pytest.mark.asyncio
async def test_log_names_and_tags_do_not_point_at_another_seat(config, tmp_path):
    """decision-gated (Dylan/Rutger: rename logs by player number, or keep names and make the header authoritative)."""
    await run_mixed_game(config, tmp_path)
    all_log = (game_dir(config) / "all.log").read_text(errors="replace")

    aliased = []
    for player_number, _ in AGENT_SEATS:
        for path in file_holding(config, marker_for(player_number)):
            match = re.fullmatch(r"agent_(\d+)\.log", path.name)
            if match and int(match.group(1)) != player_number:
                aliased.append(f"{path.name} holds player {player_number}")
        for line in all_log.splitlines():
            if marker_for(player_number) in line:
                tag = re.search(r"\[AGENT (\S+)\]", line)
                if tag and tag.group(1) != str(player_number):
                    aliased.append(f"all.log tags player {player_number} as [AGENT {tag.group(1)}]")
    assert aliased == [], "; ".join(aliased)


@pytest.mark.asyncio
async def test_agents_without_player_identity_keep_launch_index_logs(config, tmp_path):
    """guard: agents with no player number still log to agent_<launch index>.log."""
    agents = [make_agent(None, "speculator", f"anonymous-record {i}", tmp_path) for i in (1, 2)]
    await GameRunner(config=config, agents=agents).run_game()

    for index in (1, 2):
        path = game_dir(config) / f"agent_{index}.log"
        assert path.is_file(), f"missing {path.name}; files={[p.name for p in agent_logs(config)]}"
        assert f"anonymous-record {index}" in path.read_text(errors="replace")
