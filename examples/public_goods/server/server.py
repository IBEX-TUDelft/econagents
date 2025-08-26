import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

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
CONTRIBUTION_PHASE = "contribution"
PAYOUT_PHASE = "payout"
FINISHED = "finished"

SPECS_PATH = Path(__file__).parent / "games"


class PublicGoodsGame:
    """Represents a single Public Goods game."""

    def __init__(
        self, 
        game_id: int, 
        num_players: int = 4,
        initial_endowment: float = 20.0, 
        public_good_efficiency: float = 0.5
    ):
        self.game_id = game_id
        self.num_players = num_players
        self.players: dict[str, Optional[ServerConnection]] = {}
        self.player_names: dict[str, str] = {}
        self.player_recovery_codes: dict[str, str] = {}
        self.state = WAITING
        self.current_phase = 0
        self.initial_endowment = initial_endowment
        self.public_good_efficiency = public_good_efficiency
        self.contributions: dict[str, float] = {}
        self.contributions_made: dict[str, bool] = {}
        self.players_done: dict[str, bool] = {}

    def add_player(self, player_id: str, websocket: ServerConnection, name: str):
        """Add a player to the game."""
        self.players[player_id] = websocket
        self.player_names[player_id] = name
        self.players_done[player_id] = False
        self.contributions_made[player_id] = False
        logger.info(f"Added {player_id} ({name}) to game {self.game_id}")

    def is_ready(self) -> bool:
        """Check if the game is ready to start (has all players)."""
        return len(self.players) == self.num_players

    def record_contribution(self, player_id: str, contribution: float) -> None:
        """Record a player's contribution."""
        if contribution < 0:
            raise ValueError(f"Cannot contribute negative amount: {contribution}")
        if contribution > self.initial_endowment:
            raise ValueError(
                f"Cannot contribute more than endowment: {contribution} > {self.initial_endowment}"
            )

        self.contributions[player_id] = contribution
        self.contributions_made[player_id] = True
        logger.info(f"Player {player_id} contributed {contribution} in game {self.game_id}")

    def calculate_payoffs(self) -> Dict[str, float]:
        """Calculate the payoffs for all players."""
        total_contribution = sum(self.contributions.values())
        payoffs = {}
        
        for player_id in self.players:
            player_contribution = self.contributions.get(player_id, 0.0)
            kept = self.initial_endowment - player_contribution
            share_of_public_good = self.public_good_efficiency * total_contribution
            payoffs[player_id] = kept + share_of_public_good
        
        return payoffs

    def mark_player_done(self, player_id: str) -> None:
        """Mark a player as done with the current phase."""
        self.players_done[player_id] = True
        logger.info(f"Player {player_id} marked as done in game {self.game_id}")

    def all_players_done(self) -> bool:
        """Check if all players are done with the current phase."""
        return all(self.players_done.values())
    
    def all_contributions_made(self) -> bool:
        """Check if all players have made their contributions."""
        return all(self.contributions_made.values())


class PublicGoodsServer:
    """WebSocket server for the Public Goods game experiment."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.games: Dict[int, PublicGoodsGame] = {}

    async def handle_websocket(self, websocket: ServerConnection) -> None:
        """Handle WebSocket connections."""
        game = None
        player_id = None

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
                            game = PublicGoodsGame(
                                game_id,
                                game_specs.get("num_players", 4),
                                game_specs.get("initial_endowment", 20.0),
                                game_specs.get("public_good_efficiency", 0.5),
                            )
                            self.games[game_id] = game

                        if len(game.players) >= game.num_players:
                            await self.send_error(websocket, f"Game {game_id} is full")
                            continue

                        recovery_index = game_specs["recovery_codes"].index(recovery)
                        player_id = f"player_{recovery_index + 1}"

                        if player_id in game.players:
                            await self.send_error(
                                websocket, f"Player {player_id} already joined"
                            )
                            continue

                        player_name = f"Player {recovery_index + 1}"
                        game.add_player(player_id, websocket, player_name)
                        await self.send_assign_role_message(
                            websocket, player_name, player_id
                        )

                        if game.is_ready():
                            await self.start_game(game)

                    elif msg_type == "contribution":
                        if not game or not player_id:
                            await self.send_error(websocket, "Game not found")
                            continue

                        if game.state != CONTRIBUTION_PHASE:
                            await self.send_error(
                                websocket, "Game not in contribution phase"
                            )
                            continue

                        try:
                            contribution = data.get("contribution")
                            if contribution is None:
                                await self.send_error(
                                    websocket, "contribution is required"
                                )
                                continue

                            game.record_contribution(player_id, float(contribution))
                            
                            if game.all_contributions_made():
                                await self.process_contribution_completion(game)
                        except ValueError as e:
                            await self.send_error(websocket, str(e))
                            continue

                    elif msg_type == "action":
                        if not game or not player_id:
                            await self.send_error(websocket, "Game not found")
                            continue

                        action = data.get("action")
                        if action == "done":
                            game.mark_player_done(player_id)

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
            logger.info(f"Connection closed for {player_id}")
        finally:
            if game and player_id is not None:
                if player_id in game.players:
                    game.players[player_id] = None
                logger.info(f"{player_id} disconnected from game {game.game_id}")

    async def start_game(self, game: PublicGoodsGame) -> None:
        """Start a new game."""
        game.state = CONTRIBUTION_PHASE
        game.current_phase = 1

        for player_id, websocket in game.players.items():
            if websocket:
                await self.send_game_started(websocket, game, player_id)

        logger.info(
            f"Game {game.game_id} started with players {list(game.players.keys())}"
        )

    async def process_contribution_completion(self, game: PublicGoodsGame) -> None:
        """Process the completion of all contributions."""
        game.state = PAYOUT_PHASE
        game.current_phase = 2

        # Reset players_done for phase 2
        for player_id in game.players_done:
            game.players_done[player_id] = False

        payoffs = game.calculate_payoffs()
        total_contribution = sum(game.contributions.values())

        # Send contribution results first to update state
        for player_id, websocket in game.players.items():
            if websocket:
                await self.send_contribution_result(
                    websocket, game, player_id, payoffs, total_contribution
                )

        # Then send phase-started event for phase 2
        for player_id, websocket in game.players.items():
            if websocket:
                await self.send_phase_started(websocket, game, player_id)

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
        self, websocket: ServerConnection, player_name: str, player_id: str
    ) -> None:
        """Send an assign-role message to a player when they first connect."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "assign-role",
                "data": {
                    "player_name": player_name,
                    "player_id": player_id,
                },
            },
        )

    async def send_game_started(
        self, websocket: ServerConnection, game: PublicGoodsGame, player_id: str
    ) -> None:
        """Send a game-started message to a player."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "game-started",
                "data": {
                    "game_id": game.game_id,
                    "player_id": player_id,
                    "num_players": game.num_players,
                    "initial_endowment": game.initial_endowment,
                    "public_good_efficiency": game.public_good_efficiency,
                },
            },
        )

        await self.send_phase_started(websocket, game, player_id)

    async def send_phase_started(
        self, websocket: ServerConnection, game: PublicGoodsGame, player_id: str
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
                    "phase_name": "contribution" if game.current_phase == 1 else "payout",
                    "player_id": player_id,
                    "initial_endowment": game.initial_endowment,
                    "public_good_efficiency": game.public_good_efficiency,
                    "num_players": game.num_players,
                },
            },
        )

    async def send_contribution_result(
        self,
        websocket: ServerConnection,
        game: PublicGoodsGame,
        player_id: str,
        payoffs: Dict[str, float],
        total_contribution: float,
    ) -> None:
        """Send a contribution-result message to a player."""
        # Ensure all players are in contributions dict (with 0 for those who didn't contribute)
        all_contributions = {pid: game.contributions.get(pid, 0.0) for pid in game.players}
        
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "contribution-result",
                "data": {
                    "gameId": game.game_id,
                    "player_id": player_id,
                    "contributions": all_contributions,
                    "total_contribution": total_contribution,
                    "initial_endowment": game.initial_endowment,
                    "public_good_efficiency": game.public_good_efficiency,
                    "payoffs": payoffs,
                    "your_payoff": payoffs[player_id],
                },
            },
        )

    async def send_game_ended(
        self,
        websocket: ServerConnection,
        game: PublicGoodsGame,
        player_id: str,
        payoffs: Dict[str, float],
    ) -> None:
        """Send a game-ended message to a player."""
        # Ensure all players are in contributions dict (with 0 for those who didn't contribute)
        all_contributions = {pid: game.contributions.get(pid, 0.0) for pid in game.players}
        
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "game-over",
                "data": {
                    "gameId": game.game_id,
                    "player_id": player_id,
                    "contributions": all_contributions,
                    "total_contribution": sum(game.contributions.values()),
                    "initial_endowment": game.initial_endowment,
                    "public_good_efficiency": game.public_good_efficiency,
                    "final_payoff": payoffs[player_id],
                },
            },
        )

    async def end_game(self, game: PublicGoodsGame) -> None:
        """End the game after all players are done with phase 2."""
        game.state = FINISHED
        payoffs = game.calculate_payoffs()

        for player_id, websocket in game.players.items():
            if websocket:
                await self.send_game_ended(websocket, game, player_id, payoffs)

        logger.info(f"Game {game.game_id} ended with payoffs: {payoffs}")

    async def start_server(self) -> None:
        """Start the WebSocket server."""
        async with serve(self.handle_websocket, self.host, self.port):
            logger.info(
                f"Public Goods game WebSocket server started on {self.host}:{self.port}"
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

    logger.info(f"Starting Public Goods game WebSocket server on {host}:{port}")

    asyncio.run(PublicGoodsServer.run(host, port))
