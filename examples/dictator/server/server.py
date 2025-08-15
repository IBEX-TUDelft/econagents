import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import websockets
from websockets.asyncio.server import serve, ServerConnection
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

WAITING = "waiting"
DECISION_PHASE = "decision"
PAYOUT_PHASE = "payout"
FINISHED = "finished"

SPECS_PATH = Path(__file__).parent / "games"


class DictatorGame:
    """Represents a single Dictator game."""

    def __init__(
        self, game_id: int, money_available: float = 10.0, exchange_rate: float = 3.0
    ):
        self.game_id = game_id
        self.players: dict[str, Optional[ServerConnection]] = {}
        self.player_names: dict[str, str] = {}
        self.player_recovery_codes: dict[str, str] = {}
        self.state = WAITING
        self.current_phase = 0
        self.money_available = money_available
        self.exchange_rate = exchange_rate
        self.money_sent = 0.0
        self.dictator_decision_made = False
        self.players_done: dict[str, bool] = {}

    def add_player(self, role: str, websocket: ServerConnection, name: str):
        """Add a player to the game."""
        self.players[role] = websocket
        self.player_names[role] = name
        self.players_done[role] = False
        logger.info(f"Added {role} ({name}) to game {self.game_id}")

    def is_ready(self) -> bool:
        """Check if the game is ready to start (has both dictator and receiver)."""
        return "dictator" in self.players and "receiver" in self.players

    def record_decision(self, money_send: float) -> None:
        """Record the dictator's decision."""
        if money_send < 0:
            raise ValueError(f"Cannot send negative amount: {money_send}")
        if money_send > self.money_available:
            raise ValueError(
                f"Cannot send more than available: {money_send} > {self.money_available}"
            )

        self.money_sent = money_send
        self.dictator_decision_made = True
        logger.info(f"Dictator decided to send {money_send} in game {self.game_id}")

    def calculate_payouts(self) -> Dict[str, float]:
        """Calculate the payouts for both players."""
        dictator_payout = self.money_available - self.money_sent
        receiver_payout = self.money_sent * self.exchange_rate

        return {"dictator": dictator_payout, "receiver": receiver_payout}

    def mark_player_done(self, role: str) -> None:
        """Mark a player as done with the current phase."""
        self.players_done[role] = True
        logger.info(f"Player {role} marked as done in game {self.game_id}")

    def all_players_done(self) -> bool:
        """Check if all players are done with the current phase."""
        return all(self.players_done.values())

    @property
    def num_players(self) -> int:
        """Get the number of players in the game."""
        return len(self.players.keys())


class DictatorServer:
    """WebSocket server for the Dictator game experiment."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.games: Dict[int, DictatorGame] = {}

    async def handle_websocket(self, websocket: ServerConnection) -> None:
        """Handle WebSocket connections."""
        game = None
        player_role = None

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    logger.debug(f"Message: {data}")
                    msg_type = data.get("type", "")

                    if msg_type == "join":
                        game_id = data.get("gameId")
                        recovery = data.get("recovery")

                        if not game_id and not recovery:
                            await self.send_error(
                                websocket, "Game ID and recovery code are required"
                            )
                            continue

                        game_specs_path = SPECS_PATH / f"game_{game_id}.json"

                        if not game_specs_path.exists():
                            await self.send_error(
                                websocket, f"Game {game_id} does not exist"
                            )
                            continue

                        with game_specs_path.open("r") as f:
                            game_specs = json.load(f)

                        if recovery not in game_specs["recovery_codes"]:
                            await self.send_error(
                                websocket, f"Invalid recovery code: {recovery}"
                            )
                            continue

                        if game_id in self.games:
                            game = self.games[game_id]
                        else:
                            game = DictatorGame(
                                game_id,
                                game_specs.get("money_available", 10.0),
                                game_specs.get("exchange_rate", 3.0),
                            )
                            self.games[game_id] = game

                        if game.num_players >= 2:
                            await self.send_error(websocket, f"Game {game_id} is full")
                            continue

                        recovery_index = game_specs["recovery_codes"].index(recovery)
                        player_role = "dictator" if recovery_index == 0 else "receiver"

                        if player_role in game.players:
                            await self.send_error(
                                websocket, f"Role {player_role} already taken"
                            )
                            continue

                        player_name = player_role.capitalize()
                        game.add_player(player_role, websocket, player_name)
                        await self.send_assign_role_message(
                            websocket, player_name, player_role
                        )

                        if game.is_ready():
                            await self.start_game(game)

                    elif msg_type == "decision":
                        if not game or not player_role:
                            await self.send_error(websocket, "Game not found")
                            continue

                        if game.state != DECISION_PHASE:
                            await self.send_error(
                                websocket, "Game not in decision phase"
                            )
                            continue

                        if player_role != "dictator":
                            await self.send_error(
                                websocket, "Only dictator can make decisions"
                            )
                            continue

                        try:
                            money_send = data.get("money_send")
                            if money_send is None:
                                await self.send_error(
                                    websocket, "money_send is required"
                                )
                                continue

                            game.record_decision(float(money_send))
                            await self.process_decision_completion(game)
                        except ValueError as e:
                            await self.send_error(websocket, str(e))
                            continue

                    elif msg_type == "action":
                        if not game or not player_role:
                            await self.send_error(websocket, "Game not found")
                            continue

                        action = data.get("action")
                        if action == "done":
                            game.mark_player_done(player_role)

                            # Check if all players are done with phase 2
                            if game.state == PAYOUT_PHASE and game.all_players_done():
                                await self.end_game(game)
                        else:
                            await self.send_error(
                                websocket, f"Unknown action: {action}"
                            )

                    else:
                        await self.send_error(
                            websocket, f"Unknown message type: {msg_type}"
                        )

                except json.JSONDecodeError:
                    await self.send_error(websocket, "Invalid JSON message")
                except Exception as e:
                    logger.exception(f"Error handling message: {e}")
                    await self.send_error(websocket, f"Error: {str(e)}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed for {player_role}")
        finally:
            if game and player_role is not None:
                if player_role in game.players:
                    game.players[player_role] = None
                logger.info(f"{player_role} disconnected from game {game.game_id}")

    async def start_game(self, game: DictatorGame) -> None:
        """Start a new game."""
        game.state = DECISION_PHASE
        game.current_phase = 1

        for role, websocket in game.players.items():
            if websocket:
                await self.send_game_started(websocket, game, role)

        logger.info(
            f"Game {game.game_id} started with players {list(game.players.keys())}"
        )

    async def process_decision_completion(self, game: DictatorGame) -> None:
        """Process the completion of the dictator's decision."""
        game.state = PAYOUT_PHASE
        game.current_phase = 2

        # Reset players_done for phase 2
        for role in game.players_done:
            game.players_done[role] = False

        payouts = game.calculate_payouts()

        # Send phase-started event for phase 2
        for role, websocket in game.players.items():
            if websocket:
                await self.send_phase_started(websocket, game, role)

        # Send decision results
        for role, websocket in game.players.items():
            if websocket:
                await self.send_decision_result(websocket, game, role, payouts)

    async def send_message(
        self, websocket: ServerConnection, message: Dict[str, Any]
    ) -> None:
        """Send a message to a client."""
        await websocket.send(json.dumps(message))

    async def send_error(self, websocket: ServerConnection, error_message: str) -> None:
        """Send an error message to a client."""
        await self.send_message(
            websocket,
            {
                "type": "error",
                "message": error_message,
            },
        )

    async def send_assign_role_message(
        self, websocket: ServerConnection, player_name: str, role: str
    ) -> None:
        """Send an assign-role message to a player when they first connect."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "assign-role",
                "data": {
                    "player_name": player_name,
                    "role": role,
                },
            },
        )

    async def send_game_started(
        self, websocket: ServerConnection, game: DictatorGame, role: str
    ) -> None:
        """Send a game-started message to a player."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "game-started",
                "data": {
                    "game_id": game.game_id,
                    "role": role,
                    "money_available": game.money_available,
                    "exchange_rate": game.exchange_rate,
                },
            },
        )

        await self.send_phase_started(websocket, game, role)

    async def send_phase_started(
        self, websocket: ServerConnection, game: DictatorGame, role: str
    ) -> None:
        """Send a phase-started message to a player."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "phase-started",
                "data": {
                    "gameId": game.game_id,
                    "phase": game.current_phase,
                    "phase_name": "decision" if game.current_phase == 1 else "payout",
                    "role": role,
                },
            },
        )

    async def send_decision_result(
        self,
        websocket: ServerConnection,
        game: DictatorGame,
        role: str,
        payouts: Dict[str, float],
    ) -> None:
        """Send a decision-result message to a player."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "decision-result",
                "data": {
                    "gameId": game.game_id,
                    "money_sent": game.money_sent,
                    "money_available": game.money_available,
                    "exchange_rate": game.exchange_rate,
                    "payouts": payouts,
                    "payout": payouts[role],
                },
            },
        )

    async def send_game_ended(
        self,
        websocket: ServerConnection,
        game: DictatorGame,
        role: str,
        payouts: Dict[str, float],
    ) -> None:
        """Send a game-ended message to a player."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "game-over",
                "data": {
                    "gameId": game.game_id,
                    "role": role,
                    "money_sent": game.money_sent,
                    "money_available": game.money_available,
                    "exchange_rate": game.exchange_rate,
                    "payouts": payouts[role],
                },
            },
        )

    async def end_game(self, game: DictatorGame) -> None:
        """End the game after all players are done with phase 2."""
        game.state = FINISHED
        payouts = game.calculate_payouts()

        # Send game ended to all players
        for role, websocket in game.players.items():
            if websocket:
                await self.send_game_ended(websocket, game, role, payouts)

        logger.info(f"Game {game.game_id} ended with payouts: {payouts}")

    async def start_server(self) -> None:
        """Start the WebSocket server."""
        async with serve(self.handle_websocket, self.host, self.port):
            logger.info(
                f"Dictator game WebSocket server started on {self.host}:{self.port}"
            )
            await asyncio.Future()

    @classmethod
    async def run(cls, host: str = "localhost", port: int = 8765) -> None:
        """Run the WebSocket server."""
        server = cls(host, port)
        await server.start_server()


if __name__ == "__main__":
    host = "localhost"
    port = 8765

    logger.info(f"Starting Dictator game WebSocket server on {host}:{port}")

    asyncio.run(DictatorServer.run(host, port))
