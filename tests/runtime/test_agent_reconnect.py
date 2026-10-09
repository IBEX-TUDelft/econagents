"""Reproduction for IBEX-game_suite#8: a reconnect must not add a second decision loop.

The agent is wired like ``futarchy_agents.run_game.build_agent`` (origin/futharcy-agents): it acts on
``snapshot`` events and requests a snapshot when its own ``player-joined`` arrives. On a re-join the
IBEX server replays ``player-joined`` and ``phase-transition`` (``WebSocketService.logIn``), so the
agent asks for a snapshot of the phase it is already in. Today that snapshot re-enters
``handle_phase_transition("market")``, which starts a second continuous decision loop and a second
model decision while the first one is still unresolved (the #6 lifecycle defect surfaced by #8).

Loops are counted by behavior, not by name: the market's action delay runs on ``ActionClock``. One
tick of the clock is one action delay elapsing, and each live decision loop answers it with exactly
one model decision. The only assumption is that a continuous loop waits for its next action with
``asyncio.sleep(phase_engine.next_action_delay())``.
"""

import asyncio
import json

import pytest

from econagents.domain.state.game import GameState
from econagents.runtime import Agent, PhaseEngine

PLAYER = 2
RECOVERY = "rec-abc"
ACTION_DELAY = 3600
GET_SNAPSHOT = json.dumps({"meta": {"type": "get-snapshot"}, "payload": {}})
POST_ORDER = {
    "meta": {"type": "post-order", "component": {"type": "standard:dam", "name": "no_project"}},
    "payload": {"sender": PLAYER, "type": "bid", "price": 1041, "timestamp": 1791555677396, "now": False},
}


def _player_joined() -> str:
    payload = {"playerNumber": PLAYER, "role": "developer", "joinedPlayers": 12, "totalPlayers": 12}
    return json.dumps({"meta": {"type": "player-joined"}, "payload": payload})


def _phase_transition(phase: str) -> str:
    return json.dumps(
        {"meta": {"type": "phase-transition"}, "payload": {"round": 1, "phase": phase, "transitionedAt": 0}}
    )


def _snapshot(phase: str) -> str:
    players = [{"playerNumber": PLAYER, "role": "developer", "recovery": RECOVERY}]
    payload = {"currentRound": 1, "currentPhase": phase, "players": players}
    return json.dumps({"meta": {"type": "snapshot"}, "payload": payload})


class ActionClock:
    """Stands in for ``asyncio.sleep`` for the market action delay only; ``tick()`` lets it elapse once."""

    def __init__(self, real_sleep):
        self.real_sleep = real_sleep
        self.sleepers = 0
        self._elapsed = asyncio.Event()

    async def sleep(self, delay, result=None):
        if delay != ACTION_DELAY:
            return await self.real_sleep(delay, result)
        elapsed = self._elapsed
        self.sleepers += 1
        try:
            await elapsed.wait()
        finally:
            self.sleepers -= 1
        return result

    def tick(self) -> None:
        elapsed, self._elapsed = self._elapsed, asyncio.Event()
        elapsed.set()


@pytest.fixture
def clock(monkeypatch):
    action_clock = ActionClock(asyncio.sleep)
    monkeypatch.setattr(asyncio, "sleep", action_clock.sleep)
    return action_clock


class InMemoryIbexConnection:
    """Transport double that replays what the IBEX server sends on (re-)join and on get-snapshot.

    ``fail_actions`` maps the 1-based index of an action send (get-snapshot excluded) to the exception it raises."""

    def __init__(self, phase: str, fail_actions: dict[int, BaseException] | None = None):
        self.phase = phase
        self.fail_actions = dict(fail_actions or {})
        self.sent: list[str] = []
        self.actions: list[str] = []
        self.agent: Agent | None = None
        self._stopped = asyncio.Event()

    def _deliver(self, raw: str) -> None:
        event = self.agent.message_codec.decode_event(raw)
        asyncio.create_task(self.agent.on_event(event))

    async def join(self) -> None:
        """A successful (re-)join: WebSocketService.logIn sends player-joined, then replays the phase."""
        self._deliver(_player_joined())
        self._deliver(_phase_transition(self.phase))

    async def start_listening(self) -> None:
        await self._stopped.wait()

    async def send(self, message: str):
        self.sent.append(message)
        if json.loads(message)["meta"]["type"] == "get-snapshot":
            self._deliver(_snapshot(self.phase))
            return True
        self.actions.append(message)
        if len(self.actions) in self.fail_actions:
            raise self.fail_actions.pop(len(self.actions))
        return True

    async def stop(self) -> None:
        self._stopped.set()


class GatedRole:
    """A role whose model decisions stay unresolved until the test opens the gate."""

    name = "developer"
    prompt_renderer = object()
    response_parser = object()

    def __init__(self, response=None, gated: bool = True):
        self.response = response
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.gate = asyncio.Event()
        if not gated:
            self.gate.set()

    async def handle_phase(self, phase, state, prompts_dir):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await self.gate.wait()
        finally:
            self.in_flight -= 1
        return self.response


async def wait_for(pred, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


def _market_agent(tmp_path, connection: InMemoryIbexConnection, role: GatedRole) -> Agent:
    agent = Agent(
        url="ws://127.0.0.1:1",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=connection,
        auth_mechanism_kwargs={"recovery": RECOVERY},
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(
            continuous_phases={"market"}, min_action_delay=ACTION_DELAY, max_action_delay=ACTION_DELAY
        ),
    )
    connection.agent = agent

    async def request_snapshot(event) -> None:
        if event.data.get("playerNumber") == PLAYER:
            await agent.transport.send(GET_SNAPSHOT)

    agent.register_event_handler("player-joined", request_snapshot)
    return agent


async def _reconnected_market_agent(tmp_path, clock: ActionClock):
    connection = InMemoryIbexConnection(phase="market")
    role = GatedRole()
    agent = _market_agent(tmp_path, connection, role)

    await connection.join()
    assert await wait_for(lambda: role.calls == 1, timeout=5.0), "initial market snapshot did not start a decision"

    await connection.join()
    assert await wait_for(lambda: connection.sent.count(GET_SNAPSHOT) == 2, timeout=5.0)
    await wait_for(lambda: role.calls >= 2 or clock.sleepers >= 2, timeout=1.0)
    await asyncio.sleep(0.05)
    return agent, role


async def _shutdown(agent: Agent, role: GatedRole, tasks_before: set[asyncio.Task]) -> None:
    role.gate.set()
    await agent.stop()
    leftovers = [t for t in asyncio.all_tasks() - tasks_before if t is not asyncio.current_task() and not t.done()]
    for task in leftovers:
        task.cancel()
    await asyncio.gather(*leftovers, return_exceptions=True)


async def _decisions_per_action_delay(role: GatedRole, clock: ActionClock) -> int:
    """Let one action delay elapse and return how many model decisions it produced."""
    assert await wait_for(lambda: clock.sleepers >= 1, timeout=5.0), "no market loop is waiting for its next action"
    waiting = clock.sleepers
    before = role.calls
    clock.tick()
    await wait_for(lambda: role.calls - before >= waiting and clock.sleepers >= waiting, timeout=2.0)
    await asyncio.sleep(0.05)
    return role.calls - before


@pytest.mark.asyncio
async def test_reconnect_snapshot_does_not_start_second_decision_loop(tmp_path, clock):
    tasks_before = asyncio.all_tasks()
    agent, role = await _reconnected_market_agent(tmp_path, clock)
    try:
        role.gate.set()
        assert await wait_for(lambda: role.in_flight == 0, timeout=5.0)
        decisions = await _decisions_per_action_delay(role, clock)
        assert decisions == 1, (
            f"one action delay after one reconnect produced {decisions} market decisions "
            f"({decisions} live decision loops; expected exactly 1)"
        )
    finally:
        await _shutdown(agent, role, tasks_before)


@pytest.mark.asyncio
async def test_reconnect_snapshot_does_not_start_second_unresolved_decision(tmp_path, clock):
    tasks_before = asyncio.all_tasks()
    agent, role = await _reconnected_market_agent(tmp_path, clock)
    try:
        assert role.max_in_flight == 1, (
            f"{role.max_in_flight} model decisions in flight for the same market phase after reconnect "
            f"({role.calls} model calls); the first one was still unresolved"
        )
    finally:
        await _shutdown(agent, role, tasks_before)


@pytest.mark.asyncio
async def test_market_loop_survives_a_failed_send(tmp_path, clock):
    """Once send() reports a lost request by raising, the market loop must keep deciding after it."""
    tasks_before = asyncio.all_tasks()
    connection = InMemoryIbexConnection(
        phase="market", fail_actions={2: ConnectionError("socket closed before the frame was written")}
    )
    role = GatedRole(response=POST_ORDER, gated=False)
    agent = _market_agent(tmp_path, connection, role)
    try:
        await connection.join()
        assert await wait_for(lambda: role.calls == 1 and len(connection.actions) == 1, timeout=5.0)

        failed = await _decisions_per_action_delay(role, clock)
        assert failed == 1 and len(connection.actions) == 2, "the loop did not reach the failing send"

        survived = await _decisions_per_action_delay(role, clock) if clock.sleepers else 0
        assert survived == 1, (
            "after one send raised ConnectionError the market loop made no further decision: "
            "the loop task died (only CancelledError is handled)"
        )
    finally:
        await _shutdown(agent, role, tasks_before)
