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

    async def connect(self) -> bool:
        """Establish the WebSocket connection and authenticate."""
        try:
            self.ws = await websockets.connect(self.url, ping_interval=30, ping_timeout=10)
            self.logger.info("WebSocketTransport: connection opened.")

            # Perform authentication using the callback
            if self.auth_mechanism:
                if not self.auth_mechanism_kwargs:
                    self.auth_mechanism_kwargs = {}
                auth_success = await self.auth_mechanism.authenticate(self, **self.auth_mechanism_kwargs)
                if not auth_success:
                    self.logger.error("Authentication failed")
                    await self.stop()
                    self.ws = None  # Ensure ws is set to None after stopping
                    return False

        except Exception as e:
            self.logger.exception(f"Transport connection error: {e}")
            return False
        else:
            return True

    async def start_listening(self):
        """Begin receiving messages in a loop."""
        self._running = True
        while self._running and self.ws:
            try:
                message_str = await self.ws.recv()
                if self.on_message_callback:
                    # Call the callback, supporting both sync and async functions
                    self.logger.debug(f"<-- Transport received: {message_str}")
                    result = self.on_message_callback(message_str)
                    # If the callback is a coroutine function, await it
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
            except ConnectionClosed:
                self.logger.info("WebSocket connection closed by remote.")
                break
            except Exception:
                self.logger.exception("Error in receive loop.")
                break
        self._running = False

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
        self._running = False
        if self.ws:
            await self.ws.close()
            self.logger.info("WebSocketTransport: connection closed.")
            self.ws = None  # Set ws to None after closing
