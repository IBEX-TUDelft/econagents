"""econagents.adapters.launch (ibex), used the way ibex's AgentService uses it.

The contract between AgentService and the launcher is duplicated on each side: ibex tests
AgentService against a mock agents program, and these tests drive the launcher with the
command lines AgentService sends, against a stand-in ibex server.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import pytest
import websockets

from econagents.adapters.llm.base import BaseLLM
from econagents.adapters.protocol import IbexMessageCodec
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.adapters.launch.ibex import (
    IbexGameSpec,
    IbexLaunchError,
    build_agent,
    build_config,
    build_parser,
    ibex_main,
    list_personas,
    parse_seats,
    run,
)
from econagents.personas import BUILTIN_LIBRARY, available_personas
from econagents.runtime import HybridGameRunnerConfig, TurnBasedGameRunnerConfig


class UnusedLLM(BaseLLM):
    async def get_response(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("no model call is expected")


class Prisoner(Role):
    role = 1
    name = "prisoner"
    llm = UnusedLLM()
    task_phases = ["decision"]

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.register_phase_handler("decision", self._decide)

    async def _decide(self, phase: Any, state: Any) -> dict:
        choice = "cooperate" if self.persona is None else self.persona.id
        return {
            "meta": {"type": "submit-choice", "component": {"type": "standard:coordination"}},
            "payload": {"choice": choice},
        }


class Guard(Prisoner):
    name = "guard"


def persona_yaml(folder: Path, persona_id: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{persona_id}.yaml").write_text(f"id: {persona_id}\nbio: test persona\n")


@pytest.fixture
def spec(tmp_path: Path) -> IbexGameSpec:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    personas = tmp_path / "personas"
    persona_yaml(personas, "tit_for_tat")
    persona_yaml(personas / "nested", "grim_trigger")
    return IbexGameSpec(
        game="prisoner_dilemma",
        state_cls=GameState,
        roles={"prisoner": Prisoner, "guard": Guard},
        prompts_dir=prompts,
        personas_dir=personas,
    )


def agent_service_argv(**overrides: Any) -> list[str]:
    """The command line AgentService sends for two seats."""
    flags: dict[str, Any] = {
        "game": "prisoner_dilemma",
        "game-id": "7",
        "hostname": "localhost",
        "port": "3000",
        "recovery-code": ["r1", "r2"],
        "player-number": ["1", "2"],
        "role": ["prisoner", "guard"],
        "persona": ["tit_for_tat", ""],
    }
    flags.update(overrides)
    argv: list[str] = []
    for flag, value in flags.items():
        if value is None:
            continue
        for v in value if isinstance(value, list) else [value]:
            argv += [f"--{flag}", v]
    return argv


def library_ids() -> set[str]:
    return {p.stem for p in BUILTIN_LIBRARY.rglob("*.yaml")}


# --- personas -----------------------------------------------------------------------------


def test_available_personas_lists_the_folder_then_the_library(tmp_path: Path) -> None:
    persona_yaml(tmp_path, "mine")
    shadow = sorted(library_ids())[0]
    persona_yaml(tmp_path, shadow)

    sources = available_personas(tmp_path)

    assert sources["mine"] == "user"
    assert sources[shadow] == "user"
    assert all(sources[pid] == "library" for pid in library_ids() - {shadow})
    assert list(sources) == sorted(sources)


def test_list_personas_answers_the_agent_service_query(spec: IbexGameSpec, capsys: pytest.CaptureFixture) -> None:
    assert ibex_main(spec, ["--game", "prisoner_dilemma", "--list-personas"]) == 0
    ids = json.loads(capsys.readouterr().out)
    assert {"tit_for_tat", "grim_trigger"} <= set(ids)
    assert library_ids() <= set(ids)

    assert ibex_main(spec, ["--game", "prisoner_dilemma", "--list-personas", "--with-source"]) == 0
    entries = json.loads(capsys.readouterr().out)
    by_id = {e["id"]: e["source"] for e in entries}
    assert by_id["tit_for_tat"] == "game"
    assert by_id["grim_trigger"] == "game"
    assert {by_id[i] for i in library_ids()} == {"library"}


def test_every_listed_persona_loads(spec: IbexGameSpec) -> None:
    from econagents.personas import load_persona

    for pid in list_personas(spec):
        assert load_persona(pid, user_dir=spec.personas_dir).id == pid


def test_another_game_is_refused(spec: IbexGameSpec, capsys: pytest.CaptureFixture) -> None:
    assert ibex_main(spec, ["--game", "futarchy", "--list-personas"]) == 2
    assert "prisoner_dilemma" in capsys.readouterr().err


# --- seats ---------------------------------------------------------------------------------


def test_seats_follow_the_recovery_codes(spec: IbexGameSpec) -> None:
    seats = parse_seats(spec, build_parser(spec).parse_args(agent_service_argv()))
    assert [(s.recovery, s.player_number, s.role, s.persona_id) for s in seats] == [
        ("r1", 1, "prisoner", "tit_for_tat"),
        ("r2", 2, "guard", None),
    ]


def test_personas_may_be_left_out(spec: IbexGameSpec) -> None:
    seats = parse_seats(spec, build_parser(spec).parse_args(agent_service_argv(persona=None)))
    assert [s.persona_id for s in seats] == [None, None]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"role": ["prisoner"]}, "every seat needs both"),
        ({"player-number": None}, "every seat needs both"),
        ({"persona": ["tit_for_tat"]}, "--persona"),
        ({"role": ["prisoner", "warden"]}, "warden"),
        ({"recovery-code": None, "player-number": None, "role": None, "persona": None}, "no --recovery-code"),
        ({"port": None}, "--port"),
    ],
)
def test_inconsistent_seats_are_refused(spec: IbexGameSpec, overrides: dict, message: str) -> None:
    with pytest.raises(IbexLaunchError, match=message):
        parse_seats(spec, build_parser(spec).parse_args(agent_service_argv(**overrides)))


def test_main_reports_a_bad_command_line(spec: IbexGameSpec, capsys: pytest.CaptureFixture) -> None:
    assert ibex_main(spec, agent_service_argv(role=["prisoner"])) == 2
    assert "every seat needs both" in capsys.readouterr().err


# --- configuration and agents ------------------------------------------------------------------


def test_turn_based_configuration_with_ibex_defaults(spec: IbexGameSpec, tmp_path: Path) -> None:
    args = build_parser(spec).parse_args(agent_service_argv() + ["--logs-dir", str(tmp_path / "out")])
    config = build_config(spec, args)

    assert isinstance(config, TurnBasedGameRunnerConfig)
    assert (config.game_id, config.hostname, config.port, config.path) == (7, "localhost", 3000, "")
    assert config.max_game_duration == 0
    assert (config.phase_transition_event, config.phase_identifier_key) == ("snapshot", "currentPhase")
    assert config.logs_dir.parent == tmp_path / "out"
    assert config.run_id

    again = build_config(spec, args)
    assert again.logs_dir != config.logs_dir
    assert again.run_id != config.run_id


def test_continuous_phases_give_a_hybrid_configuration(spec: IbexGameSpec) -> None:
    hybrid = IbexGameSpec(**{**spec.__dict__, "continuous_phases": frozenset({"market"})})
    config = build_config(
        hybrid, build_parser(hybrid).parse_args(agent_service_argv() + ["--min-delay", "1", "--max-delay", "2"])
    )
    assert isinstance(config, HybridGameRunnerConfig)
    assert config.continuous_phases == ["market"]
    assert (config.min_action_delay, config.max_action_delay) == (1, 2)


def test_each_seat_gets_its_role_persona_and_identity(spec: IbexGameSpec) -> None:
    hooked: list[tuple[int, str]] = []

    def agent_kwargs(seat: Any, config: Any, role: Role) -> dict:
        hooked.append((seat.player_number, role.name))
        return {"on_unknown": "continue"}

    spec = IbexGameSpec(**{**spec.__dict__, "agent_kwargs": agent_kwargs})
    args = build_parser(spec).parse_args(agent_service_argv())
    config = build_config(spec, args)
    agents = [build_agent(spec, config, seat) for seat in parse_seats(spec, args)]

    assert [type(a.role) for a in agents] == [Prisoner, Guard]
    assert agents[0].role.persona.id == "tit_for_tat"
    assert agents[1].role.persona is None
    assert [(a.state.meta.player_number, a.state.meta.role) for a in agents] == [(1, "prisoner"), (2, "guard")]
    assert all(isinstance(a.message_codec, IbexMessageCodec) for a in agents)
    assert hooked == [(1, "prisoner"), (2, "guard")]


# --- a game against a stand-in ibex server -------------------------------------------------


class StandInServer:
    """Plays the ibex side of one turn-based phase: join, snapshot on request, a decision, game over."""

    def __init__(self, recoveries: dict[str, int]):
        self.recoveries = recoveries
        self.received: list[dict] = []
        self.decided: set[int] = set()
        self.sockets: dict[int, Any] = {}

    async def handler(self, ws: Any) -> None:
        player: Optional[int] = None
        async for raw in ws:
            msg = json.loads(raw)
            self.received.append(msg)
            kind = msg["meta"]["type"]
            if kind == "join":
                assert set(msg["payload"]) == {"recovery"}, "ibex's JoinPayload accepts only the recovery code"
                player = self.recoveries[msg["payload"]["recovery"]]
                self.sockets[player] = ws
                await ws.send(json.dumps({"meta": {"type": "player-joined"}, "payload": {"playerNumber": player}}))
                await ws.send(
                    json.dumps({"meta": {"type": "phase-transition"}, "payload": {"phase": "decision", "round": 1}})
                )
            elif kind == "get-snapshot":
                await ws.send(
                    json.dumps(
                        {
                            "meta": {"type": "snapshot"},
                            "payload": {
                                "currentPhase": "decision",
                                "currentRound": 1,
                                "playerNumber": player,
                                "phaseSnapshot": [],
                            },
                        }
                    )
                )
            elif kind == "submit-choice":
                assert player is not None
                self.decided.add(player)
                if self.decided == set(self.recoveries.values()):
                    for sock in self.sockets.values():
                        await sock.send(json.dumps({"meta": {"type": "game-over"}, "payload": {}}))


@pytest.mark.asyncio
async def test_a_game_played_from_the_agent_service_command_line(spec: IbexGameSpec, tmp_path: Path) -> None:
    server = StandInServer({"r1": 1, "r2": 2})
    async with websockets.serve(server.handler, "127.0.0.1", 0) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        argv = agent_service_argv(hostname="127.0.0.1", port=str(port)) + ["--logs-dir", str(tmp_path / "logs")]
        args = build_parser(spec).parse_args(argv)
        await asyncio.wait_for(run(spec, args), timeout=20)

    choices = [m for m in server.received if m["meta"]["type"] == "submit-choice"]
    assert sorted(m["payload"]["choice"] for m in choices) == ["cooperate", "tit_for_tat"]
    assert [m["meta"]["type"] for m in server.received].count("get-snapshot") == 2
    runs = list((tmp_path / "logs").iterdir())
    assert len(runs) == 1 and (runs[0] / "game_7").is_dir()
