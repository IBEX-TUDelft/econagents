"""Run a game's agents the way ibex's AgentService spawns them.

A game's agents are one Python program that calls :func:`main` with the game's
:class:`GameSpec`. ibex starts it once per game, for every agent seat at once,
and never lets it create, start or claim a game: every seat's identity arrives
on the command line, one value per seat, in the same order::

    --game <type> --game-id <id> --hostname <h> --port <p>
    --recovery-code <r1> --recovery-code <r2> ...
    --player-number <n1> --player-number <n2> ...
    --role <role1> --role <role2> ...
    [--persona <p1> --persona <p2> ...]   ("" for a seat without one)
    [--logs-dir <folder>]

Before a game starts, ibex asks which personas exist::

    --game <type> --list-personas [--with-source]

which prints a JSON array of ids, or of ``{"id", "source": "game" | "library"}``.

Every agent gets ibex's defaults: the snapshot as phase-transition event,
``currentPhase`` as phase key, ``JoinPayloadAuth`` with the seat's recovery code,
no game watchdog (the server ends the process at game over), and a logs folder
of its own per run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from econagents.adapters.protocol import IbexMessageCodec
from econagents.adapters.transport import JoinPayloadAuth
from econagents.domain.messages import Event
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.personas import available_personas, load_persona
from econagents.ports.codec import MessageCodec
from econagents.runtime import (
    Agent,
    GameRunner,
    HybridGameRunnerConfig,
    PhaseEngine,
    TurnBasedGameRunnerConfig,
    create_game_state,
)

RunnerConfig = Union[HybridGameRunnerConfig, TurnBasedGameRunnerConfig]

GET_SNAPSHOT = json.dumps({"meta": {"type": "get-snapshot"}, "payload": {}})


@dataclass(frozen=True)
class Seat:
    """One agent seat, as the server claimed it."""

    recovery: str
    player_number: int
    role: str
    persona_id: Optional[str]


@dataclass(frozen=True)
class GameSpec:
    """What one game's agents are made of.

    ``roles`` maps the server's role names to ``Role`` classes; each is built with
    ``persona=`` (the seat's persona, or ``None``). A game with ``continuous_phases``
    runs on ``HybridGameRunnerConfig`` with a ``PhaseEngine`` (and accepts
    ``--min-delay``/``--max-delay``), any other on ``TurnBasedGameRunnerConfig``.

    ``agent_kwargs(seat, config, role)`` returns extra ``Agent`` arguments for a
    seat (``decision_gate``, ``disposition_tracker``, ``decision_trace``, ...).
    """

    game: str
    state_cls: type[GameState]
    roles: Mapping[str, type[Role]]
    prompts_dir: Path
    personas_dir: Optional[Path] = None
    continuous_phases: frozenset[str] = frozenset()
    action_delays: tuple[int, int] = (3, 8)
    message_codec: Callable[[], MessageCodec] = IbexMessageCodec
    agent_kwargs: Optional[Callable[[Seat, RunnerConfig, Role], dict[str, Any]]] = None
    description: Optional[str] = None

    @property
    def hybrid(self) -> bool:
        return bool(self.continuous_phases)


class LaunchError(Exception):
    """The command line does not describe the seats of a game this program plays."""


def list_personas(spec: GameSpec, with_source: bool = False) -> list[Any]:
    """The persona ids a seat of this game may ask for, sorted (``--list-personas``)."""
    sources = available_personas(spec.personas_dir)
    if not with_source:
        return list(sources)
    return [{"id": pid, "source": "game" if source == "user" else "library"} for pid, source in sources.items()]


def build_parser(spec: GameSpec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"{spec.game} agents",
        description=spec.description or __doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--game", default=None, help=f"The game type; must be {spec.game!r} when given.")
    parser.add_argument("--list-personas", action="store_true", help="Print the persona ids as JSON and exit.")
    parser.add_argument("--with-source", action="store_true", help='With --list-personas: [{"id", "source"}].')
    parser.add_argument("--game-id")
    parser.add_argument("--hostname")
    parser.add_argument("--port", type=int)
    parser.add_argument("--recovery-code", dest="recovery_codes", action="append", default=[])
    parser.add_argument("--player-number", dest="player_numbers", action="append", default=[])
    parser.add_argument("--role", dest="roles", action="append", default=[])
    parser.add_argument("--persona", dest="personas", action="append", default=[])
    parser.add_argument("--logs-dir", type=Path, default=None, help="Where this run's logs go (default: ./logs).")
    parser.add_argument("--log-level", default="INFO")
    min_delay, max_delay = spec.action_delays
    parser.add_argument(
        "--min-delay", type=int, default=min_delay, help="Continuous phases: min seconds between actions."
    )
    parser.add_argument(
        "--max-delay", type=int, default=max_delay, help="Continuous phases: max seconds between actions."
    )
    return parser


def parse_seats(spec: GameSpec, args: argparse.Namespace) -> list[Seat]:
    """One seat per ``--recovery-code``; the other per-seat lists must match it."""
    missing = [flag for flag in ("game_id", "hostname", "port") if getattr(args, flag) is None]
    if missing:
        raise LaunchError("missing " + ", ".join("--" + m.replace("_", "-") for m in missing))
    n = len(args.recovery_codes)
    if n == 0:
        raise LaunchError("no --recovery-code: there is no seat to play")
    if len(args.player_numbers) != n or len(args.roles) != n:
        raise LaunchError(
            f"{n} seat(s) but {len(args.player_numbers)} --player-number and {len(args.roles)} --role: "
            "every seat needs both"
        )
    personas = args.personas or [""] * n
    if len(personas) != n:
        raise LaunchError(f'{n} seat(s) but {len(personas)} --persona: give one per seat ("" for none)')
    seats = [
        Seat(recovery=r, player_number=int(pn), role=role, persona_id=persona or None)
        for r, pn, role, persona in zip(args.recovery_codes, args.player_numbers, args.roles, personas)
    ]
    unknown = sorted({s.role for s in seats if s.role not in spec.roles})
    if unknown:
        raise LaunchError(f"no Role for server role(s) {', '.join(unknown)} (known: {', '.join(sorted(spec.roles))})")
    return seats


def run_logs_dir(base: Path, game_id: int) -> Path:
    """A folder of its own for each run: game ids restart with a fresh server database."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / f"{stamp}-game{game_id}-{uuid.uuid4().hex[:6]}"


def build_config(spec: GameSpec, args: argparse.Namespace) -> RunnerConfig:
    game_id = int(args.game_id)
    common: dict[str, Any] = dict(
        game_id=game_id,
        hostname=args.hostname,
        port=args.port,
        path="",
        prompts_dir=spec.prompts_dir,
        logs_dir=run_logs_dir(args.logs_dir or Path.cwd() / "logs", game_id),
        log_level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        max_game_duration=0,
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        run_id=str(uuid.uuid4()),
    )
    if spec.hybrid:
        return HybridGameRunnerConfig(
            **common,
            continuous_phases=sorted(spec.continuous_phases),
            min_action_delay=args.min_delay,
            max_action_delay=args.max_delay,
        )
    return TurnBasedGameRunnerConfig(**common)


def build_agent(spec: GameSpec, config: RunnerConfig, seat: Seat) -> Agent:
    persona = load_persona(seat.persona_id, user_dir=spec.personas_dir) if seat.persona_id else None
    role = spec.roles[seat.role](persona=persona)

    state = create_game_state(spec.state_cls, game_id=config.game_id)
    state.meta.player_number = seat.player_number
    state.meta.role = seat.role

    phase_engine = None
    if isinstance(config, HybridGameRunnerConfig):
        phase_engine = PhaseEngine(
            continuous_phases=set(spec.continuous_phases),
            min_action_delay=config.min_action_delay,
            max_action_delay=config.max_action_delay,
        )

    kwargs: dict[str, Any] = dict(
        url=config.server_url(),
        state=state,
        role=role,
        prompts_dir=config.prompts_dir,
        message_codec=spec.message_codec(),
        auth_mechanism=JoinPayloadAuth(),
        auth_mechanism_kwargs={"recovery": seat.recovery},
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=phase_engine,
        end_game_event=config.end_game_event,
    )
    if spec.agent_kwargs is not None:
        kwargs.update(spec.agent_kwargs(seat, config, role))
    agent = Agent(**kwargs)

    # The introduction's snapshot is pushed before a spawned process has joined, and on
    # join the server replays only a bare phase-transition: ask for the snapshot once our
    # own join is announced.
    async def request_snapshot(event: Event) -> None:
        if event.data.get("playerNumber") == seat.player_number:
            await agent.transport.send(GET_SNAPSHOT)

    agent.register_event_handler("player-joined", request_snapshot)
    return agent


async def run(spec: GameSpec, args: argparse.Namespace) -> None:
    config = build_config(spec, args)
    agents = [build_agent(spec, config, seat) for seat in parse_seats(spec, args)]
    await GameRunner(config=config, agents=agents).run_game()


def main(spec: GameSpec, argv: Optional[Sequence[str]] = None) -> int:
    """The agents program's entry point: answers ``--list-personas`` or plays the seats."""
    parser = build_parser(spec)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.game is not None and args.game != spec.game:
        print(f"These agents play {spec.game!r}, not {args.game!r}.", file=sys.stderr)
        return 2
    if args.list_personas:
        print(json.dumps(list_personas(spec, with_source=args.with_source)))
        return 0
    try:
        parse_seats(spec, args)
    except LaunchError as e:
        print(f"{spec.game} agents: {e}.", file=sys.stderr)
        return 2
    asyncio.run(run(spec, args))
    return 0


__all__ = [
    "GameSpec",
    "LaunchError",
    "RunnerConfig",
    "Seat",
    "build_agent",
    "build_config",
    "build_parser",
    "list_personas",
    "main",
    "parse_seats",
    "run",
]
