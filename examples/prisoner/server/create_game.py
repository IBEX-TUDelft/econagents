import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def generate_recovery_codes(num_players: int = 2) -> list[str]:
    """Generate recovery codes for the specified number of players."""
    return [str(uuid.uuid4()) for _ in range(num_players)]


def save_game_data(specs_path: Path, game_id: int, game_name: str, num_players: int, recovery_codes: list[str]) -> Path:
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


def create_game_from_specs() -> dict:
    """Create a new Prisoner's Dilemma game from specs."""
    try:
        # Generate a game ID (timestamp-based for simplicity)
        game_id = int(datetime.now().timestamp())

        # Use provided game name or generate one
        game_name = f"Prisoner's Dilemma {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Generate recovery codes for 2 players
        recovery_codes = generate_recovery_codes(num_players=2)

        # Save game specs (on server)
        save_game_data(
            specs_path=Path(__file__).parent / "games",
            game_id=game_id,
            game_name=game_name,
            num_players=2,
            recovery_codes=recovery_codes,
        )

        return {
            "game_id": game_id,
            "game_name": game_name,
            "num_players": 2,
            "recovery_codes": recovery_codes,
            "created_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise
