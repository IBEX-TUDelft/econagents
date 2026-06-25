"""Registry that holds an agent's tools and dispatches calls."""

from __future__ import annotations

from typing import Any, Iterable

from econagents.ports.tools import Tool, ToolCall, ToolContext, ToolSpec


class ToolRegistry:
    """Holds tools by name, exposes their specs, and invokes them by call."""

    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"A tool named {tool.name!r} is already registered.")
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def specs(self) -> list[ToolSpec]:
        """Provider-agnostic specs for every registered tool."""
        return [tool.spec() for tool in self._tools.values()]

    async def invoke(self, call: ToolCall, ctx: ToolContext) -> Any:
        """Run the tool named by ``call`` and return its result.

        Unknown tool names and tool exceptions are returned as error payloads
        rather than raised, so a single bad call cannot abort the phase.
        """
        tool = self._tools.get(call.name)
        if tool is None:
            return {"error": f"Unknown tool: {call.name}"}
        try:
            return await tool.run(call.arguments, ctx)
        except Exception as exc:  # noqa: BLE001 - surfaced back to the model
            if ctx.logger is not None:
                ctx.logger.error(f"Tool {call.name!r} failed: {exc}")
            return {"error": f"Tool {call.name} failed: {exc}"}
