"""Transport ports."""

from typing import Protocol


class TransportPort(Protocol):
    """Minimal async transport interface used by agents."""

    async def start_listening(self) -> None:
        """Start receiving messages."""
        ...

    async def send(self, message: str) -> None:
        """Send a raw outbound message."""
        ...

    async def stop(self) -> None:
        """Stop the transport."""
        ...
