import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_game_specs(specs_path: Path) -> Dict[str, Any]:
    """Load game specifications from JSON file."""
    try:
        with specs_path.open("r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load game specs: {e}")
        raise


def generate_recovery_codes(num_players: int = 2) -> List[str]:
    """Generate recovery codes for the specified number of players."""
    return [str(uuid.uuid4()) for _ in range(num_players)]


def save_game_data(specs_path: Path, game_id: int, game_name: str, num_players: int, recovery_codes: List[str]) -> Path:
    """Save game data to a JSON file in the specs/games directory."""
    specs_dir = specs_path.parent / "games"
    specs_dir.mkdir(parents=True, exist_ok=True)

    game_data = {
        "game_id": game_id,
        "game_name": game_name,
        "num_players": num_players,
        "recovery_codes": recovery_codes,
        "created_at": datetime.now().isoformat(),
    }

    output_file = specs_dir / f"game_{game_id}.json"
    try:
        with output_file.open("w") as f:
            json.dump(game_data, f, indent=2)
        logger.info(f"Game data saved to {output_file}")
    except Exception as e:
        logger.error(f"Failed to save game data: {e}")
        raise

    return output_file


def create_game_from_specs(specs_path: Path, game_name: Optional[str] = None, base_url: Optional[str] = None) -> int:
    """Create a new Prisoner's Dilemma game from specs."""
    try:
        # Generate a game ID (timestamp-based for simplicity)
        game_id = int(datetime.now().timestamp())

        # Use provided game name or generate one
        if not game_name:
            game_name = f"Prisoner's Dilemma {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Generate recovery codes for 2 players
        recovery_codes = generate_recovery_codes(num_players=2)

        # Save game data
        output_file_client = save_game_data(
            specs_path=specs_path,
            game_id=game_id,
            game_name=game_name,
            num_players=2,
            recovery_codes=recovery_codes,
        )
        output_file_server = save_game_data(
            specs_path=Path(__file__).parent / "specs" / "games",
            game_id=game_id,
            game_name=game_name,
            num_players=2,
            recovery_codes=recovery_codes,
        )

        logger.info(f"Created new game '{game_name}' with ID {game_id}")
        logger.info(f"Recovery codes: {recovery_codes}")
        logger.info(f"Game data saved to {output_file_client}")
        logger.info(f"Game data saved to {output_file_server}")

        return game_id
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    SPECS_PATH = Path(__file__).parent / "specs/prisoner.json"

    if not SPECS_PATH.exists():
        logger.error(f"Game specs file not found at {SPECS_PATH}")
        exit(1)

    game_id = create_game_from_specs(specs_path=SPECS_PATH)

    # Print instructions for running the server and connecting clients
    logger.info("\nTo start the WebSocket server:")
    logger.info("python -m examples.server.prisoner.server")
    logger.info("\nTo connect clients, use the following recovery codes in your client:")

    # Read the game data file to get the recovery codes
    game_data_path = SPECS_PATH.parent / "games" / f"game_{game_id}.json"
    with game_data_path.open() as f:
        game_data = json.load(f)

    for i, code in enumerate(game_data["recovery_codes"]):
        logger.info(f"Player {i + 1}: {code}")
