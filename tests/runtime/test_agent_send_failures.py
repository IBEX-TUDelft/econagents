"""IBEX-game_suite#7: a failed send must reach the caller of ``Agent.execute_phase_action``.

``tests/adapters/test_transport_send_failures.py`` checks the transport alone, so a fix where
``WebSocketTransport.send`` returns ``False`` but ``Agent.execute_phase_action`` ignores the result
would pass it while the lost action still vanishes in production. This drives the Agent with the
production ``WebSocketTransport`` it builds itself.

Logging is not a criterion: the Agent hands its own logger to the transport, so the failed send is
already logged at ERROR on the agent logger today ("Error sending message."), and the issue requires
infrastructure errors to be "surfaced to the caller or recorded ... never only logged". The caller
must see the failure: ``execute_phase_action`` raises, or returns an explicit ``False``.
"""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from econagents.adapters.transport import WebSocketTransport
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime import Agent

ENVELOPE = {"meta": {"type": "post-order"}, "payload": {"price": 1}}


def _agent(tmp_path: Path) -> Agent:
    async def handle_phase(phase, state, prompts_path):
        return ENVELOPE

    role = MagicMock(spec=Role)
    role.name = "trader"
    role.handle_phase = handle_phase
    return Agent(
        url="ws://127.0.0.1:9",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        logger=logging.getLogger("gs7.agent.send"),
    )


async def _outcome(agent: Agent) -> str:
    try:
        result = await agent.execute_phase_action("market")
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}"
    return "returned False" if result is False else f"returned {result!r}"


@pytest.mark.asyncio
async def test_failed_send_reaches_the_caller_of_execute_phase_action(tmp_path: Path):
    agent = _agent(tmp_path)
    assert isinstance(agent.transport, WebSocketTransport)
    agent.transport.ws = MagicMock(send=AsyncMock(side_effect=ConnectionResetError("socket closed")))

    outcome = await _outcome(agent)

    agent.transport.ws.send.assert_awaited_once()
    assert outcome.startswith("raised") or outcome == "returned False", (
        f"ws.send raised ConnectionResetError but execute_phase_action {outcome}: the agent treats the lost "
        "action as delivered"
    )


@pytest.mark.asyncio
async def test_send_without_connection_reaches_the_caller_of_execute_phase_action(tmp_path: Path):
    agent = _agent(tmp_path)
    assert isinstance(agent.transport, WebSocketTransport)
    agent.transport.ws = None

    outcome = await _outcome(agent)

    assert outcome.startswith("raised") or outcome == "returned False", (
        f"no connection, yet execute_phase_action {outcome}: the action was dropped without the agent knowing"
    )
