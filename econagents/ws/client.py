import asyncio
import json
import logging
import random

import websockets


class WebSocketClient:
    def __init__(self, url, game_id, recovery=None, logger=None):
        self.logger = logger
        self.url = url
        self.game_id = game_id
        self.recovery = recovery
        self.ws = None
        self.task = None
        self.running = False

        self.name = None
        self.role = None
        self.known_players = []
        self.current_phase = None
        self.role_map = {1: "Speculator", 2: "Developer", 3: "Owner"}

    async def on_message(self, message):
        self.logger.debug(f"← Received: {message}")

        # Attempt to parse the server message as JSON
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON received.")
            return

        msg_type = msg.get("type", "")
        event_type = msg.get("eventType", "")
        data = msg.get("data", {})

        if msg_type == "event" and event_type == "assign-name":
            self.name = data.get("name")
            self.logger.info(f"Name assigned: {self.name}")
            await self.send_player_ready()

        elif msg_type == "event" and event_type == "assign-role":
            self.role = data.get("role", None)
            self.logger.info(f"Role assigned: {self.role}")

        elif msg_type == "event" and event_type == "players-known":
            self.known_players = data.get("players", [])
            self.logger.info(f"Known players: {self.known_players}")

        elif msg_type == "event" and event_type == "phase-transition":
            self.current_phase = data.get("phase")
            round_number = data.get("round", 1)
            self.logger.info(f"Transitioning to phase {self.current_phase}, round {round_number}")
            await self.handle_phase(self.current_phase)

    async def handle_phase(self, phase):
        """
        Execute a simple auto-action per phase
        0 - Name assignment: All players must send "player-is-ready".
        2 - Declaration: Owners (role=3) or Developers (role=2) declare random property values.
        3 - Speculation: Speculators (role=1) might snipe random owners.
        6 - Market: (Optional) we let Speculators place a random "ask" order.
        7 - Declaration again.
        8 - Speculation again.
        Phases 1, 4, 5, 9 do nothing in this minimal example.
        """
        # Phase 2 => if role=Owner(3) or Developer(2), declare random values
        if phase == 2 and self.role in [2, 3]:
            dec1 = random.randint(250000, 600000)
            dec2 = random.randint(150000, 400000)
            declare_msg = {"gameId": self.game_id, "type": "declare", "declaration": [dec1, dec2, 0]}
            await self.send_message(json.dumps(declare_msg))
            self.logger.info(f"Declared values: {declare_msg['declaration']}")

        # Phase 3 => if role=Speculator(1), try a random speculation
        elif phase == 3 and self.role == 1:
            # We'll randomly pick from owners/developers in known_players
            potential_targets = [p["number"] for p in self.known_players if p["role"] in [2, 3]]
            # randomly snipe half of them
            chosen = []
            for t in potential_targets:
                if random.random() < 0.5:
                    chosen.append(t)
            snipe_msg = {
                "gameId": self.game_id,
                "type": "done-speculating",
                "snipe": [
                    chosen,  # condition 0
                    [],
                ],
            }
            await self.send_message(json.dumps(snipe_msg))
            self.logger.info(f"Speculating against targets: {chosen}")

        # Phase 6 => Market: if role=Speculator(1), place a random ask order
        elif phase == 6 and self.role == 1:
            post_msg = {
                "gameId": self.game_id,
                "type": "post-order",
                "order": {
                    "price": random.randint(3000, 10000),
                    "quantity": 1,
                    "condition": 0,
                    "type": "ask",
                    "now": False,
                },
            }
            await self.send_message(json.dumps(post_msg))
            self.logger.info(f"Posted market order: {post_msg['order']}")

        # Phase 7 => declare again if role=Owner(3) or Developer(2)
        elif phase == 7 and self.role in [2, 3]:
            dec1 = random.randint(250000, 600000)
            dec2 = random.randint(150000, 400000)
            declare_msg = {"gameId": self.game_id, "type": "declare", "declaration": [dec1, dec2, 0]}
            await self.send_message(json.dumps(declare_msg))
            self.logger.info(f"Declared (second time): {declare_msg['declaration']}")

        # Phase 8 => speculation again if role=Speculator(1)
        elif phase == 8 and self.role == 1:
            potential_targets = [p["number"] for p in self.known_players if p["role"] in [2, 3]]
            chosen = []
            for t in potential_targets:
                if random.random() < 0.5:
                    chosen.append(t)
            snipe_msg = {
                "gameId": self.game_id,
                "type": "done-speculating",
                "snipe": [
                    chosen,  # condition 0
                    [],
                ],
            }
            await self.send_message(json.dumps(snipe_msg))
            self.logger.info(f"Final speculation against: {chosen}")

        # Phases 1,4,5,9 => do nothing in this demo

    async def send_player_ready(self):
        """
        Send the 'player-is-ready' message so that the game can advance from the introduction.
        """
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))
        self.logger.info("Sent player-is-ready message.")

    async def connect(self):
        try:
            self.ws = await websockets.connect(self.url, ping_interval=30, ping_timeout=10)
            self.logger.info("WebSocket connection opened.")
            initial_message = json.dumps({"gameId": self.game_id, "type": "join", "recovery": self.recovery})
            self.logger.debug(f"Sending initial message: {initial_message}")
            await self.send_message(initial_message)
        except Exception:
            self.logger.exception("Connection error", exc_info=True)
            return False
        else:
            return True

    async def send_message(self, message):
        try:
            self.logger.debug(f"→ Sending: {message}")
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
