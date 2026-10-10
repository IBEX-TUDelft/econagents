"""Gameplay watchdog vs. pre-game waiting (IBEX-TUDelft/IBEX-game_suite#5).

Real ``Agent`` + ``GameRunner`` against an in-memory stand-in for the IBEX ``futharcy-agents``
server. The fake server reproduces the message flow that server emits for a futarchy game:

* the game is started before anyone joins, so it sits in ``introduction``;
* on join: ``player-joined`` to everyone, then a ``phase-transition`` replay to the joining socket;
  the agent answers its own ``player-joined`` with ``get-snapshot`` (as
  ``futarchy_agents.run_game.build_agent`` does) and gets a ``snapshot`` back;
* ``introduction`` ends only when every seat (agents and the human seat) sent ``ready``;
* every later phase: ``phase-transition`` broadcast, then one ``snapshot`` per player;
* finally ``game-over``.

Agents act on ``snapshot`` with ``currentPhase``, exactly as futarchy-agents configures them. The
clock checks also run with the econagents defaults (``phase-transition`` / ``phase``) against a
server that, like the econagents example servers, sends no per-phase ``snapshot`` (only the
``get-snapshot`` reply), so a fix must follow ``phase_transition_event`` / ``phase_identifier_key``
rather than hardcode the futarchy wiring.
The role is stubbed (no LLM): ``role.handle_phase`` calls record which phases each agent acted in.
Time is scaled down: a 0.5 s budget stands for the 780 s budget of Game 16.

Decided (Dylan): the gameplay clock is on by default, i.e. ``max_game_duration`` counts from the
first post-introduction phase without extra configuration, so ``GAMEPLAY_CLOCK_OPT_IN`` stays empty.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import Field

from econagents import Agent, GameRunner, HybridGameRunnerConfig, PhaseEngine
from econagents.domain.role import Role
from econagents.domain.state.fields import EventField
from econagents.domain.state.game import GameState, MetaInformation

GAME_ID = 16
PRE_GAME_PHASE = "introduction"
GAMEPLAY_PHASES = (
    "presentation",
    "declaration_first",
    "speculation_first",
    "transition",
    "transcription",
    "market",
    "declaration_final",
    "speculation_final",
    "results",
)
FINAL_PHASES = ("market", "declaration_final", "speculation_final", "results")
AGENT_SEATS = {1: "owner", 2: "speculator"}
HUMAN_SEAT = (3, "speculator")
GET_SNAPSHOT = json.dumps({"meta": {"type": "get-snapshot"}, "payload": {}})
RUN_TIMEOUT = 15.0

GAMEPLAY_CLOCK_OPT_IN: dict[str, Any] = {}

PHASE_SIGNALS = (
    pytest.param("snapshot", "currentPhase", True, id="futarchy-snapshot-currentPhase"),
    pytest.param("phase-transition", "phase", False, id="phase-transition-phase-no-phase-snapshots"),
)


def envelope(message_type: str, **payload: Any) -> str:
    return json.dumps({"meta": {"type": message_type}, "payload": payload})


class FakeConnection:
    """TransportPort for one seat, wired to the fake server."""

    def __init__(self, server: "FakeIbexServer", player_number: int) -> None:
        self.server = server
        self.player_number = player_number
        self.on_message = None
        self.closed = asyncio.Event()
        self.stopped_at: Optional[float] = None
        self.stopped_in_phase: Optional[str] = None
        self.game_over_received = False
        self.snapshot_phases: list[str] = []
        self.transition_phases: list[str] = []

    async def start_listening(self) -> None:
        await self.server.authenticate(self)
        await self.closed.wait()

    async def send(self, message: str) -> None:
        await self.server.receive(self, json.loads(message))

    async def stop(self) -> None:
        if self.stopped_at is None:
            self.stopped_at = self.server.now()
            self.stopped_in_phase = self.server.current_phase
        self.closed.set()

    async def push(self, raw: str) -> None:
        if self.closed.is_set() or self.on_message is None:
            return
        message = json.loads(raw)
        message_type = message["meta"]["type"]
        if message_type == "game-over":
            self.game_over_received = True
        elif message_type == "snapshot":
            self.snapshot_phases.append(message["payload"]["currentPhase"])
        elif message_type == "phase-transition":
            self.transition_phases.append(message["payload"]["phase"])
        await self.on_message(raw)


class FakeIbexServer:
    """Minimal futharcy-agents WebSocketService + GameInstance phase loop for one futarchy round."""

    def __init__(
        self,
        *,
        phase_seconds: dict[str, float],
        human_ready_after: Optional[float],
        human_join_after: Optional[float] = None,
        rejoins: tuple[tuple[str, float], ...] = (),
        per_phase_snapshots: bool = True,
    ) -> None:
        self.phase_seconds = phase_seconds
        self.per_phase_snapshots = per_phase_snapshots
        self.human_ready_after = human_ready_after
        self.human_join_after = human_ready_after if human_join_after is None else human_join_after
        self.rejoins = rejoins
        self.seats = {**AGENT_SEATS, HUMAN_SEAT[0]: HUMAN_SEAT[1]}
        self.connections: dict[int, FakeConnection] = {}
        self.joined: set[int] = set()
        self.ready: set[int] = set()
        self.all_ready = asyncio.Event()
        self.current_phase: Optional[str] = PRE_GAME_PHASE
        self.t0 = asyncio.get_running_loop().time()
        self.human_joined_at: Optional[float] = None
        self.human_ready_at: Optional[float] = None
        self.gameplay_started_at: Optional[float] = None
        self.game_over_at: Optional[float] = None
        self.rejoin_times: dict[str, float] = {}

    def now(self) -> float:
        return asyncio.get_running_loop().time() - self.t0

    def connection(self, player_number: int) -> FakeConnection:
        return FakeConnection(self, player_number)

    def snapshot_for(self, player_number: int) -> dict[str, Any]:
        phase_snapshot = []
        if self.current_phase == PRE_GAME_PHASE:
            phase_snapshot = [
                {
                    "key": {"type": "standard:ready"},
                    "value": {
                        "state": {"readyPlayers": sorted(self.ready), "totalExpected": len(self.seats)},
                        "configuration": {},
                    },
                }
            ]
        return {
            "currentRound": 1,
            "currentPhase": self.current_phase,
            "players": [
                {"playerNumber": number, "role": role, "recovery": f"recovery-{number}"}
                for number, role in sorted(self.seats.items())
            ],
            "properties": {"computed": {}, "primitive": {"conditions": ["project", "no_project"]}, "derived": {}},
            "results": [],
            "phaseSnapshot": phase_snapshot,
            "gameOver": False,
        }

    async def _broadcast_joined(self, player_number: int) -> None:
        self.joined.add(player_number)
        joined = envelope(
            "player-joined",
            playerNumber=player_number,
            role=self.seats[player_number],
            joinedPlayers=len(self.joined),
            totalPlayers=len(self.seats),
        )
        for other in list(self.connections.values()):
            await other.push(joined)

    async def authenticate(self, connection: FakeConnection) -> None:
        self.connections[connection.player_number] = connection
        await self._broadcast_joined(connection.player_number)
        await connection.push(
            envelope("phase-transition", round=1, phase=self.current_phase, transitionedAt=self._millis())
        )

    async def receive(self, connection: FakeConnection, message: dict[str, Any]) -> None:
        message_type = message.get("meta", {}).get("type")
        if message_type == "get-snapshot":
            await connection.push(envelope("snapshot", **self.snapshot_for(connection.player_number)))
        elif message_type == "ready" and self.current_phase == PRE_GAME_PHASE:
            self._mark_ready(connection.player_number)

    def _mark_ready(self, player_number: int) -> None:
        self.ready.add(player_number)
        if self.ready >= set(self.seats):
            self.all_ready.set()

    @staticmethod
    def _millis() -> int:
        return int(time.time() * 1000)

    async def _rejoin_everyone(self, label: str) -> None:
        self.rejoin_times[label] = self.now()
        for connection in list(self.connections.values()):
            if not connection.closed.is_set():
                await self.authenticate(connection)

    async def _human(self) -> None:
        if self.human_join_after is not None:
            await asyncio.sleep(self.human_join_after)
            self.human_joined_at = self.now()
            await self._broadcast_joined(HUMAN_SEAT[0])
        if self.human_ready_after is None:
            return
        await asyncio.sleep(max(0.0, self.human_ready_after - self.now()))
        self.human_ready_at = self.now()
        self._mark_ready(HUMAN_SEAT[0])

    async def _pre_game_rejoins(self) -> None:
        for phase, at in self.rejoins:
            if phase == PRE_GAME_PHASE:
                await asyncio.sleep(max(0.0, at - self.now()))
                if self.current_phase == PRE_GAME_PHASE:
                    await self._rejoin_everyone(PRE_GAME_PHASE)

    async def run(self) -> None:
        helpers = [asyncio.create_task(self._human()), asyncio.create_task(self._pre_game_rejoins())]
        try:
            await self.all_ready.wait()
            for phase in GAMEPLAY_PHASES:
                self.current_phase = phase
                if self.gameplay_started_at is None:
                    self.gameplay_started_at = self.now()
                phase_started = self.now()
                transition = envelope("phase-transition", round=1, phase=phase, transitionedAt=self._millis())
                for connection in list(self.connections.values()):
                    await connection.push(transition)
                if self.per_phase_snapshots:
                    for connection in list(self.connections.values()):
                        await connection.push(envelope("snapshot", **self.snapshot_for(connection.player_number)))
                for rejoin_phase, offset in self.rejoins:
                    if rejoin_phase == phase:
                        await asyncio.sleep(max(0.0, phase_started + offset - self.now()))
                        await self._rejoin_everyone(phase)
                await asyncio.sleep(max(0.0, phase_started + self.phase_seconds[phase] - self.now()))
            self.current_phase = None
            self.game_over_at = self.now()
            for connection in list(self.connections.values()):
                await connection.push(envelope("game-over"))
        finally:
            for helper in helpers:
                helper.cancel()


@dataclass
class SeatOutcome:
    player_number: int
    acted_phases: list[str]
    snapshot_phases: list[str]
    transition_phases: list[str]
    stopped_at: Optional[float]
    stopped_in_phase: Optional[str]
    game_over_received: bool

    @property
    def missing_gameplay_phases(self) -> list[str]:
        return [phase for phase in GAMEPLAY_PHASES if phase not in self.acted_phases]

    @property
    def stopped_by_runner(self) -> bool:
        return not self.game_over_received


@dataclass
class GameOutcome:
    runner: GameRunner
    server: FakeIbexServer
    budget: float
    seats: dict[int, SeatOutcome] = field(default_factory=dict)
    records: list[logging.LogRecord] = field(default_factory=list)

    def messages(self, min_level: int = logging.DEBUG) -> list[str]:
        return [record.getMessage() for record in self.records if record.levelno >= min_level]

    def describe(self, seat: SeatOutcome) -> str:
        server = self.server
        stop = "never stopped" if seat.stopped_at is None else f"stopped at +{seat.stopped_at:.2f}s"
        how = (
            "by game-over"
            if seat.game_over_received
            else f"by the runner while the server was in {seat.stopped_in_phase!r}"
        )
        joined = "" if server.human_joined_at is None else f"joined at +{server.human_joined_at:.2f}s, "
        if server.human_ready_at is not None:
            human = f"{joined}ready at +{server.human_ready_at:.2f}s"
        elif server.human_ready_after is not None:
            human = f"{joined}not ready yet (scheduled for +{server.human_ready_after:.2f}s)"
        else:
            human = f"{joined}never ready"
        gameplay = "not yet" if server.gameplay_started_at is None else f"+{server.gameplay_started_at:.2f}s"
        return (
            f"agent {seat.player_number}: {stop} {how}; acted in {seat.acted_phases}; "
            f"human seat {human}; gameplay (presentation) started {gameplay}; budget {self.budget}s"
        )


def build_agent(
    server: FakeIbexServer, player_number: int, prompts_dir: Path, phase_signal: tuple[str, str]
) -> tuple[Agent, FakeConnection]:
    connection = server.connection(player_number)
    role = MagicMock(spec=Role)
    role.name = AGENT_SEATS[player_number]
    role.handle_phase = AsyncMock(return_value=None)
    agent = Agent(
        url="ws://ibex.invalid",
        state=GameState(),
        role=role,
        prompts_dir=prompts_dir,
        transport=connection,
        phase_transition_event=phase_signal[0],
        phase_identifier_key=phase_signal[1],
        phase_engine=PhaseEngine(),
        auth_mechanism_kwargs={"recovery": f"recovery-{player_number}"},
    )
    connection.on_message = agent._raw_message_received

    async def request_snapshot(event) -> None:
        if event.data.get("playerNumber") == player_number:
            await agent.transport.send(GET_SNAPSHOT)

    agent.register_event_handler("player-joined", request_snapshot)
    return agent, connection


def runner_config(
    tmp_path: Path, budget: float, phase_signal: tuple[str, str], **extra: float
) -> HybridGameRunnerConfig:
    config = HybridGameRunnerConfig(
        game_id=GAME_ID,
        hostname="localhost",
        port=0,
        path="",
        logs_dir=tmp_path / "logs",
        prompts_dir=tmp_path,
        phase_transition_event=phase_signal[0],
        phase_identifier_key=phase_signal[1],
        continuous_phases=["market"],
    )
    config.max_game_duration = budget
    for name, value in GAMEPLAY_CLOCK_OPT_IN.items():
        setattr(config, name, value)
    for name, value in extra.items():
        if name in type(config).model_fields:
            setattr(config, name, value)
    return config


def phase_plan(default: float, **overrides: float) -> dict[str, float]:
    return {phase: overrides.get(phase, default) for phase in GAMEPLAY_PHASES}


async def play_game(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    *,
    budget: float,
    human_ready_after: Optional[float],
    phase_seconds: dict[str, float],
    human_join_after: Optional[float] = None,
    rejoins: tuple[tuple[str, float], ...] = (),
    phase_signal: tuple[str, str] = ("snapshot", "currentPhase"),
    per_phase_snapshots: bool = True,
    **config_extra: float,
) -> GameOutcome:
    caplog.set_level(logging.DEBUG)
    server = FakeIbexServer(
        phase_seconds=phase_seconds,
        human_ready_after=human_ready_after,
        human_join_after=human_join_after,
        rejoins=rejoins,
        per_phase_snapshots=per_phase_snapshots,
    )
    built = [build_agent(server, number, tmp_path, phase_signal) for number in AGENT_SEATS]
    config = runner_config(tmp_path, budget, phase_signal, **config_extra)
    runner = GameRunner(config=config, agents=[agent for agent, _ in built])

    server_task = asyncio.create_task(server.run())
    try:
        await asyncio.wait_for(runner.run_game(), timeout=RUN_TIMEOUT)
    finally:
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)

    outcome = GameOutcome(runner=runner, server=server, budget=budget, records=list(caplog.records))
    for agent, connection in built:
        acted = []
        for call in agent.role.handle_phase.call_args_list:
            if call.args[0] not in acted:
                acted.append(call.args[0])
        outcome.seats[connection.player_number] = SeatOutcome(
            player_number=connection.player_number,
            acted_phases=acted,
            snapshot_phases=connection.snapshot_phases,
            transition_phases=connection.transition_phases,
            stopped_at=connection.stopped_at,
            stopped_in_phase=connection.stopped_in_phase,
            game_over_received=connection.game_over_received,
        )
    return outcome


# --- (a) Behavioural bug checks: fail on main, must pass after the fix -------------------------
# (assume the gameplay clock is on by default; see GAMEPLAY_CLOCK_OPT_IN)


@pytest.mark.asyncio
@pytest.mark.parametrize(("event", "key", "per_phase_snapshots"), PHASE_SIGNALS)
async def test_pre_game_wait_does_not_consume_gameplay_budget(tmp_path, caplog, event, key, per_phase_snapshots):
    """Game 16, scaled: the human joins at +0.2 s (every seat joined) but readies only after 3x the
    budget; gameplay itself takes ~0.3 s < budget. Neither the run start nor the last join may
    start the gameplay clock."""
    budget = 0.5
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_join_after=0.2,
        human_ready_after=1.5,
        phase_seconds=phase_plan(0.03),
        rejoins=((PRE_GAME_PHASE, 0.25),),
        phase_signal=(event, key),
        per_phase_snapshots=per_phase_snapshots,
    )

    for seat in outcome.seats.values():
        assert not seat.missing_gameplay_phases, (
            f"waiting for the human consumed the gameplay budget: agent {seat.player_number} never acted in "
            f"{seat.missing_gameplay_phases}. {outcome.describe(seat)}"
        )
        assert seat.game_over_received, f"agent was stopped before game-over. {outcome.describe(seat)}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("event", "key", "per_phase_snapshots"), PHASE_SIGNALS)
async def test_duplicate_snapshots_and_rejoin_do_not_restart_gameplay_clock(
    tmp_path, caplog, event, key, per_phase_snapshots
):
    """The clock starts once, at presentation; an introduction re-join and a market re-join
    (player-joined + phase-transition replay + get-snapshot reply) must neither start nor restart it.
    Gameplay (~2 s) is longer than the budget, so the watchdog must fire budget seconds after
    presentation began (window [0.8, 1.1] s). Wrong clocks land well outside that window: run start
    (fires in introduction), last join (+0.15 s, fires in introduction), introduction re-join
    (~0 s), re-armed per phase at market (+0.55 s -> ~1.45 s) or at the market re-join
    (+0.60 s -> ~1.5 s)."""
    budget = 0.9
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_join_after=0.15,
        human_ready_after=1.2,
        phase_seconds=phase_plan(
            0.2, declaration_first=0.15, speculation_first=0.1, transition=0.05, transcription=0.05, market=1.5
        ),
        rejoins=((PRE_GAME_PHASE, 0.3), ("market", 0.05)),
        phase_signal=(event, key),
        per_phase_snapshots=per_phase_snapshots,
    )
    started = outcome.server.gameplay_started_at

    for seat in outcome.seats.values():
        assert seat.stopped_by_runner and seat.stopped_at is not None, (
            f"gameplay is longer than the budget, the watchdog should have stopped the agent. {outcome.describe(seat)}"
        )
        assert started is not None and seat.stopped_at >= started, (
            f"gameplay watchdog stopped the agent during introduction, before gameplay started. "
            f"{outcome.describe(seat)}"
        )
        fired_after = seat.stopped_at - started
        assert budget - 0.1 <= fired_after <= budget + 0.2, (
            f"gameplay watchdog fired {fired_after:+.2f}s after gameplay started, expected {budget}s "
            f"(clock must start once at presentation; market re-join at "
            f"+{outcome.server.rejoin_times.get('market', float('nan')):.2f}s must not restart it). "
            f"{outcome.describe(seat)}"
        )
        signals = seat.snapshot_phases if event == "snapshot" else seat.transition_phases
        assert signals.count("market") >= 2, (
            f"agent {seat.player_number} did not see a duplicate market {event}: {signals}"
        )
        assert signals.count(PRE_GAME_PHASE) >= 2, (
            f"agent {seat.player_number} did not see a duplicate introduction {event}: {signals}"
        )


# --- Guards: pass on main, must still pass after the fix -----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("event", "key", "per_phase_snapshots"), PHASE_SIGNALS)
async def test_genuine_gameplay_timeout_still_stops_agents(tmp_path, caplog, event, key, per_phase_snapshots):
    """No pre-game wait, gameplay (market alone 2 s) longer than the budget: agents are stopped
    about budget seconds into gameplay, never reach the final phases, and a warning names the budget."""
    budget = 0.5
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_ready_after=0.0,
        phase_seconds=phase_plan(0.05, market=2.0),
        phase_signal=(event, key),
        per_phase_snapshots=per_phase_snapshots,
    )
    started = outcome.server.gameplay_started_at
    assert started is not None, "fake server never left introduction"

    for seat in outcome.seats.values():
        assert seat.stopped_by_runner and seat.stopped_at is not None, (
            f"the gameplay watchdog did not stop the agent. {outcome.describe(seat)}"
        )
        fired_after = seat.stopped_at - started
        assert budget - 0.15 <= fired_after <= budget + 0.3, (
            f"gameplay watchdog fired {fired_after:+.2f}s after gameplay started, expected ~{budget}s. "
            f"{outcome.describe(seat)}"
        )
        assert seat.stopped_in_phase == "market", outcome.describe(seat)
        assert "results" not in seat.acted_phases, outcome.describe(seat)

    warnings = outcome.messages(logging.WARNING)
    assert any(re.search(rf"\b{budget}\s*s", message) for message in warnings), (
        f"no warning names the {budget}s budget: {warnings}"
    )


@pytest.mark.asyncio
async def test_game_over_within_budget_is_not_a_timeout(tmp_path, caplog):
    budget = 1.5
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_ready_after=0.0,
        phase_seconds=phase_plan(0.03),
    )

    for seat in outcome.seats.values():
        assert not seat.missing_gameplay_phases, outcome.describe(seat)
        assert seat.game_over_received, outcome.describe(seat)


# --- (b) Interface proposal: how the runner reports the gameplay clock --------------------------


@pytest.mark.asyncio
async def test_proposal_gameplay_start_is_logged_once(tmp_path, caplog):
    """Proposal: one 'Gameplay started' log record naming the first gameplay phase, despite the
    duplicate introduction/market snapshots."""
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=1.5,
        human_ready_after=0.3,
        phase_seconds=phase_plan(0.03),
        rejoins=((PRE_GAME_PHASE, 0.1), ("market", 0.01)),
    )

    started = [message for message in outcome.messages() if "gameplay started" in message.lower()]
    assert len(started) == 1 and "presentation" in started[0], (
        f"expected exactly one 'Gameplay started' record naming 'presentation', got {len(started)}: {started}"
    )


@pytest.mark.asyncio
async def test_proposal_gameplay_timeout_is_reported_as_gameplay(tmp_path, caplog):
    """Proposal: a gameplay timeout is logged as such (budget and start phase) and exposed as
    ``runner.timeout_reason == "gameplay"``; it never mentions the pre-game wait."""
    budget = 0.5
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_ready_after=0.2,
        phase_seconds=phase_plan(0.05, market=2.0),
    )

    warnings = outcome.messages(logging.WARNING)
    gameplay_timeouts = [m for m in warnings if "gameplay" in m.lower() and str(budget) in m and "presentation" in m]
    assert gameplay_timeouts, f"no gameplay-timeout warning naming the {budget}s budget and 'presentation': {warnings}"
    assert not [m for m in warnings if "pre-game" in m.lower()], f"gameplay timeout logged as pre-game: {warnings}"
    reason = getattr(outcome.runner, "timeout_reason", "<no timeout_reason attribute>")
    assert reason == "gameplay", f"runner.timeout_reason is {reason!r}, expected 'gameplay'"


# --- (c) Gated on a decision: a separate pre-game (join/ready) timeout ---------------------------


@pytest.mark.asyncio
async def test_decision_pre_game_wait_has_its_own_timeout(tmp_path, caplog):
    """Decision needed (name, default, whether it exists at all): ``max_pre_game_duration``.
    The human never readies; the run must end after the pre-game budget (0.8 s), not the gameplay
    budget (0.3 s), with a distinct 'pre-game' warning and ``timeout_reason == "pre_game"``."""
    pre_game_budget = 0.8
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=0.3,
        human_ready_after=None,
        phase_seconds=phase_plan(0.03),
        max_pre_game_duration=pre_game_budget,
    )

    for seat in outcome.seats.values():
        assert seat.stopped_by_runner and seat.stopped_at is not None, outcome.describe(seat)
        assert pre_game_budget - 0.1 <= seat.stopped_at <= pre_game_budget + 0.3, (
            f"run stopped at +{seat.stopped_at:.2f}s while waiting in introduction; expected the "
            f"{pre_game_budget}s pre-game budget, not the 0.3s gameplay budget. {outcome.describe(seat)}"
        )

    warnings = outcome.messages(logging.WARNING)
    assert [m for m in warnings if "pre-game" in m.lower()], f"no distinct pre-game timeout warning: {warnings}"
    assert not [m for m in warnings if "gameplay" in m.lower()], f"pre-game timeout logged as gameplay: {warnings}"
    reason = getattr(outcome.runner, "timeout_reason", "<no timeout_reason attribute>")
    assert reason == "pre_game", f"runner.timeout_reason is {reason!r}, expected 'pre_game'"


# --- Later rounds: a second introduction pauses the gameplay clock ------------------------------

ROUND_KEYS = (
    pytest.param("snapshot", "currentPhase", True, "currentRound", id="futarchy-snapshot-currentPhase"),
    pytest.param("phase-transition", "phase", False, "round", id="phase-transition-phase-no-phase-snapshots"),
)


class MultiRoundFakeIbexServer(FakeIbexServer):
    """The same flow over several rounds; every round starts in ``introduction`` and waits for every ready.
    The human seat readies ``human_ready_after[round]`` seconds after that round's introduction began."""

    def __init__(self, *, rounds: int, human_ready_after: dict[int, float], **kwargs: Any) -> None:
        super().__init__(human_ready_after=None, human_join_after=0.0, **kwargs)
        self.rounds = rounds
        self.round_ready_after = human_ready_after
        self.current_round = 1
        self.round_started_at: dict[int, float] = {}

    def snapshot_for(self, player_number: int) -> dict[str, Any]:
        return {**super().snapshot_for(player_number), "currentRound": self.current_round}

    async def authenticate(self, connection: FakeConnection) -> None:
        self.connections[connection.player_number] = connection
        await self._broadcast_joined(connection.player_number)
        await connection.push(
            envelope(
                "phase-transition", round=self.current_round, phase=self.current_phase, transitionedAt=self._millis()
            )
        )

    async def _enter_phase(self, phase: str) -> None:
        self.current_phase = phase
        transition = envelope("phase-transition", round=self.current_round, phase=phase, transitionedAt=self._millis())
        for connection in list(self.connections.values()):
            await connection.push(transition)
        if self.per_phase_snapshots:
            for connection in list(self.connections.values()):
                await connection.push(envelope("snapshot", **self.snapshot_for(connection.player_number)))

    async def _human_ready(self, round_number: int) -> None:
        await asyncio.sleep(self.round_ready_after[round_number])
        self._mark_ready(HUMAN_SEAT[0])

    async def run(self) -> None:
        human = asyncio.create_task(self._human())
        await asyncio.sleep(0)
        try:
            for round_number in range(1, self.rounds + 1):
                self.current_round = round_number
                self.round_started_at[round_number] = self.now()
                self.ready = set()
                self.all_ready = asyncio.Event()
                if round_number > 1:
                    await self._enter_phase(PRE_GAME_PHASE)
                ready = asyncio.create_task(self._human_ready(round_number))
                try:
                    await self.all_ready.wait()
                finally:
                    ready.cancel()
                for phase in GAMEPLAY_PHASES:
                    if self.gameplay_started_at is None:
                        self.gameplay_started_at = self.now()
                    phase_started = self.now()
                    await self._enter_phase(phase)
                    await asyncio.sleep(max(0.0, phase_started + self.phase_seconds[phase] - self.now()))
            self.current_phase = None
            self.game_over_at = self.now()
            for connection in list(self.connections.values()):
                await connection.push(envelope("game-over"))
        finally:
            human.cancel()


async def play_rounds(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    *,
    budget: float,
    human_ready_after: dict[int, float],
    phase_seconds: dict[str, float],
    phase_signal: tuple[str, str],
    per_phase_snapshots: bool,
    round_key: str,
) -> tuple[GameRunner, MultiRoundFakeIbexServer, list[tuple[Agent, FakeConnection]]]:
    """Two rounds; agents keep ``meta.round`` from ``round_key`` so each round's phases are new occurrences."""
    caplog.set_level(logging.DEBUG)

    class RoundMeta(MetaInformation):
        round: int = EventField(default=0, event_key=round_key)

    class RoundState(GameState):
        meta: RoundMeta = Field(default_factory=RoundMeta)

    server = MultiRoundFakeIbexServer(
        rounds=len(human_ready_after),
        human_ready_after=human_ready_after,
        phase_seconds=phase_seconds,
        per_phase_snapshots=per_phase_snapshots,
    )
    built = [build_agent(server, number, tmp_path, phase_signal) for number in AGENT_SEATS]
    for agent, _ in built:
        agent.state = RoundState()
    runner = GameRunner(config=runner_config(tmp_path, budget, phase_signal), agents=[agent for agent, _ in built])

    server_task = asyncio.create_task(server.run())
    try:
        await asyncio.wait_for(runner.run_game(), timeout=RUN_TIMEOUT)
    finally:
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)
    return runner, server, built


def phase_calls(agent: Agent, phase: str) -> int:
    return sum(1 for call in agent.role.handle_phase.call_args_list if call.args[0] == phase)


@pytest.mark.asyncio
@pytest.mark.parametrize(("event", "key", "per_phase_snapshots", "round_key"), ROUND_KEYS)
async def test_second_round_introduction_does_not_consume_gameplay_budget(
    tmp_path, caplog, event, key, per_phase_snapshots, round_key
):
    """Two rounds of ~0.18 s gameplay each (0.36 s < 0.6 s budget); the human readies the second
    round's introduction only after 1.5 s. The second introduction pauses the clock, so every agent
    plays both rounds and stops on game-over."""
    runner, server, built = await play_rounds(
        tmp_path,
        caplog,
        budget=0.6,
        human_ready_after={1: 0.05, 2: 1.5},
        phase_seconds=phase_plan(0.02),
        phase_signal=(event, key),
        per_phase_snapshots=per_phase_snapshots,
        round_key=round_key,
    )

    for agent, connection in built:
        assert connection.game_over_received, (
            f"agent {connection.player_number} was stopped at +{connection.stopped_at:.2f}s in "
            f"{connection.stopped_in_phase!r} (round 2 introduction began at +{server.round_started_at[2]:.2f}s)"
        )
        assert phase_calls(agent, "results") == 2, agent.role.handle_phase.call_args_list
    assert runner.timeout_reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("event", "key", "per_phase_snapshots", "round_key"), ROUND_KEYS)
async def test_gameplay_budget_accumulates_across_rounds(tmp_path, caplog, event, key, per_phase_snapshots, round_key):
    """The clock pauses but never resets: two rounds of ~0.36 s gameplay with a 1 s second
    introduction exceed the 0.5 s budget in the second round's gameplay, ~0.14 s after it began."""
    budget = 0.5
    runner, server, built = await play_rounds(
        tmp_path,
        caplog,
        budget=budget,
        human_ready_after={1: 0.05, 2: 1.0},
        phase_seconds=phase_plan(0.04),
        phase_signal=(event, key),
        per_phase_snapshots=per_phase_snapshots,
        round_key=round_key,
    )

    assert runner.timeout_reason == "gameplay"
    for _, connection in built:
        assert not connection.game_over_received
        assert connection.stopped_at is not None and connection.stopped_at > server.round_started_at[2] + 1.0, (
            f"stopped at +{connection.stopped_at}s in {connection.stopped_in_phase!r}; round 2 introduction began at "
            f"+{server.round_started_at[2]:.2f}s and lasted ~1 s"
        )
        assert connection.stopped_in_phase in GAMEPLAY_PHASES[:5], connection.stopped_in_phase
