"""Reproduction for IBEX-game_suite#10 (FPM-23): original model inputs and outputs are not retained.

At the default INFO level a game run leaves no record of the prompts actually sent to the model, the
raw model output, or the provider's response id, finish reason and token usage: Role logs prompts at
DEBUG and ChatOpenAI only DEBUG-logs the provider response. Replay tooling therefore re-renders
today's templates instead of recovering what was sent. These checks are black-box: they search
everything the runner persisted under ``logs_dir`` (any file, plain text or JSON).

- behavioral: rendered prompts and raw output are recoverable after an INFO-level run.
- behavioral: provider response id, finish reason and token usage are recoverable.
- guard: recording does not change what goes on the wire or the number of model calls.
"""

import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from econagents.adapters.llm.base import BaseLLM
from econagents.adapters.llm.observability import get_observability_provider
from econagents.adapters.llm.openai import ChatOpenAI
from econagents.domain.messages import Event
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime.agent import Agent
from econagents.runtime.game_runner import GameRunner, GameRunnerConfig

GAME_ID = 21
PLAYER = 7
RAW_OUTPUT = '{"message": "scripted-output-gs10", "price": 4321}'


class ScriptedLLM(BaseLLM):
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    async def get_response(self, messages, tracing_extra, response_schema=None, **kwargs) -> str:
        self.calls.append(messages)
        return self.responses.pop(0)


class SpeculatorRole(Role):
    role = 3
    name = "speculator"
    llm = ScriptedLLM([])


class PhaseTransport:
    """Transport stand-in: delivers one phase-transition to the agent and records what it sends."""

    def __init__(self) -> None:
        self.agent: Agent | None = None
        self.sent: list[str] = []
        self.logger = logging.getLogger("unbound-transport")

    async def start_listening(self) -> None:
        assert self.agent is not None
        await self.agent.on_event(Event(type="phase-transition", data={"phase": 1}))

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def stop(self) -> None:
        return None


@pytest.fixture
def prompts(tmp_path) -> Path:
    path = tmp_path / "prompts"
    path.mkdir()
    (path / "all_system.jinja2").write_text("You are player {{ meta.player_number }}. sentinel-system-gs10")
    (path / "all_user.jinja2").write_text(
        "Phase {{ meta.phase }} for player {{ meta.player_number }}. sentinel-user-gs10"
    )
    return path


@pytest.fixture
def config(tmp_path, prompts) -> GameRunnerConfig:
    return GameRunnerConfig(
        hostname="127.0.0.1",
        port=9,
        path="",
        game_id=GAME_ID,
        logs_dir=tmp_path / "logs",
        prompts_dir=prompts,
        log_level=logging.INFO,
        max_game_duration=0,
    )


async def run_one_decision(config: GameRunnerConfig, llm: BaseLLM) -> tuple[Agent, PhaseTransport]:
    state = GameState()
    state.meta.game_id = GAME_ID
    state.meta.player_number = PLAYER
    role = SpeculatorRole()
    role.llm = llm
    transport = PhaseTransport()
    agent = Agent(url="ws://127.0.0.1:9", state=state, role=role, prompts_dir=config.prompts_dir, transport=transport)
    transport.agent = agent
    await GameRunner(config=config, agents=[agent]).run_game()
    return agent, transport


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def persisted_text(config: GameRunnerConfig) -> tuple[str, set[str]]:
    """Everything under logs_dir as text, plus every string value of any JSON / JSONL record found there."""
    text, values = [], set()
    for path in sorted(config.logs_dir.rglob("*")):
        if not path.is_file():
            continue
        content = path.read_text(errors="replace")
        text.append(content)
        for chunk in [content, *content.splitlines()]:
            try:
                values.update(_strings(json.loads(chunk)))
            except ValueError:
                continue
    return "\n".join(text), values


def is_persisted(needle: str, config: GameRunnerConfig) -> bool:
    text, values = persisted_text(config)
    return needle in text or needle in values


@pytest.mark.asyncio
async def test_rendered_prompts_and_raw_output_are_recoverable_after_an_info_run(config):
    """behavioral: the exact messages sent to the model and its raw output survive an INFO-level run."""
    llm = ScriptedLLM([RAW_OUTPUT])
    await run_one_decision(config, llm)
    assert len(llm.calls) == 1

    missing = [m["role"] for m in llm.calls[0] if not is_persisted(m["content"], config)]
    assert missing == [], (
        f"the {missing} prompt(s) actually sent to the model are not recoverable from {config.logs_dir} "
        f"(rendered prompts are only logged at DEBUG); sent: {llm.calls[0]!r}"
    )
    assert is_persisted(RAW_OUTPUT, config), (
        f"raw model output {RAW_OUTPUT!r} is not recoverable from {config.logs_dir}"
    )


@pytest.mark.asyncio
async def test_provider_response_metadata_is_recoverable_after_an_info_run(config):
    """behavioral: response id, finish reason and token usage of the provider call are recorded."""
    response = SimpleNamespace(
        id="resp_gs10_provenance",
        model="gpt-5.4-mini-2026-03-17",
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        usage=SimpleNamespace(
            input_tokens=48213,
            output_tokens=7919,
            total_tokens=56132,
            output_tokens_details=SimpleNamespace(reasoning_tokens=6011),
        ),
        output=[],
        output_text=RAW_OUTPUT,
        output_parsed=None,
    )
    client = MagicMock()
    client.responses.create = AsyncMock(return_value=response)
    with patch("importlib.util.find_spec", return_value=True), patch("openai.AsyncOpenAI", return_value=client):
        llm = ChatOpenAI(model_name="gpt-5.4-mini", api_key="sk-test-not-used", reasoning_effort="medium")
        llm.observability = get_observability_provider("noop")
        _, transport = await run_one_decision(config, llm)
    assert client.responses.create.await_count == 1
    assert transport.sent, "the scripted decision did not reach the transport"

    text, values = persisted_text(config)
    corpus = text + "\n" + "\n".join(values)
    missing = [
        label
        for label, pattern in [
            ("response id", r"resp_gs10_provenance"),
            ("input token usage", r"\b48213\b"),
            ("output token usage", r"\b7919\b"),
            ("finish reason", r"max_output_tokens"),
        ]
        if not re.search(pattern, corpus)
    ]
    assert missing == [], f"provider {missing} not recorded anywhere under {config.logs_dir} after an INFO run"


@pytest.mark.asyncio
async def test_recording_does_not_change_wire_output_or_model_calls(config):
    """guard: one decision means one model call and the parsed output is what reaches the wire."""
    llm = ScriptedLLM([RAW_OUTPUT])
    _, transport = await run_one_decision(config, llm)
    assert len(llm.calls) == 1
    assert [json.loads(m) for m in transport.sent] == [json.loads(RAW_OUTPUT)]
