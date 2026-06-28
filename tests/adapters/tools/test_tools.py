from typing import ClassVar, Optional, Type

import pytest
from pydantic import BaseModel

from econagents.adapters.tools import BaseTool, CalculatorTool, ToolRegistry
from econagents.ports.tools import ToolCall, ToolContext


class _AddArgs(BaseModel):
    a: int
    b: int


class _AddTool(BaseTool):
    name: ClassVar[str] = "add"
    description: ClassVar[str] = "Add two integers"
    params_model: ClassVar[Optional[Type[BaseModel]]] = _AddArgs

    async def execute(self, arguments: _AddArgs, ctx: ToolContext):
        return arguments.a + arguments.b


def _ctx():
    return ToolContext(state=None, phase=1, logger=None)


class TestBaseTool:
    def test_spec_derived_from_params_model(self):
        spec = _AddTool().spec()
        assert spec.name == "add"
        assert spec.parameters["properties"].keys() == {"a", "b"}

    @pytest.mark.asyncio
    async def test_run_validates_arguments(self):
        result = await _AddTool().run({"a": 2, "b": 5}, _ctx())
        assert result == 7


class TestToolRegistry:
    def test_specs_lists_every_tool(self):
        registry = ToolRegistry([_AddTool()])
        assert [s.name for s in registry.specs()] == ["add"]
        assert "add" in registry and len(registry) == 1

    def test_duplicate_name_rejected(self):
        with pytest.raises(ValueError):
            ToolRegistry([_AddTool(), _AddTool()])

    @pytest.mark.asyncio
    async def test_invoke_dispatches_by_name(self):
        registry = ToolRegistry([_AddTool()])
        out = await registry.invoke(ToolCall(id="1", name="add", arguments={"a": 1, "b": 2}), _ctx())
        assert out == 3

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        registry = ToolRegistry([_AddTool()])
        out = await registry.invoke(ToolCall(id="1", name="nope", arguments={}), _ctx())
        assert "error" in out

    @pytest.mark.asyncio
    async def test_tool_exception_is_captured(self):
        registry = ToolRegistry([_AddTool()])
        out = await registry.invoke(ToolCall(id="1", name="add", arguments={"a": "x"}), _ctx())
        assert "error" in out


class TestCalculatorTool:
    @pytest.mark.asyncio
    async def test_evaluates_expression(self):
        out = await CalculatorTool().run({"expression": "2 * (3 + 4) ** 2"}, _ctx())
        assert out["result"] == 98

    @pytest.mark.asyncio
    async def test_unary_and_division(self):
        out = await CalculatorTool().run({"expression": "-10 / 4"}, _ctx())
        assert out["result"] == -2.5

    @pytest.mark.asyncio
    async def test_division_by_zero_returns_error(self):
        out = await CalculatorTool().run({"expression": "1 / 0"}, _ctx())
        assert "Division by zero" in out["error"]

    @pytest.mark.asyncio
    async def test_rejects_non_arithmetic(self):
        out = await CalculatorTool().run({"expression": "__import__('os').getcwd()"}, _ctx())
        assert "Invalid expression" in out["error"]

    @pytest.mark.asyncio
    async def test_rejects_names(self):
        out = await CalculatorTool().run({"expression": "a + 1"}, _ctx())
        assert "Invalid expression" in out["error"]


class TestPythonExecutionTool:
    @pytest.mark.asyncio
    async def test_executes_and_returns_result(self):
        pytest.importorskip("pydantic_monty")
        from econagents.adapters.tools import PythonExecutionTool

        out = await PythonExecutionTool().run({"code": "total = sum(range(5))\nprint('hi', total)\ntotal"}, _ctx())
        assert out["result"] == "10"
        assert "hi 10" in out["stdout"]

    @pytest.mark.asyncio
    async def test_runtime_error_returned_not_raised(self):
        pytest.importorskip("pydantic_monty")
        from econagents.adapters.tools import PythonExecutionTool

        out = await PythonExecutionTool().run({"code": "1 / 0"}, _ctx())
        assert "ZeroDivisionError" in out["error"]
