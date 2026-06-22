"""JSON response parsing adapter."""

import json
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from econagents.domain.state.game import GameStateProtocol
from econagents.domain.messages import PhaseId


class JsonResponseParser:
    """Parse structured-output instances, schema-validated JSON, or raw JSON."""

    def parse(
        self,
        response: str | BaseModel,
        state: GameStateProtocol,
        phase: PhaseId,
        response_schema: Type[BaseModel] | None = None,
        logger: Any | None = None,
    ) -> dict[str, Any]:
        """Parse one LLM response into an action payload."""
        if isinstance(response, BaseModel):
            return response.model_dump()

        if response_schema is not None:
            try:
                return response_schema.model_validate_json(response).model_dump()
            except ValidationError as exc:
                if logger is not None:
                    logger.error(f"Failed to validate LLM response against schema {response_schema.__name__}: {exc}")
                    logger.debug(f"Raw response: {response}")
                return {"error": "Failed to validate response", "raw_response": response}

        try:
            return json.loads(response)
        except json.JSONDecodeError as exc:
            if logger is not None:
                logger.error(f"Failed to parse LLM response as JSON: {exc}")
                logger.debug(f"Raw response: {response}")
            return {"error": "Failed to parse response", "raw_response": response}
