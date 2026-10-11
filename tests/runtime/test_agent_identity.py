"""Agent identity binding (IBEX-game_suite#10): snapshot, first own player-joined, recovery match."""

import asyncio
import json
import logging

import pytest
import websockets

from econagents.adapters.transport import JoinPayloadAuth, WebSocketTransport
from econagents.domain.messages import Event
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime.agent import Agent
from econagents.runtime.identity import PlayerIdentity

RECOVERY = "rec-7"


class IdleRole(Role):
    role = 1
    name = "speculator"
    task_phases = ["never"]


class EpochTransport:
    """Transport stand-in that reports a connection epoch the test advances."""

    def __init__(self) -> None:
        self.connection_epoch = 1
        self.bound_identity = None
        self.logger = logging.getLogger("identity-test")
        self.stopped = False

    async def start_listening(self) -> None:
        return None

    async def send(self, message: str) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True


def make_agent(tmp_path, player_number=None, role=None, transport=None) -> Agent:
    state = GameState()
    state.meta.player_number = player_number
    if role is not None:
        state.meta.role = role
    return Agent(
        url="ws://127.0.0.1:9",
        state=state,
        role=IdleRole(),
        prompts_dir=tmp_path,
        auth_mechanism_kwargs={"recovery": RECOVERY},
        transport=transport or EpochTransport(),
    )


def joined(player: int, role: str = "speculator") -> Event:
    return Event(type="player-joined", data={"playerNumber": player, "role": role, "joinedPlayers": 1})


@pytest.mark.asyncio
async def test_snapshot_player_number_binds_and_fills_meta(tmp_path):
    agent = make_agent(tmp_path)
    await agent.start()
    await agent.on_event(Event(type="snapshot", data={"playerNumber": 7, "role": "speculator", "players": []}))

    assert agent.state.meta.player_number == 7
    assert agent.bound_identity == PlayerIdentity(7, "speculator", "snapshot", 1)
    assert agent.transport.bound_identity == agent.bound_identity


@pytest.mark.asyncio
async def test_first_player_joined_per_connection_is_own(tmp_path):
    agent = make_agent(tmp_path)
    await agent.start()
    await agent.on_event(joined(7))
    await agent.on_event(joined(3, "owner"))
    assert agent.bound_identity == PlayerIdentity(7, "speculator", "player-joined", 1)

    agent.transport.connection_epoch = 2
    await agent.on_event(joined(7))
    assert agent.bound_identity == PlayerIdentity(7, "speculator", "player-joined", 2)
    assert agent.state.meta.player_number == 7


@pytest.mark.asyncio
async def test_recovery_match_is_the_last_resort(tmp_path):
    roster = {"players": [{"playerNumber": 7, "role": "speculator", "recovery": RECOVERY}]}
    agent = make_agent(tmp_path)
    await agent.start()
    await agent.on_event(Event(type="snapshot", data=roster))
    assert agent.bound_identity.source == "recovery"

    await agent.on_event(Event(type="snapshot", data={**roster, "playerNumber": 7, "role": "speculator"}))
    assert agent.bound_identity.source == "snapshot"
    await agent.on_event(Event(type="phase-transition", data=roster))
    assert agent.bound_identity.source == "snapshot", "a recovery match must not override a stronger source"


@pytest.mark.asyncio
async def test_identity_contradicting_the_configured_seat_stops_the_agent(tmp_path, caplog):
    agent = make_agent(tmp_path, player_number=7, role="speculator")
    await agent.start()
    with caplog.at_level(logging.ERROR):
        await agent.on_event(Event(type="snapshot", data={"playerNumber": 8, "role": "speculator"}))

    assert agent.identity_error is not None
    assert agent.running is False and agent.transport.stopped
    assert agent.state.meta.player_number == 7
    assert "identity-mismatch" in caplog.text


@pytest.mark.asyncio
async def test_role_contradicting_the_configured_seat_stops_the_agent(tmp_path):
    agent = make_agent(tmp_path, player_number=7, role="speculator")
    await agent.start()
    await agent.on_event(joined(7, "owner"))
    assert agent.identity_error is not None
    assert agent.running is False


@pytest.mark.asyncio
async def test_matching_identity_keeps_the_agent_running(tmp_path):
    agent = make_agent(tmp_path, player_number=7, role="speculator")
    await agent.start()
    await agent.on_event(joined(7))
    await agent.on_event(Event(type="snapshot", data={"playerNumber": 7, "role": "speculator"}))
    assert agent.identity_error is None
    assert agent.running is True


@pytest.mark.asyncio
async def test_instances_get_distinct_ids(tmp_path):
    assert make_agent(tmp_path).instance_id != make_agent(tmp_path).instance_id


class JoinServer:
    """Answers each join with the joiner's own player-joined, then another seat's player-joined."""

    def __init__(self) -> None:
        self.sockets: list = []

    async def handler(self, ws):
        self.sockets.append(ws)
        async for raw in ws:
            if json.loads(raw)["meta"]["type"] == "join":
                for player, role in ((7, "speculator"), (3, "owner")):
                    payload = {"playerNumber": player, "role": role, "joinedPlayers": 2, "totalPlayers": 12}
                    await ws.send(json.dumps({"meta": {"type": "player-joined"}, "payload": payload}))


async def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.02)
    return True


@pytest.mark.asyncio
async def test_websocket_agent_rebinds_on_every_connection(tmp_path):
    server = JoinServer()
    async with websockets.serve(server.handler, "127.0.0.1", 0) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        state = GameState()
        agent = Agent(
            url=f"ws://127.0.0.1:{port}",
            state=state,
            role=IdleRole(),
            prompts_dir=tmp_path,
            auth_mechanism=JoinPayloadAuth(),
            auth_mechanism_kwargs={"recovery": RECOVERY},
        )
        agent.transport.reconnect_delay = 0.01
        task = asyncio.create_task(agent.start())
        try:
            assert await wait_for(lambda: agent.bound_identity is not None)
            assert agent.bound_identity == PlayerIdentity(7, "speculator", "player-joined", 1)
            assert agent.transport.bound_identity == agent.bound_identity

            server.sockets[-1].transport.abort()
            assert await wait_for(lambda: agent.bound_identity is not None and agent.bound_identity.connection == 2)
            assert agent.bound_identity.player_number == 7
            assert agent.transport.connection_epoch == 2
            assert state.meta.player_number == 7
        finally:
            await agent.stop()
            await asyncio.wait_for(task, 5)
