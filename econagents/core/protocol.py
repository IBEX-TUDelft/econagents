"""Helpers for the WebSocket message protocol.

The game server speaks a uniform JSON envelope::

    {"meta": {"type": <event-type>, "component": {...}}, "payload": {...}}

* ``meta.type`` is the event/message discriminator.
* ``meta.component`` (optional) routes the message to a server-side component,
  e.g. ``{"type": "standard:coordination"}``.
* ``payload`` carries the message data.

These helpers build outbound envelopes and define the standard handshake
messages, so games and the framework do not have to reconstruct them by hand.
"""

from typing import Any, Optional, Union

#: Name of the phase in which players declare themselves ready.
INTRODUCTION_PHASE = "introduction"


def build_message(
    type: str,
    payload: Optional[dict[str, Any]] = None,
    component: Optional[Union[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a message envelope.

    Args:
        type: Value for ``meta.type`` (the message discriminator).
        payload: Message data placed under ``payload``. Defaults to ``{}``.
        component: Optional ``meta.component`` reference. A string is expanded
            to ``{"type": <string>}``; a dict is used as-is.

    Returns:
        The ``{"meta": {...}, "payload": {...}}`` envelope.
    """
    meta: dict[str, Any] = {"type": type}
    if component is not None:
        meta["component"] = {"type": component} if isinstance(component, str) else component
    return {"meta": meta, "payload": payload or {}}


def join_message(**payload: Any) -> dict[str, Any]:
    """Build the ``join`` envelope used to authenticate a connection.

    The keyword arguments become the envelope ``payload`` (typically
    ``recovery="<code>"``).
    """
    return build_message("join", payload=dict(payload))


def ready_message() -> dict[str, Any]:
    """Build the ``ready`` envelope for the standard ready component."""
    return build_message("ready", component="standard:ready")
