"""Reproduction for IBEX-game_suite#8: a reconnect must not add a second decision loop.

The agent is wired like ``futarchy_agents.run_game.build_agent`` (origin/futharcy-agents): it acts on
``snapshot`` events and requests a snapshot when its own ``player-joined`` arrives. On a re-join the
IBEX server replays ``player-joined`` and ``phase-transition`` (``WebSocketService.logIn``), so the
agent asks for a snapshot of the phase it is already in. Today that snapshot re-enters
``handle_phase_transition("market")``, which starts a second ``_continuous_phase_loop`` and a second
model decision while the first one is still unresolved (the #6 lifecycle defect surfaced by #8).
"""

import asyncio
import json

import pytest

from econagents.domain.state.game import GameState
from econagents.runtime import Agent, PhaseEngine

PLAYER = 2
RECOVERY = "rec-abc"
GET_SNAPSHOT = json.dumps({"meta": {"type": "get-snapshot"}, "payload": {}})


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


class InMemoryIbexConnection:
    """Transport double that replays what the IBEX server sends on (re-)join and on get-snapshot."""

    def __init__(self, phase: str):
        self.phase = phase
        self.sent: list[str] = []
        self.joins = 0
        self.agent: Agent | None = None
        self._stopped = asyncio.Event()

    def _deliver(self, raw: str) -> None:
        event = self.agent.message_codec.decode_event(raw)
        asyncio.create_task(self.agent.on_event(event))

    async def join(self) -> None:
        """A successful (re-)join: WebSocketService.logIn sends player-joined, then replays the phase."""
        self.joins += 1
        self._deliver(_player_joined())
        self._deliver(_phase_transition(self.phase))

    async def start_listening(self) -> None:
        await self._stopped.wait()

    async def send(self, message: str) -> None:
        self.sent.append(message)
        if json.loads(message)["meta"]["type"] == "get-snapshot":
            self._deliver(_snapshot(self.phase))

    async def stop(self) -> None:
        self._stopped.set()


class GatedRole:
    """A role whose model decision stays unresolved until the test opens the gate."""

    name = "developer"
    prompt_renderer = object()
    response_parser = object()

    def __init__(self):
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.gate = asyncio.Event()

    async def handle_phase(self, phase, state, prompts_dir):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await self.gate.wait()
        finally:
            self.in_flight -= 1
        return None


async def wait_for(pred, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


def _live_decision_loops() -> list[asyncio.Task]:
    return [
        task
        for task in asyncio.all_tasks()
        if not task.done() and getattr(task.get_coro(), "__qualname__", "").endswith("_continuous_phase_loop")
    ]


async def _reconnected_market_agent(tmp_path):
    connection = InMemoryIbexConnection(phase="market")
    role = GatedRole()
    agent = Agent(
        url="ws://127.0.0.1:1",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=connection,
        auth_mechanism_kwargs={"recovery": RECOVERY},
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(continuous_phases={"market"}, min_action_delay=3600, max_action_delay=3600),
    )
    connection.agent = agent

    async def request_snapshot(event) -> None:
        if event.data.get("playerNumber") == PLAYER:
            await agent.transport.send(GET_SNAPSHOT)

    agent.register_event_handler("player-joined", request_snapshot)

    await connection.join()
    assert await wait_for(lambda: role.calls == 1, timeout=5.0), "initial market snapshot did not start a decision"
    assert len(_live_decision_loops()) == 1

    await connection.join()
    assert await wait_for(lambda: connection.sent.count(GET_SNAPSHOT) == 2, timeout=5.0)
    await wait_for(lambda: role.calls >= 2 or len(_live_decision_loops()) >= 2, timeout=1.0)
    await asyncio.sleep(0.05)
    return agent, role


async def _shutdown(agent: Agent, role: GatedRole) -> None:
    role.gate.set()
    await agent.stop()
    loops = _live_decision_loops()
    for task in loops:
        task.cancel()
    await asyncio.gather(*loops, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconnect_snapshot_does_not_start_second_decision_loop(tmp_path):
    agent, role = await _reconnected_market_agent(tmp_path)
    try:
        loops = len(_live_decision_loops())
        assert loops == 1, f"{loops} market decision loops alive after one reconnect (expected exactly 1)"
    finally:
        await _shutdown(agent, role)


@pytest.mark.asyncio
async def test_reconnect_snapshot_does_not_start_second_unresolved_decision(tmp_path):
    agent, role = await _reconnected_market_agent(tmp_path)
    try:
        assert role.max_in_flight == 1, (
            f"{role.max_in_flight} model decisions in flight for the same market phase after reconnect "
            f"({role.calls} model calls); the first one was still unresolved"
        )
    finally:
        await _shutdown(agent, role)
