"""``Agent`` while an administrator has paused the game (ibex 0.9.0, IBEX-TUDelft/futarchy#1).

A paused game refuses every player's message. The agent starts no decision and sends no action from
``game-paused`` (or a snapshot with ``paused: true``) until ``game-resumed``, and treats a refusal with
reason ``"paused"`` or ``"late"`` as no fault of the action.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from econagents.domain import Event
from econagents.domain.state.game import GameState
from econagents.runtime import Agent, GameTime, PhaseEngine

SEALED = "declaration"
OTHER = "speculation"
MARKET = "market"
DECLARATION = {
    "meta": {"type": "submit-declaration", "component": {"type": "standard:declaration"}},
    "payload": {"values": [10]},
}
BID = {
    "meta": {"type": "post-order", "component": {"type": "standard:dam", "name": "project"}},
    "payload": {"type": "bid", "price": 10},
}


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail: BaseException | None = None

    async def start_listening(self) -> None:
        pass

    async def send(self, message: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append(message)

    async def stop(self) -> None:
        pass


class Role:
    """Returns the declaration in ``SEALED`` and a bid in ``MARKET``; ``hold`` keeps a decision running."""

    name = "trader"
    prompt_renderer = object()
    response_parser = object()

    def __init__(self) -> None:
        self.calls = 0
        self.hold: asyncio.Event | None = None

    async def handle_phase(self, phase, state, prompts_dir):
        self.calls += 1
        if self.hold is not None:
            await self.hold.wait()
        await asyncio.sleep(0)
        return {SEALED: DECLARATION, MARKET: BID}.get(phase)


class Tracker:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def submitted(self, decision_id, message, state) -> bool:
        return False

    def observe(self, event, state):
        self.seen.append(event.type)
        return []


def make_agent(role: Role, tmp_path: Path, **options: Any) -> tuple[Agent, FakeTransport]:
    transport = FakeTransport()
    agent = Agent(
        url="ws://unused",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(continuous_phases={MARKET}, min_action_delay=0, max_action_delay=0),
        **options,
    )
    agent.running = True
    return agent, transport


def message(event_type: str, gametime: float | None = None, **payload: Any) -> Event:
    meta: dict[str, Any] = {"type": event_type}
    if gametime is not None:
        meta["gametime"] = gametime
        if event_type in ("game-paused", "game-resumed"):
            payload["gametime"] = gametime
    return Event(type=event_type, data=payload, raw={"meta": meta, "payload": payload})


def snapshot(phase: str, paused: bool = False, gametime: float | None = None) -> Event:
    payload: dict[str, Any] = {"currentPhase": phase}
    if paused:
        payload["paused"] = True
    return message("snapshot", gametime, **payload)


def refused(action: dict, reason: str) -> Event:
    meta = action["meta"]
    return message("message-refused", component=meta["component"], messageType=meta["type"], reason=reason)


async def spin(n: int = 50) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def deliver(agent: Agent, event: Event) -> asyncio.Task:
    task = asyncio.create_task(agent.on_event(event))
    await spin()
    return task


async def shutdown(agent: Agent, *tasks: asyncio.Task) -> None:
    await agent.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_no_decision_starts_while_the_game_is_paused(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, message("game-paused", gametime=1000))]
    try:
        assert agent.paused
        tasks.append(await deliver(agent, snapshot(SEALED, paused=True)))
        assert role.calls == 0
        assert transport.sent == []

        tasks.append(await deliver(agent, message("game-resumed", gametime=1000)))
        assert not agent.paused
        assert role.calls == 1
        assert transport.sent == [json.dumps(DECLARATION)]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_snapshot_says_whether_the_game_is_paused(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(SEALED, paused=True))]
    try:
        assert agent.paused, "an agent that joins during a pause learns it from its snapshot"
        assert role.calls == 0

        tasks.append(await deliver(agent, snapshot(SEALED)))
        assert not agent.paused, "a snapshot without the flag ends the pause for an agent that missed game-resumed"
        assert role.calls == 1
        assert transport.sent == [json.dumps(DECLARATION)]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_an_action_decided_during_a_pause_is_held_and_sent_after_the_resume(tmp_path):
    role = Role()
    role.hold = asyncio.Event()
    outcomes: list[Any] = []
    agent, transport = make_agent(role, tmp_path)
    agent.register_action_listener(outcomes.append)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        assert role.calls == 1
        tasks.append(await deliver(agent, message("game-paused")))
        role.hold.set()
        await spin()
        assert transport.sent == [], "the decision finished during the pause; its action waits"
        assert outcomes == []

        tasks.append(await deliver(agent, message("game-resumed")))
        assert transport.sent == [json.dumps(DECLARATION)]
        assert [outcome.status for outcome in outcomes] == ["sent"]
        assert role.calls == 1
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_held_action_is_dropped_when_the_agent_has_moved_to_another_phase(tmp_path):
    role = Role()
    role.hold = asyncio.Event()
    records: list[dict] = []
    agent, transport = make_agent(role, tmp_path, decision_trace=records.append)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        tasks.append(await deliver(agent, message("game-paused")))
        role.hold.set()
        await spin()

        tasks.append(await deliver(agent, snapshot(OTHER)))
        assert not agent.paused
        assert transport.sent == []
        assert [(record["phase"], record["disposition"]) for record in records] == [
            (SEALED, "stale-phase"),
            (OTHER, "no-action"),
        ]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_continuous_phase_sends_nothing_while_paused(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(MARKET))]
    try:
        assert len(transport.sent) > 1
        tasks.append(await deliver(agent, message("game-paused")))
        sent, calls = len(transport.sent), role.calls
        await spin(200)
        assert len(transport.sent) == sent
        assert role.calls <= calls + 1, "at most the decision that was running when the pause arrived"

        tasks.append(await deliver(agent, message("game-resumed")))
        assert len(transport.sent) > sent
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_an_action_refused_as_paused_is_sent_again_after_the_resume(tmp_path, caplog):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        assert transport.sent == [json.dumps(DECLARATION)]
        with caplog.at_level(logging.INFO):
            tasks.append(await deliver(agent, refused(DECLARATION, "paused")))
        assert agent.paused, "the refusal is evidence of the pause"
        assert transport.sent == [json.dumps(DECLARATION)]
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]

        tasks.append(await deliver(agent, message("game-resumed")))
        assert transport.sent == [json.dumps(DECLARATION)] * 2
        assert role.calls == 1, "the same action, not a new decision"
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_second_pause_refusal_sends_the_action_once_more(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        for _ in range(2):
            tasks.append(await deliver(agent, refused(DECLARATION, "paused")))
            tasks.append(await deliver(agent, message("game-resumed")))
        assert transport.sent == [json.dumps(DECLARATION)] * 3
        assert role.calls == 1
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_refusal_of_another_message_sends_nothing_again(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        tasks.append(await deliver(agent, refused(BID, "paused")))
        tasks.append(await deliver(agent, message("game-resumed")))
        assert transport.sent == [json.dumps(DECLARATION)]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_paused_action_is_not_sent_again_once_the_phase_has_changed(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        tasks.append(await deliver(agent, refused(DECLARATION, "paused")))
        tasks.append(await deliver(agent, snapshot(OTHER)))
        assert not agent.paused
        assert transport.sent == [json.dumps(DECLARATION)]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_continuous_phase_decides_again_instead_of_resending(tmp_path):
    role = Role()
    role.hold = asyncio.Event()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(MARKET))]
    try:
        role.hold.set()
        await spin(5)
        role.hold.clear()
        await spin()
        sent, calls = len(transport.sent), role.calls
        assert sent >= 1

        tasks.append(await deliver(agent, refused(BID, "paused")))
        role.hold.set()
        await spin()
        assert len(transport.sent) == sent

        tasks.append(await deliver(agent, message("game-resumed")))
        assert len(transport.sent) > sent
        assert role.calls > calls, "each bid after the resume is a new decision"
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_with_a_disposition_tracker_the_refusal_is_the_trackers_business(tmp_path):
    role = Role()
    tracker = Tracker()
    agent, transport = make_agent(role, tmp_path, disposition_tracker=tracker)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        tasks.append(await deliver(agent, refused(DECLARATION, "paused")))
        assert agent.paused
        tasks.append(await deliver(agent, message("game-resumed")))
        assert transport.sent == [json.dumps(DECLARATION)]
        assert tracker.seen == ["snapshot", "message-refused", "game-resumed"]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_a_late_action_is_not_sent_again(tmp_path, caplog):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        with caplog.at_level(logging.INFO):
            tasks.append(await deliver(agent, refused(DECLARATION, "late")))
        assert not agent.paused
        assert transport.sent == [json.dumps(DECLARATION)]
        assert role.calls == 1
        assert any("time was up" in record.getMessage() for record in caplog.records)
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_an_invalid_refusal_does_not_pause_the_agent(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, snapshot(SEALED))]
    try:
        tasks.append(await deliver(agent, refused(DECLARATION, "invalid")))
        assert not agent.paused
        assert transport.sent == [json.dumps(DECLARATION)]
    finally:
        await shutdown(agent, *tasks)


@pytest.mark.asyncio
async def test_stopping_a_paused_agent_sends_nothing(tmp_path):
    role = Role()
    agent, transport = make_agent(role, tmp_path)
    tasks = [await deliver(agent, message("game-paused"))]
    tasks.append(await deliver(agent, snapshot(SEALED, paused=True)))
    await shutdown(agent, *tasks)
    await spin()
    assert role.calls == 0
    assert transport.sent == []


@pytest.mark.asyncio
async def test_the_agents_game_time_stands_still_during_a_pause(tmp_path):
    local = {"now": 100_000.0}
    agent, _ = make_agent(Role(), tmp_path)
    agent.game_time = GameTime(local_now=lambda: local["now"])
    tasks = [await deliver(agent, snapshot(OTHER, gametime=20_000))]
    try:
        local["now"] += 4_000
        assert agent.game_time.remaining(60_000) == 36_000

        tasks.append(await deliver(agent, message("game-paused", gametime=24_000)))
        local["now"] += 300_000
        tasks.append(await deliver(agent, snapshot(OTHER, paused=True, gametime=24_000)))
        assert agent.game_time.remaining(60_000) == 36_000

        tasks.append(await deliver(agent, message("game-resumed", gametime=24_000)))
        assert agent.game_time.remaining(60_000) == 36_000
        local["now"] += 6_000
        assert agent.game_time.remaining(60_000) == 30_000
    finally:
        await shutdown(agent, *tasks)
