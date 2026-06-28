"""Flat JSON protocol adapter."""

import json
from typing import Any

from econagents.domain.messages import Action, Event
from econagents.ports.codec import MessageDecodeError


class FlatMessageCodec:
    """Translate flat JSON messages to and from domain messages."""

    def decode_event(self, raw_message: str) -> Event:
        """Decode a flat inbound message into a domain event."""
        try:
            decoded = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            raise MessageDecodeError("Invalid JSON received.") from exc

        if not isinstance(decoded, dict):
            return Event(type="", data={}, raw=decoded)

        event_type = decoded.get("eventType") or decoded.get("type", "")
        data = decoded.get("data") or {}
        return Event(
            type=event_type,
            data=data if isinstance(data, dict) else {},
            source=decoded.get("type"),
            raw=decoded,
        )

    def encode_action(self, action: dict[str, Any] | Action) -> str:
        """Encode an action as a flat JSON string."""
        payload = action.as_payload() if isinstance(action, Action) else action
        return json.dumps(payload)
