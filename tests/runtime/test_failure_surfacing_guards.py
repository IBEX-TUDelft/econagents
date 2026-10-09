"""IBEX-game_suite#7 guards (pass before and after the fix).

Making send failures and loop exceptions visible must not change the paths that work today:
a delivered message still goes out once without error, a phase change still cancels the
continuous loop quietly, and a complete-but-reasoning-only response is still logged.
"""

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from econagents.adapters.transport import WebSocketTransport
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime import Agent, PhaseEngine

from tests.adapters.llm.test_openai_truncation import _body, _call, tracked_metadata
from tests.runtime.test_agent_loop_failures import BOUND_S, ENVELOPE, FakeTransport


@pytest.mark.asyncio
async def test_successful_send_is_delivered_once_without_error():
    transport = WebSocketTransport(url="ws://127.0.0.1:9")
    transport.ws = MagicMock(send=AsyncMock(return_value=None))

    result = await transport.send('{"meta": {"type": "ready"}, "payload": {}}')

    transport.ws.send.assert_awaited_once_with('{"meta": {"type": "ready"}, "payload": {}}')
    assert result is not False


@pytest.mark.asyncio
async def test_phase_change_cancels_the_continuous_loop_quietly(tmp_path: Path, caplog):
    looping = asyncio.Event()
    calls = {"market": 0}

    async def handle_phase(phase, state, prompts_path):
        if phase == "market":
            calls["market"] += 1
            if calls["market"] >= 3:
                looping.set()
            return ENVELOPE
        return None

    role = MagicMock(spec=Role)
    role.name = "trader"
    role.handle_phase = handle_phase
    name = "gs7.guard.cancel"
    agent = Agent(
        url="ws://127.0.0.1:9",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=FakeTransport(),
        phase_engine=PhaseEngine(continuous_phases={"market"}, min_action_delay=0, max_action_delay=0),
        logger=logging.getLogger(name),
    )
    with caplog.at_level(logging.DEBUG, logger=name):
        await agent.handle_phase_transition("market")
        await asyncio.wait_for(looping.wait(), BOUND_S)
        task = agent._continuous_task
        await agent.handle_phase_transition("results")
        await asyncio.gather(task, return_exceptions=True)
        after = calls["market"]
        for _ in range(5):
            await asyncio.sleep(0)

    assert task.done()
    assert calls["market"] == after
    assert not [r for r in caplog.records if r.name == name and r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_reasoning_only_incomplete_response_is_logged(caplog):
    name = "gs7.guard.reasoning_only"
    with caplog.at_level(logging.DEBUG, logger=name):
        observability = await _call(_body(None), logging.getLogger(name))
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name == name)
    assert "max_output_tokens" in logged
    assert observability.track_llm_call.call_count == 1
    assert all(tracked_metadata(observability).values())
