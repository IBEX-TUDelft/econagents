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
role is stubbed (no LLM): ``role.handle_phase`` calls record which phases each agent acted in.
Time is scaled down: a 0.5 s budget stands for the 780 s budget of Game 16.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from econagents import Agent, GameRunner, HybridGameRunnerConfig, PhaseEngine
from econagents.domain.role import Role
from econagents.domain.state.game import GameState

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
        await self.on_message(raw)


class FakeIbexServer:
    """Minimal futharcy-agents WebSocketService + GameInstance phase loop for one futarchy round."""

    def __init__(
        self,
        *,
        phase_seconds: dict[str, float],
        human_ready_after: Optional[float],
        rejoins: tuple[tuple[str, float], ...] = (),
    ) -> None:
        self.phase_seconds = phase_seconds
        self.human_ready_after = human_ready_after
        self.rejoins = rejoins
        self.seats = {**AGENT_SEATS, HUMAN_SEAT[0]: HUMAN_SEAT[1]}
        self.connections: dict[int, FakeConnection] = {}
        self.ready: set[int] = set()
        self.all_ready = asyncio.Event()
        self.current_phase: Optional[str] = PRE_GAME_PHASE
        self.t0 = asyncio.get_running_loop().time()
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

    async def authenticate(self, connection: FakeConnection) -> None:
        self.connections[connection.player_number] = connection
        joined = envelope(
            "player-joined",
            playerNumber=connection.player_number,
            role=self.seats[connection.player_number],
            joinedPlayers=len(self.connections),
            totalPlayers=len(self.seats),
        )
        for other in list(self.connections.values()):
            await other.push(joined)
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

    def _millis(self) -> int:
        return int(self.now() * 1000)

    async def _rejoin_everyone(self, label: str) -> None:
        self.rejoin_times[label] = self.now()
        for connection in list(self.connections.values()):
            if not connection.closed.is_set():
                await self.authenticate(connection)

    async def _human(self) -> None:
        if self.human_ready_after is None:
            return
        await asyncio.sleep(self.human_ready_after)
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
        if server.human_ready_at is not None:
            human = f"ready at +{server.human_ready_at:.2f}s"
        elif server.human_ready_after is not None:
            human = f"not ready yet (scheduled for +{server.human_ready_after:.2f}s)"
        else:
            human = "never ready"
        gameplay = "not yet" if server.gameplay_started_at is None else f"+{server.gameplay_started_at:.2f}s"
        return (
            f"agent {seat.player_number}: {stop} {how}; acted in {seat.acted_phases}; "
            f"human seat {human}; gameplay (presentation) started {gameplay}; budget {self.budget}s"
        )


def build_agent(server: FakeIbexServer, player_number: int, prompts_dir: Path) -> tuple[Agent, FakeConnection]:
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
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(),
        auth_mechanism_kwargs={"recovery": f"recovery-{player_number}"},
    )
    connection.on_message = agent._raw_message_received

    async def request_snapshot(event) -> None:
        if event.data.get("playerNumber") == player_number:
            await agent.transport.send(GET_SNAPSHOT)

    agent.register_event_handler("player-joined", request_snapshot)
    return agent, connection


def runner_config(tmp_path: Path, budget: float, **extra: float) -> HybridGameRunnerConfig:
    config = HybridGameRunnerConfig(
        game_id=GAME_ID,
        hostname="localhost",
        port=0,
        path="",
        logs_dir=tmp_path / "logs",
        prompts_dir=tmp_path,
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        continuous_phases=["market"],
    )
    config.max_game_duration = budget
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
    rejoins: tuple[tuple[str, float], ...] = (),
    **config_extra: float,
) -> GameOutcome:
    caplog.set_level(logging.DEBUG)
    server = FakeIbexServer(phase_seconds=phase_seconds, human_ready_after=human_ready_after, rejoins=rejoins)
    built = [build_agent(server, number, tmp_path) for number in AGENT_SEATS]
    runner = GameRunner(config=runner_config(tmp_path, budget, **config_extra), agents=[agent for agent, _ in built])

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
            stopped_at=connection.stopped_at,
            stopped_in_phase=connection.stopped_in_phase,
            game_over_received=connection.game_over_received,
        )
    return outcome


# --- (a) Behavioural bug checks: fail on main, must pass after the fix -------------------------


@pytest.mark.asyncio
async def test_pre_game_wait_does_not_consume_gameplay_budget(tmp_path, caplog):
    """Game 16, scaled: the human readies after 3x the budget; gameplay itself takes ~0.3 s < budget."""
    budget = 0.5
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_ready_after=1.5,
        phase_seconds=phase_plan(0.03),
        rejoins=((PRE_GAME_PHASE, 0.25),),
    )

    for seat in outcome.seats.values():
        assert not seat.missing_gameplay_phases, (
            f"waiting for the human consumed the gameplay budget: agent {seat.player_number} never acted in "
            f"{seat.missing_gameplay_phases}. {outcome.describe(seat)}"
        )
        assert seat.game_over_received, f"agent was stopped before game-over. {outcome.describe(seat)}"


@pytest.mark.asyncio
async def test_duplicate_snapshots_and_rejoin_do_not_restart_gameplay_clock(tmp_path, caplog):
    """The clock starts once, at presentation; an introduction re-join and a market re-join
    (player-joined + phase-transition replay + get-snapshot reply) must neither start nor restart it.
    Gameplay (2.1 s) is longer than the budget, so the watchdog must fire budget seconds after
    presentation began, not budget seconds after the run started or after the last snapshot."""
    budget = 0.6
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_ready_after=0.9,
        phase_seconds=phase_plan(0.1, speculation_first=0.05, transition=0.02, transcription=0.02, market=1.5),
        rejoins=((PRE_GAME_PHASE, 0.3), ("market", 0.05)),
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
        assert budget - 0.1 <= fired_after <= budget + 0.25, (
            f"gameplay watchdog fired {fired_after:+.2f}s after gameplay started, expected {budget}s "
            f"(clock must start once at presentation; market re-join at "
            f"+{outcome.server.rejoin_times.get('market', float('nan')):.2f}s must not restart it). "
            f"{outcome.describe(seat)}"
        )
        assert seat.snapshot_phases.count("market") >= 2, (
            f"agent {seat.player_number} did not see the duplicate market snapshot: {seat.snapshot_phases}"
        )
        assert seat.snapshot_phases.count(PRE_GAME_PHASE) >= 2, (
            f"agent {seat.player_number} did not see the duplicate introduction snapshot: {seat.snapshot_phases}"
        )


# --- Guards: pass on main, must still pass after the fix -----------------------------------------


@pytest.mark.asyncio
async def test_genuine_gameplay_timeout_still_stops_agents(tmp_path, caplog):
    """No pre-game wait, gameplay (market alone 2 s) longer than the budget: agents are stopped
    about budget seconds into gameplay, never reach the final phases, and a warning names the budget."""
    budget = 0.5
    outcome = await play_game(
        tmp_path,
        caplog,
        budget=budget,
        human_ready_after=0.0,
        phase_seconds=phase_plan(0.05, market=2.0),
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
