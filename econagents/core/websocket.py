import json
import logging
from abc import abstractmethod
from typing import Any

import websockets


class WebSocketClient:
    def __init__(self, url: str, login_payload: dict[str, Any], game_id: int, logger: logging.Logger):
        self.logger = logger
        self.url = url
        self.ws = None
        self.task = None
        self.running = False
        self.login_payload = login_payload
        self.game_id = game_id

    @abstractmethod
    async def on_message(self, message):
        """Handle incoming messages from the server."""
        raise NotImplementedError("Subclasses must implement this method")

    async def connect(self):
        try:
            self.ws = await websockets.connect(self.url, ping_interval=30, ping_timeout=10)
            self.logger.info("WebSocket connection opened.")
            initial_message = json.dumps(self.login_payload)
            self.logger.debug(f"Sending initial message: {initial_message}")
            await self.send_message(initial_message)
        except Exception:
            self.logger.exception("Connection error", exc_info=True)
            return False
        else:
            return True

    async def send_message(self, message):
        try:
            self.logger.debug(f"Sending: {message}")
            await self.ws.send(message)
        except Exception:
            self.logger.exception("Error sending message", exc_info=True)

    async def receive_messages(self):
        while True:
            try:
                message = await self.ws.recv()
                await self.on_message(message)
            except websockets.exceptions.ConnectionClosed:
                self.logger.info("WebSocket connection closed")
                break
            except Exception:
                self.logger.exception("Error in receive loop", exc_info=True)
                break

    async def start(self):
        self.running = True
        if await self.connect():
            self.logger.info("Connected to WebSocket server. Receiving messages...")
            await self.receive_messages()
        else:
            self.logger.exception("Failed to connect to WebSocket server", exc_info=True)

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
        if self.ws:
            await self.ws.close()
            self.logger.info("WebSocket client stopped.")
