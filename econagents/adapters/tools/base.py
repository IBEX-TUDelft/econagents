"""Convenience base class for defining read-only tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional, Type

from pydantic import BaseModel

from econagents.ports.tools import ToolContext, ToolSpec


class BaseTool(ABC):
    """Base class for tools that derive their schema from a Pydantic model.

    Subclasses set ``name``, ``description`` and ``params_model`` and implement
    :meth:`run`. The advertised JSON Schema is taken from ``params_model``;
    incoming arguments are validated against it before :meth:`run` is called.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    params_model: ClassVar[Optional[Type[BaseModel]]] = None

    def spec(self) -> ToolSpec:
        if self.params_model is not None:
            parameters = self.params_model.model_json_schema()
        else:
            parameters = {"type": "object", "properties": {}}
        return ToolSpec(name=self.name, description=self.description, parameters=parameters)

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> Any:
        if self.params_model is not None:
            validated = self.params_model.model_validate(arguments)
            return await self.execute(validated, ctx)
        return await self.execute(arguments, ctx)

    @abstractmethod
    async def execute(self, arguments: Any, ctx: ToolContext) -> Any:
        """Compute the tool result.

        ``arguments`` is a validated ``params_model`` instance when one is set,
        otherwise the raw arguments dict. Return a JSON-serializable value.
        """
        ...
