import asyncio
import json
import logging

import websockets


class WebSocketClient:
    def __init__(self, url, game_id, recovery=None, verbose=True, logger=None):
        self.logger = logger
        self.url = url
        self.game_id = game_id
        self.recovery = recovery
        self.verbose = verbose
        self.ws = None
        self.task = None
        self.running = False

    async def on_message(self, message):
        if self.verbose:
            self.logger.info(f"← Received: {message}")
        else:
            self.logger.debug(f"← Received: {message}")

    async def connect(self):
        try:
            self.ws = await websockets.connect(self.url, ping_interval=30, ping_timeout=10)
            self.logger.info("WebSocket connection opened.")

            initial_message = json.dumps({"gameId": self.game_id, "type": "join", "recovery": self.recovery})

            if self.verbose:
                self.logger.debug(f"Sending initial message: {initial_message}")

            await self.send_message(initial_message)

        except Exception:
            self.logger.exception("Connection error")
            return False

    async def send_message(self, message):
        try:
            if self.verbose:
                self.logger.info(f"→ Sending: {message}")
            else:
                self.logger.debug(f"→ Sending: {message}")
            await self.ws.send(message)
        except Exception:
            self.logger.exception("Error sending message")

    async def receive_messages(self):
        while True:
            try:
                message = await self.ws.recv()
                await self.on_message(message)
            except websockets.exceptions.ConnectionClosed:
                self.logger.info("WebSocket connection closed")
                break
            except Exception:
                self.logger.exception("Error in receive loop")
                break

    async def start(self):
        self.running = True
        if await self.connect():
            self.logger.info("WebSocket client started.")
            await self.receive_messages()
        else:
            self.logger.error("Failed to connect to WebSocket server")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
        if self.ws:
            await self.ws.close()
            self.logger.info("WebSocket client stopped.")
