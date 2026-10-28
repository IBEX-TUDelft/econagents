"""The agent records each decision's reasoning and sends it in ``meta.reasoning``."""

import json
import logging
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from econagents.domain.reasoning import report_reasoning
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime import Agent

ENVELOPE = {"meta": {"type": "post-order", "component": {"type": "standard:dam"}}, "payload": {"price": 1}}


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def start_listening(self) -> None:
        pass

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def stop(self) -> None:
        pass


def make_agent(tmp_path: Path, reasoning: Optional[str]) -> tuple[Agent, FakeTransport, list]:
    async def handle_phase(phase, state, prompts_path):
        report_reasoning(reasoning)
        return ENVELOPE

    role = MagicMock(spec=Role)
    role.name = "trader"
    role.handle_phase = handle_phase
    transport = FakeTransport()
    traces: list[dict[str, Any]] = []
    agent = Agent(
        url="ws://unused",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
        decision_trace=traces.append,
        logger=logging.getLogger("test.agent.reasoning"),
    )
    return agent, transport, traces


@pytest.mark.asyncio
async def test_reasoning_is_sent_in_meta_and_traced(tmp_path):
    agent, transport, traces = make_agent(tmp_path, "Cheap enough.")

    await agent.execute_phase_action("market")

    assert transport.sent[0]["meta"]["reasoning"] == "Cheap enough."
    assert transport.sent[0]["payload"] == ENVELOPE["payload"]
    assert traces[0]["reasoning"] == "Cheap enough."


@pytest.mark.asyncio
async def test_an_action_without_reasoning_is_sent_as_decided(tmp_path):
    agent, transport, traces = make_agent(tmp_path, None)

    outcome = await agent.execute_phase_action("market")

    assert outcome.status == "sent"
    assert transport.sent == [ENVELOPE]
    assert traces[0]["reasoning"] is None
