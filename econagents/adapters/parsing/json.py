"""JSON response parsing adapter."""

import json
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from econagents.domain.state.game import GameStateProtocol
from econagents.domain.messages import PhaseId


class ResponseParseError(ValueError):
    """An LLM response that is not valid JSON or does not match the phase's response schema."""

    def __init__(self, message: str, raw_response: Any) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class JsonResponseParser:
    """Parse structured-output instances, schema-validated JSON, or raw JSON.

    Raises ``ResponseParseError`` when the response cannot be parsed, so a role retries the
    decision or falls back instead of sending the failure as an action.
    """

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
                raise ResponseParseError(
                    f"Response does not match schema {response_schema.__name__}: {exc}", response
                ) from exc

        try:
            return json.loads(response)
        except json.JSONDecodeError as exc:
            if logger is not None:
                logger.error(f"Failed to parse LLM response as JSON: {exc}")
                logger.debug(f"Raw response: {response}")
            raise ResponseParseError(f"Response is not valid JSON: {exc}", response) from exc
