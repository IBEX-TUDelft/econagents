import json
from typing import ClassVar, Optional, Type

import pytest
from pydantic import BaseModel

from econagents.adapters.parsing import JsonResponseParser
from econagents.adapters.prompts import JinjaPromptRenderer
from econagents.adapters.tools import BaseTool
from econagents.domain.role import Role
from econagents.domain.state.game import GameStateProtocol
from econagents.ports.tools import ToolCall, ToolContext
from tests.conftest import MockLLM, SimpleGameState


class _EchoArgs(BaseModel):
    value: int


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Echo a value back"
    params_model: ClassVar[Optional[Type[BaseModel]]] = _EchoArgs

    async def execute(self, arguments: _EchoArgs, ctx: ToolContext):
        # Record that the tool saw the live game state.
        return {"echoed": arguments.value, "phase": ctx.phase}


class _ToolForwardingLLM(MockLLM):
    """Captures the tools/executor passed and exercises the executor once."""

    def __init__(self):
        self.captured = {}

    async def get_response(self, *args, **kwargs):
        self.captured = kwargs
        executor = kwargs.get("tool_executor")
        if executor is not None:
            self.tool_result = await executor(ToolCall(id="1", name="echo", arguments={"value": 9}))
        return json.dumps({"message": "done"})


class _ToolRole(Role[GameStateProtocol]):
    role: ClassVar[int] = 1
    name: ClassVar[str] = "test_role"
    prompt_renderer = JinjaPromptRenderer()
    response_parser = JsonResponseParser()


@pytest.fixture
def state():
    s = SimpleGameState()
    s.meta.phase = 3
    return s


class TestRoleToolWiring:
    @pytest.mark.asyncio
    async def test_tools_and_executor_forwarded_to_llm(self, state, prompts_path, logger):
        llm = _ToolForwardingLLM()
        role = _ToolRole(logger=logger, tools=[_EchoTool()])
        role.llm = llm

        await role.handle_phase_with_llm(phase=3, state=state, prompts_path=prompts_path)

        specs = llm.captured["tools"]
        assert [s.name for s in specs] == ["echo"]
        assert callable(llm.captured["tool_executor"])
        # The executor dispatched to the registered tool with the live context.
        assert llm.tool_result == {"echoed": 9, "phase": 3}

    @pytest.mark.asyncio
    async def test_no_tools_means_no_tool_kwargs(self, state, prompts_path, logger):
        llm = _ToolForwardingLLM()
        role = _ToolRole(logger=logger)
        role.llm = llm

        await role.handle_phase_with_llm(phase=3, state=state, prompts_path=prompts_path)

        assert "tools" not in llm.captured
        assert "tool_executor" not in llm.captured

    @pytest.mark.asyncio
    async def test_unknown_tool_call_returns_error_payload(self, state, prompts_path, logger):
        role = _ToolRole(logger=logger, tools=[_EchoTool()])
        kwargs = role._build_tool_kwargs(phase=3, state=state)
        out = await kwargs["tool_executor"](ToolCall(id="1", name="missing", arguments={}))
        assert "error" in out
