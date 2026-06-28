"""Tool port.

Tools are read-only, computational helpers an agent may call during a phase
(e.g. compute a payoff, look up history, summarize state). They never mutate
game state or send messages; the phase's parsed response remains the only
action an agent takes in the game.

The provider-native tool-calling loop lives in the LLM adapters. The domain
layer supplies provider-agnostic ``ToolSpec``s plus a ``tool_executor``
callback, keeping which-tools/how-to-run policy out of the adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from econagents.domain.messages import PhaseId
from econagents.domain.state.game import GameStateProtocol


@dataclass(frozen=True)
class ToolSpec:
    """Provider-agnostic description of a callable tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    """JSON Schema for the tool's arguments."""


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    """Provider call id, echoed back when returning the result."""
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolContext:
    """Read-only context handed to a tool when it runs."""

    state: GameStateProtocol
    phase: PhaseId
    logger: Any | None = None


#: Closure the domain passes to an adapter to execute one tool call.
ToolExecutor = Callable[[ToolCall], Awaitable[Any]]


@runtime_checkable
class Tool(Protocol):
    """Interface for a read-only tool an agent can call."""

    name: str
    description: str

    def spec(self) -> ToolSpec:
        """Return the provider-agnostic spec advertised to the model."""
        ...

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> Any:
        """Execute the tool and return a JSON-serializable result."""
        ...
