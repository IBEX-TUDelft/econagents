"""A simple, dependency-free arithmetic calculator tool.

Evaluates a single arithmetic expression using a whitelisted AST walk, so it is
safe to expose to an LLM without the Monty sandbox. For anything beyond
arithmetic (loops, data structures, functions) use ``PythonExecutionTool``.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, ClassVar, Optional, Type

from pydantic import BaseModel, Field

from econagents.adapters.tools.base import BaseTool
from econagents.ports.tools import ToolContext

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


class CalculatorInput(BaseModel):
    """Arguments for the calculator tool."""

    expression: str = Field(
        description=(
            "An arithmetic expression to evaluate, e.g. '2 * (3 + 4) ** 2'. "
            "Supports + - * / // % ** and parentheses over numbers only."
        )
    )


class CalculatorTool(BaseTool):
    """Evaluate a basic arithmetic expression and return the numeric result."""

    name: ClassVar[str] = "calculator"
    description: ClassVar[str] = (
        "Evaluate an arithmetic expression over numbers (supports + - * / // % ** "
        "and parentheses) and return the numeric result."
    )
    params_model: ClassVar[Optional[Type[BaseModel]]] = CalculatorInput

    async def execute(self, arguments: CalculatorInput, ctx: ToolContext) -> dict[str, Any]:
        try:
            tree = ast.parse(arguments.expression, mode="eval")
            return {"result": _eval_node(tree)}
        except ZeroDivisionError:
            return {"error": "Division by zero"}
        except (ValueError, SyntaxError, TypeError) as exc:
            return {"error": f"Invalid expression: {exc}"}
