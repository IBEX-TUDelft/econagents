from abc import ABC, abstractmethod
import asyncio
import json
import logging
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from econagents.core.logging_mixin import LoggerMixin


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
        self._authenticated = False

    async def _authenticate(self) -> bool:
        """Authenticate the connection."""
        try:
            if self.auth_mechanism:
                if not self.auth_mechanism_kwargs:
                    self.auth_mechanism_kwargs = {}
                auth_success = await self.auth_mechanism.authenticate(self, **self.auth_mechanism_kwargs)
                if not auth_success:
                    self.logger.error("Authentication failed")
                    await self.stop()
                    self.ws = None
                    return False
            self._authenticated = True
        except Exception as e:
            self.logger.exception(f"Transport connection error: {e}")
            return False
        else:
            return True

    async def start_listening(self):
        """Begin receiving messages in a loop."""
        self.logger.info("WebSocketTransport: starting to listen.")
        self._running = True

        try:
            async for websocket in websockets.connect(self.url):
                if not self._running:
                    self.logger.info("WebSocketTransport: stopping as requested.")
                    break

                try:
                    self.ws = websocket

                    if not self._authenticated:
                        await self._authenticate()
                        if not self._authenticated:
                            self.logger.error("Authentication failed. Stopping transport.")
                            break

                    async for message in self.ws:
                        if not self._running:
                            break
                        if self.on_message_callback:
                            self.logger.info(f"<-- Transport received: {message}")
                            await self.on_message_callback(message)

                except ConnectionClosed as e:
                    self.logger.info(f"WebSocketTransport: connection closed: ({e.code}) {e.reason}")
                    if not self._running:
                        self.logger.info("WebSocketTransport: connection closed by client. Stopping transport.")
                        break
                    self.logger.info("WebSocketTransport: reconnecting...")
                    continue
                except Exception as e:
                    self.logger.exception(f"Error in receive loop: {e}")
                    break
                finally:
                    if self.ws:
                        try:
                            await self.ws.close()
                            self.logger.info("WebSocketTransport: connection closed.")
                        except Exception as e:
                            self.logger.debug(f"Error closing websocket: {e}")
                        finally:
                            self.ws = None
        except Exception as e:
            self.logger.exception(f"Error in start_listening: {e}")
        finally:
            self._running = False
            self.logger.info("WebSocketTransport: stopped listening.")

    async def send(self, message: str):
        """Send a raw string message to the WebSocket."""
        if self.ws:
            try:
                self.logger.debug(f"--> Transport sending: {message}")
                await self.ws.send(message)
            except Exception:
                self.logger.exception("Error sending message.")

    async def stop(self):
        """Gracefully close the WebSocket connection."""
        self.logger.info("WebSocketTransport: stopping...")
        self._running = False
        if self.ws:
            try:
                await self.ws.close()
                self.logger.info("WebSocketTransport: connection closed.")
            except Exception as e:
                self.logger.debug(f"Error during stop: {e}")
            finally:
                self.ws = None
                self._authenticated = False
