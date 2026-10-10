"""``Agent.execute_phase_action`` reports what became of each decision, and listeners receive it."""

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.ports.transport import TransportSendError
from econagents.runtime import ActionOutcome, Agent

ENVELOPE = {"meta": {"type": "post-order"}, "payload": {"price": 1}}


class FakeTransport:
    def __init__(self, fail: BaseException | None = None):
        self.sent: list[str] = []
        self.fail = fail

    async def start_listening(self) -> None:
        return None

    async def send(self, message: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append(message)

    async def stop(self) -> None:
        return None


def _agent(tmp_path: Path, handle_phase, transport: FakeTransport) -> Agent:
    role = MagicMock(spec=Role)
    role.name = "trader"
    role.handle_phase = handle_phase
    return Agent(
        url="ws://127.0.0.1:9",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
        logger=logging.getLogger("econagents.test.outcomes"),
    )


def _returning(payload):
    async def handle_phase(phase, state, prompts_path):
        return payload

    return handle_phase


@pytest.mark.asyncio
async def test_sent_action_is_reported_to_caller_and_listener(tmp_path: Path):
    transport = FakeTransport()
    agent = _agent(tmp_path, _returning(ENVELOPE), transport)
    seen: list[ActionOutcome] = []
    agent.register_action_listener(seen.append)

    outcome = await agent.execute_phase_action("market")

    assert outcome.status == "sent" and outcome.transmitted
    assert outcome.payload == ENVELOPE and outcome.frame == transport.sent[0]
    assert seen == [outcome]


@pytest.mark.asyncio
async def test_failed_send_is_reported_with_its_error(tmp_path: Path):
    error = TransportSendError("no open connection")
    agent = _agent(tmp_path, _returning(ENVELOPE), FakeTransport(fail=error))
    seen: list[ActionOutcome] = []

    async def listener(outcome: ActionOutcome) -> None:
        seen.append(outcome)

    agent.register_action_listener(listener)

    outcome = await agent.execute_phase_action("market")

    assert outcome.status == "not-transmitted" and not outcome.transmitted
    assert outcome.error is error and outcome.payload == ENVELOPE and outcome.frame is not None
    assert seen == [outcome]


@pytest.mark.asyncio
async def test_no_action_is_reported(tmp_path: Path):
    transport = FakeTransport()
    agent = _agent(tmp_path, _returning(None), transport)

    outcome = await agent.execute_phase_action("market")

    assert outcome.status == "no-action" and not outcome.transmitted
    assert transport.sent == []


@pytest.mark.asyncio
async def test_action_decided_after_the_phase_changed_is_reported_stale(tmp_path: Path):
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow(phase, state, prompts_path):
        started.set()
        await release.wait()
        return ENVELOPE

    transport = FakeTransport()
    agent = _agent(tmp_path, slow, transport)
    seen: list[ActionOutcome] = []
    agent.register_action_listener(seen.append)

    decision = asyncio.create_task(agent.execute_phase_action("market"))
    await asyncio.wait_for(started.wait(), 2)
    agent._phase_epoch += 1
    release.set()
    outcome = await asyncio.wait_for(decision, 2)

    assert outcome.status == "stale" and outcome.payload == ENVELOPE
    assert transport.sent == [] and seen == [outcome]


@pytest.mark.asyncio
async def test_failing_listener_is_logged_and_does_not_change_the_outcome(tmp_path: Path, caplog):
    transport = FakeTransport()
    agent = _agent(tmp_path, _returning(ENVELOPE), transport)

    def broken(outcome: ActionOutcome) -> None:
        raise RuntimeError("listener bug")

    later: list[ActionOutcome] = []
    agent.register_action_listener(broken).register_action_listener(later.append)

    with caplog.at_level(logging.ERROR, logger="econagents.test.outcomes"):
        outcome = await agent.execute_phase_action("market")

    assert outcome.status == "sent" and len(transport.sent) == 1
    assert later == [outcome]
    assert any("Action listener failed" in r.getMessage() for r in caplog.records)
