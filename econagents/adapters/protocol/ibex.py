"""IBEX protocol adapter."""

import json
from typing import Any

from econagents.domain.messages import Action, Event
from econagents.ports.codec import MessageDecodeError

INTRODUCTION_PHASE = "introduction"


def build_message(
    type: str,
    payload: dict[str, Any] | None = None,
    component: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an IBEX message envelope."""
    meta: dict[str, Any] = {"type": type}
    if component is not None:
        meta["component"] = {"type": component} if isinstance(component, str) else component
    return {"meta": meta, "payload": payload or {}}


def join_message(**payload: Any) -> dict[str, Any]:
    """Build the IBEX join envelope."""
    return build_message("join", payload=dict(payload))


def ready_message() -> dict[str, Any]:
    """Build the IBEX ready envelope."""
    return build_message("ready", component="standard:ready")


class IbexMessageCodec:
    """Translate IBEX WebSocket envelopes to and from domain messages.

    Inbound messages use the IBEX shape ``{"meta": {"type": ...},
    "payload": {...}}``.
    """

    def decode_event(self, raw_message: str) -> Event:
        """Decode an inbound wire message into a domain event."""
        try:
            decoded = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            raise MessageDecodeError("Invalid JSON received.") from exc

        if not isinstance(decoded, dict):
            return Event(type="", data={}, raw=decoded)

        if "meta" in decoded or "payload" in decoded:
            meta = decoded.get("meta") or {}
            payload = decoded.get("payload") or {}
            return Event(
                type=meta.get("type", "") if isinstance(meta, dict) else "",
                data=payload if isinstance(payload, dict) else {},
                raw=decoded,
            )

        return Event(type="", data={}, raw=decoded)

    def encode_action(self, action: dict[str, Any] | Action) -> str:
        """Encode an action as a JSON string.

        Dict actions are treated as already-shaped outbound payloads.
        """
        payload = action.as_payload() if isinstance(action, Action) else action
        return json.dumps(payload)

    def encode_join(self, payload: dict[str, Any]) -> str:
        """Encode an IBEX join envelope."""
        envelope = payload if "meta" in payload else join_message(**payload)
        return json.dumps(envelope)

    def encode_ready(self) -> str:
        """Encode an IBEX ready envelope."""
        return json.dumps(ready_message())
