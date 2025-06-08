import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import websockets
from websockets.asyncio.server import serve, ServerConnection
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Game states
WAITING = "waiting"
PLAYING = "playing"
FINISHED = "finished"

# Prisoner's Dilemma choices
COOPERATE = "cooperate"
DEFECT = "defect"

# Prisoner's Dilemma payoff matrix
# Format: [player1_choice][player2_choice] = (player1_payoff, player2_payoff)
PAYOFF_MATRIX = {
    COOPERATE: {
        COOPERATE: (3, 3),  # Both cooperate: both get 3
        DEFECT: (0, 5),  # P1 cooperates, P2 defects: P1 gets 0, P2 gets 5
    },
    DEFECT: {
        COOPERATE: (5, 0),  # P1 defects, P2 cooperates: P1 gets 5, P2 gets 0
        DEFECT: (1, 1),  # Both defect: both get 1
    },
}

SPECS_PATH = Path(__file__).parent / "games"


class PrisonersDilemmaGame:
    """Represents a single Prisoner's Dilemma game with multiple rounds."""

    def __init__(self, game_id: int, rounds: int = 10):
        self.game_id = game_id
        self.players: dict[int, Optional[ServerConnection]] = {}
        self.player_names: dict[int, str] = {}
        self.player_recovery_codes: dict[int, str] = {}
        self.state = WAITING
        self.current_round = 0
        self.total_rounds = rounds
        self.player_choices: dict[int, dict[int, str]] = {}
        self.round_results: list[dict[str, Any]] = []
        self.player_scores: dict[int, int] = {}

    def add_player(self, player_number: int, websocket: ServerConnection, name: str):
        """Add a player to the game."""
        self.players[player_number] = websocket
        self.player_names[player_number] = name
        self.player_choices[player_number] = {}
        self.player_scores[player_number] = 0
        logger.info(f"Added player {player_number} ({name}) to game {self.game_id}")

    def is_ready(self) -> bool:
        """Check if the game is ready to start (has 2 players)."""
        return len(self.players) == 2

    def record_choice(self, player_number: int, choice: str) -> None:
        """Record a player's choice for the current round."""
        if player_number not in self.players:
            raise ValueError(f"Player {player_number} not in game")

        if choice.lower() not in [COOPERATE, DEFECT]:
            raise ValueError(f"Invalid choice: {choice}")

        self.player_choices[player_number][self.current_round] = choice
        logger.info(f"Player {player_number} chose {choice} in round {self.current_round}")

    def all_players_made_choice(self) -> bool:
        """Check if all players have made their choice for the current round."""
        return all(self.current_round in choices for choices in self.player_choices.values())

    def calculate_round_results(self) -> Dict[str, Any]:
        """Calculate the results of the current round."""
        player_numbers = list(self.players.keys())
        if len(player_numbers) != 2:
            raise ValueError("Need exactly 2 players to calculate results")

        player1_id, player2_id = player_numbers
        player1_choice = self.player_choices[player1_id][self.current_round].lower()
        player2_choice = self.player_choices[player2_id][self.current_round].lower()

        player1_payoff, player2_payoff = PAYOFF_MATRIX[player1_choice][player2_choice]

        # Update scores
        self.player_scores[player1_id] += player1_payoff
        self.player_scores[player2_id] += player2_payoff

        # Create result object
        result = {
            "round": self.current_round,
            "choices": {
                player1_id: player1_choice,
                player2_id: player2_choice,
            },
            "payoffs": {
                player1_id: player1_payoff,
                player2_id: player2_payoff,
            },
            "total_scores": {
                player1_id: self.player_scores[player1_id],
                player2_id: self.player_scores[player2_id],
            },
        }

        self.round_results.append(result)
        return result

    def next_round(self) -> bool:
        """Move to the next round. Returns True if there are more rounds, False if the game is over."""
        self.current_round += 1
        if self.current_round >= self.total_rounds:
            self.state = FINISHED
            return False
        return True

    @property
    def num_players(self) -> int:
        """Get the number of players in the game."""
        return len(self.players.keys())


class PrisonersDilemmaServer:
    """WebSocket server for the Prisoner's Dilemma experiment."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.games: Dict[int, PrisonersDilemmaGame] = {}

    async def handle_websocket(self, websocket: ServerConnection) -> None:
        """Handle WebSocket connections."""
        game = None
        player_number = None

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
                            await self.send_error(websocket, "Game ID and recovery code are required")
                            continue

                        game_specs_path = SPECS_PATH / f"game_{game_id}.json"

                        if not game_specs_path.exists():
                            await self.send_error(websocket, f"Game {game_id} does not exist")
                            continue

                        with game_specs_path.open("r") as f:
                            game_specs = json.load(f)

                        if recovery not in game_specs["recovery_codes"]:
                            await self.send_error(websocket, f"Invalid recovery code: {recovery}")
                            continue

                        if game_id in self.games:
                            game = self.games[game_id]
                        else:
                            game = PrisonersDilemmaGame(game_id, 5)
                            self.games[game_id] = game

                        if game.num_players >= 2:
                            await self.send_error(websocket, f"Game {game_id} is full")
                            continue

                        player_number = game.num_players + 1
                        player_name = f"Player {player_number}"

                        game.add_player(player_number, websocket, player_name)
                        await self.send_assign_name_message(websocket, player_name, player_number)

                        if game.is_ready():
                            await self.start_game(game)

                    elif msg_type == "choice":
                        if not game or not player_number:
                            await self.send_error(websocket, "Game not found")
                            continue

                        if game.state != PLAYING:
                            await self.send_error(websocket, "Game not in playing state")
                            continue

                        try:
                            choice = data.get("choice")
                            game.record_choice(player_number, choice)
                        except ValueError as e:
                            await self.send_error(websocket, str(e))
                            continue

                        # If all players have made their choice, calculate results and move to next round
                        if game.all_players_made_choice():
                            await self.process_round_completion(game)

                    else:
                        await self.send_error(websocket, f"Unknown message type: {msg_type}")

                except json.JSONDecodeError:
                    await self.send_error(websocket, "Invalid JSON message")
                except Exception as e:
                    logger.exception(f"Error handling message: {e}")
                    await self.send_error(websocket, f"Error: {str(e)}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed for player {player_number}")
        finally:
            # Handle player disconnection
            if game and player_number is not None:
                # Keep player in game but mark as disconnected
                if player_number in game.players:
                    game.players[player_number] = None
                logger.info(f"Player {player_number} disconnected from game {game.game_id}")

    async def start_game(self, game: PrisonersDilemmaGame) -> None:
        """Start a new game."""
        game.state = PLAYING
        game.current_round = 0

        for player_number, websocket in game.players.items():
            if websocket:
                await self.send_game_started(websocket, game, player_number)

        logger.info(f"Game {game.game_id} started with players {list(game.players.keys())}")

    async def process_round_completion(self, game: PrisonersDilemmaGame) -> None:
        """Process the completion of a round."""
        # Calculate round results
        result = game.calculate_round_results()

        # Send round-result event to all players
        for player_number, websocket in game.players.items():
            if websocket:
                await self.send_round_result(websocket, game, player_number, result)

        # Move to next round or end game
        if game.next_round():
            # Start next round
            for player_number, websocket in game.players.items():
                if websocket:
                    await self.send_round_started(websocket, game, player_number)
        else:
            # End game
            for player_number, websocket in game.players.items():
                if websocket:
                    await self.send_game_ended(websocket, game, player_number)

    # Message sending helpers
    async def send_message(self, websocket: ServerConnection, message: Dict[str, Any]) -> None:
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

    async def send_assign_name_message(
        self, websocket: ServerConnection, player_name: str, player_number: Optional[int]
    ) -> None:
        """Send an assign-name message to a player when they first connect."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "assign-name",
                "data": {
                    "player_name": player_name,
                    "player_number": player_number,
                },
            },
        )

    async def send_game_started(
        self, websocket: ServerConnection, game: PrisonersDilemmaGame, player_number: int
    ) -> None:
        """Send a game-started message to a player."""
        other_id = next(pid for pid in game.players if pid != player_number)

        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "game-started",
                "data": {
                    "game_id": game.game_id,
                    "player_number": player_number,
                    "player_name": game.player_names[player_number],
                    "opponent_number": other_id,
                    "opponent_name": game.player_names[other_id],
                    "rounds": game.total_rounds,
                    "payoff_matrix": PAYOFF_MATRIX,
                },
            },
        )

        # Also send the first round-started event
        await self.send_round_started(websocket, game, player_number)

    async def send_round_started(
        self, websocket: ServerConnection, game: PrisonersDilemmaGame, player_number: int
    ) -> None:
        """Send a round-started message to a player."""
        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "round-started",
                "data": {
                    "gameId": game.game_id,
                    "round": game.current_round + 1,
                    "total_rounds": game.total_rounds,
                },
            },
        )

    async def send_round_result(
        self, websocket: ServerConnection, game: PrisonersDilemmaGame, player_number: int, result: Dict[str, Any]
    ) -> None:
        """Send a round-result message to a player."""
        other_id = next(pid for pid in game.players if pid != player_number)

        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "round-result",
                "data": {
                    "gameId": game.game_id,
                    "round": result["round"] + 1,  # 1-indexed for display
                    "choices": result["choices"],
                    "payoffs": result["payoffs"],
                    "total_score": result["total_scores"][player_number],
                    "history": [
                        {
                            "round": r["round"] + 1,  # 1-indexed for display
                            "my_choice": r["choices"][player_number],
                            "opponent_choice": r["choices"][other_id],
                            "my_payoff": r["payoffs"][player_number],
                            "opponent_payoff": r["payoffs"][other_id],
                        }
                        for r in game.round_results
                    ],
                },
            },
        )

    async def send_game_ended(
        self, websocket: ServerConnection, game: PrisonersDilemmaGame, player_number: int
    ) -> None:
        """Send a game-ended message to a player."""
        other_id = next(pid for pid in game.players if pid != player_number)

        my_score = game.player_scores[player_number]
        opponent_score = game.player_scores[other_id]

        result = "win" if my_score > opponent_score else "lose" if my_score < opponent_score else "tie"

        await self.send_message(
            websocket,
            {
                "type": "event",
                "eventType": "game-over",
                "data": {
                    "gameId": game.game_id,
                    "result": result,
                    "myFinalScore": my_score,
                    "opponentFinalScore": opponent_score,
                    "history": [
                        {
                            "round": r["round"] + 1,  # 1-indexed for display
                            "myChoice": r["choices"][player_number],
                            "opponentChoice": r["choices"][other_id],
                            "myPayoff": r["payoffs"][player_number],
                            "opponentPayoff": r["payoffs"][other_id],
                        }
                        for r in game.round_results
                    ],
                },
            },
        )

    async def start_server(self) -> None:
        """Start the WebSocket server."""
        async with serve(self.handle_websocket, self.host, self.port):
            logger.info(f"Prisoner's Dilemma WebSocket server started on {self.host}:{self.port}")
            # Keep the server running until interrupted
            await asyncio.Future()  # Run forever

    @classmethod
    async def run(cls, host: str = "localhost", port: int = 8765) -> None:
        """Run the WebSocket server."""
        server = cls(host, port)
        await server.start_server()


if __name__ == "__main__":
    host = "localhost"
    port = 8765

    logger.info(f"Starting Prisoner's Dilemma WebSocket server on {host}:{port}")

    asyncio.run(PrisonersDilemmaServer.run(host, port))
