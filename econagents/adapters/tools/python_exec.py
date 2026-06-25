"""A read-only Python execution tool backed by Monty.

Monty (``pydantic-monty``) is a sandboxed Python interpreter written in Rust:
filesystem, environment and network access are all blocked unless explicitly
provided via external functions. This makes it safe to let an agent run code it
generates to compute payoffs, run what-if scenarios, or crunch numbers, without
giving it access to the host.

Install with ``pip install econagents[monty]``.
"""

from __future__ import annotations

import importlib.util
from typing import Any, ClassVar, Optional, Type

from pydantic import BaseModel, Field

from econagents.adapters.tools.base import BaseTool
from econagents.ports.tools import ToolContext


class PythonExecInput(BaseModel):
    """Arguments for the Python execution tool."""

    code: str = Field(
        description=(
            "Python code to run in a sandboxed interpreter. There is no "
            "filesystem, network, or environment access. Make the final line an "
            "expression whose value is the answer you want returned."
        )
    )


class PythonExecutionTool(BaseTool):
    """Execute LLM-written Python in a Monty sandbox and return the result.

    The value of the final expression is returned under ``result``. The sandbox
    is stateless across calls: each invocation runs in a fresh session.
    """

    name: ClassVar[str] = "python"
    description: ClassVar[str] = (
        "Run Python code in a secure sandbox (no filesystem, network, or env "
        "access) and get back the value of the final expression. Use it for "
        "calculations and data manipulation."
    )
    params_model: ClassVar[Optional[Type[BaseModel]]] = PythonExecInput

    def __init__(self, type_check: bool = False) -> None:
        self._check_monty_available()
        self._type_check = type_check

    @staticmethod
    def _check_monty_available() -> None:
        if not importlib.util.find_spec("pydantic_monty"):
            raise ImportError("pydantic-monty is not installed. Install it with: pip install econagents[monty]")

    async def execute(self, arguments: PythonExecInput, ctx: ToolContext) -> dict[str, Any]:
        import pydantic_monty

        stdout = pydantic_monty.CollectString()
        try:
            runner = pydantic_monty.Monty(arguments.code, type_check=self._type_check)
            result = await runner.run_async(print_callback=stdout)
            return {"result": repr(result), "stdout": stdout.output}
        except Exception as exc:  # noqa: BLE001 - returned to the model, not raised
            if ctx.logger is not None:
                ctx.logger.debug(f"Python tool execution failed: {exc}")
            return {"error": f"{type(exc).__name__}: {exc}", "stdout": stdout.output}
