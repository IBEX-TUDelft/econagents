"""Protocol translation ports."""

from typing import Any, Protocol

from econagents.domain.messages import Action, Event


class MessageDecodeError(ValueError):
    """Raised when a raw transport message cannot be decoded."""


class MessageCodec(Protocol):
    """Translate between external wire messages and internal events/actions."""

    def decode_event(self, raw_message: str) -> Event:
        """Decode a raw inbound message into a domain event."""
        ...

    def encode_action(self, action: dict[str, Any] | Action, *, reasoning: str | None = None) -> str:
        """Encode an outbound action for the transport.

        ``reasoning`` is why the agent took the action, or ``None``; a protocol without a place for it
        ignores it.
        """
        ...

    def encode_join(self, payload: dict[str, Any]) -> str:
        """Encode an authentication/join message."""
        ...

    def encode_ready(self) -> str:
        """Encode the standard ready message."""
        ...
