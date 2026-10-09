"""Transport ports."""

from typing import Protocol


class TransportSendError(ConnectionError):
    """An outbound message was not transmitted: there was no open connection, or writing it failed."""


class TransportPort(Protocol):
    """Minimal async transport interface used by agents."""

    async def start_listening(self) -> None:
        """Start receiving messages."""
        ...

    async def send(self, message: str) -> None:
        """Send a raw outbound message.

        Raises:
            ConnectionError: The message was not transmitted (``TransportSendError`` or a subclass of
                ``ConnectionError``).
        """
        ...

    async def stop(self) -> None:
        """Stop the transport."""
        ...
