from abc import ABC, abstractmethod
import asyncio
import json
import logging
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from econagents.adapters.protocol import join_message
from econagents.domain.logging import LoggerMixin
from econagents.ports.transport import TransportSendError


class AuthenticationMechanism(ABC):
    """Abstract base class for authentication mechanisms."""

    @abstractmethod
    async def authenticate(self, transport: "WebSocketTransport", **kwargs) -> bool:
        """Authenticate the transport."""
        pass

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type, _handler):
        from pydantic_core import core_schema

        return core_schema.is_instance_schema(AuthenticationMechanism)


class SimpleLoginPayloadAuth(AuthenticationMechanism):
    """Authentication mechanism that sends a login payload as the first message."""

    async def authenticate(self, transport: "WebSocketTransport", **kwargs) -> bool:
        """Send the login payload as a JSON message."""
        initial_message = json.dumps(kwargs)
        await transport.send(initial_message)
        return True


class JoinPayloadAuth(AuthenticationMechanism):
    """Default authentication mechanism.

    Sends a ``join`` envelope as the first message on the connection::

        {"meta": {"type": "join"}, "payload": {<kwargs>}}

    The keyword arguments passed via ``auth_mechanism_kwargs`` become the
    ``payload`` (typically ``{"recovery": "<code>"}``). If the kwargs already
    contain a ``meta`` key they are treated as a fully-formed envelope and sent
    as-is, so callers may still pass an explicit envelope when needed.
    """

    async def authenticate(self, transport: "WebSocketTransport", **kwargs) -> bool:
        """Send the join envelope as a JSON message."""
        envelope = kwargs if "meta" in kwargs else join_message(**kwargs)
        await transport.send(json.dumps(envelope))
        return True


class WebSocketTransport(LoggerMixin):
    """
    Responsible for connecting to a WebSocket, sending/receiving messages,
    and reporting received messages to a callback function.
    """

    def __init__(
        self,
        url: str,
        logger: Optional[logging.Logger] = None,
        auth_mechanism: Optional[AuthenticationMechanism] = None,
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        on_message_callback: Optional[Callable[[str], Any]] = None,
    ):
        """
        Initialize the WebSocket transport.

        Args:
            url: WebSocket server URL
            logger: (Optional) Logger instance
            auth_mechanism: (Optional) Authentication mechanism
            auth_mechanism_kwargs: (Optional) Keyword arguments to pass to auth_mechanism during authentication
            on_message_callback: Callback function that receives raw message strings.
                               Can be synchronous or asynchronous.
        """
        self.url = url
        self.auth_mechanism = auth_mechanism
        self.auth_mechanism_kwargs = auth_mechanism_kwargs
        if logger:
            self.logger = logger
        self.on_message_callback = on_message_callback
        self.ws: Optional[ClientConnection] = None
        self._running = False
        self._listening = False
        self._authenticated = False

    async def _authenticate(self) -> bool:
        """Authenticate the current connection.

        Returns False when the mechanism rejects the connection or fails; a lost connection propagates as
        ``ConnectionError`` or ``ConnectionClosed`` so the caller can reconnect.
        """
        if self.auth_mechanism:
            try:
                auth_success = await self.auth_mechanism.authenticate(self, **(self.auth_mechanism_kwargs or {}))
            except (ConnectionError, ConnectionClosed):
                raise
            except Exception as e:
                self.logger.exception(f"Transport authentication error: {e}")
                return False
            if not auth_success:
                self.logger.error("Authentication failed")
                return False
        self._authenticated = True
        return True

    async def start_listening(self):
        """Connect and dispatch received messages until stopped.

        Every connection, including each one opened after an unexpected or clean close, is authenticated
        before its messages are read. Only one listen loop runs per transport: a second call while one is
        active returns immediately.
        """
        if self._listening:
            self.logger.warning("WebSocketTransport: already listening; ignoring second start_listening().")
            return
        self.logger.info("WebSocketTransport: starting to listen.")
        self._listening = True
        self._running = True

        try:
            async for websocket in websockets.connect(self.url):
                if not self._running:
                    self.logger.info("WebSocketTransport: stopping as requested.")
                    break

                self.ws = websocket
                self._authenticated = False
                try:
                    if not await self._authenticate():
                        self.logger.error("Authentication failed. Stopping transport.")
                        break

                    async for message in websocket:
                        if not self._running:
                            break
                        if self.on_message_callback:
                            self.logger.info(f"<-- Transport received: {message}")
                            await self.on_message_callback(message)

                    if not self._running:
                        self.logger.info("WebSocketTransport: stopping as requested.")
                        break
                    self.logger.info(
                        f"WebSocketTransport: server closed the connection ({websocket.close_code}); reconnecting..."
                    )
                except (ConnectionClosed, ConnectionError) as e:
                    if not self._running:
                        self.logger.info("WebSocketTransport: connection closed by client. Stopping transport.")
                        break
                    self.logger.info(f"WebSocketTransport: connection lost ({e}); reconnecting...")
                except Exception as e:
                    self.logger.exception(f"Error in receive loop: {e}")
                    break
                finally:
                    self._authenticated = False
                    if self.ws is websocket:
                        self.ws = None
                    try:
                        await websocket.close()
                        self.logger.info("WebSocketTransport: connection closed.")
                    except Exception as e:
                        self.logger.debug(f"Error closing websocket: {e}")
        except Exception as e:
            self.logger.exception(f"Error in start_listening: {e}")
        finally:
            self._running = False
            self._listening = False
            self.logger.info("WebSocketTransport: stopped listening.")

    async def send(self, message: str) -> None:
        """Send a raw string message on the current connection.

        Raises:
            TransportSendError: There is no open connection, or the connection closed or the socket failed
                while writing the frame; the message was not transmitted.
        """
        ws = self.ws
        if ws is None:
            raise TransportSendError("WebSocketTransport: no open connection; message not transmitted")
        self.logger.debug(f"--> Transport sending: {message}")
        try:
            await ws.send(message)
        except (ConnectionClosed, OSError) as e:
            raise TransportSendError(f"WebSocketTransport: send failed; message not transmitted: {e}") from e

    async def stop(self):
        """Gracefully close the WebSocket connection."""
        self.logger.info("WebSocketTransport: stopping...")
        self._running = False
        self._authenticated = False
        if self.ws:
            try:
                await self.ws.close()
                self.logger.info("WebSocketTransport: connection closed.")
            except Exception as e:
                self.logger.debug(f"Error during stop: {e}")
            finally:
                self.ws = None
