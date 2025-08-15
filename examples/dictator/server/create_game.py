import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def generate_recovery_codes(num_players: int = 2) -> list[str]:
    """Generate recovery codes for the specified number of players."""
    return [str(uuid.uuid4()) for _ in range(num_players)]


def save_game_data(
    specs_path: Path, 
    game_id: int, 
    game_name: str, 
    num_players: int, 
    recovery_codes: list[str],
    money_available: float = 10.0,
    exchange_rate: float = 3.0
) -> Path:
    """Save game data to a JSON file in the specs/games directory."""
    specs_dir = specs_path.parent / "games"
    specs_dir.mkdir(parents=True, exist_ok=True)

    game_data = {
        "game_id": game_id,
        "game_name": game_name,
        "num_players": num_players,
        "recovery_codes": recovery_codes,
        "money_available": money_available,
        "exchange_rate": exchange_rate,
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


def create_game_from_specs(money_available: float = 10.0, exchange_rate: float = 3.0) -> dict:
    """Create a new Dictator game from specs."""
    try:
        game_id = int(datetime.now().timestamp())
        game_name = f"Dictator Game {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        recovery_codes = generate_recovery_codes(num_players=2)

        save_game_data(
            specs_path=Path(__file__).parent / "games",
            game_id=game_id,
            game_name=game_name,
            num_players=2,
            recovery_codes=recovery_codes,
            money_available=money_available,
            exchange_rate=exchange_rate,
        )

        return {
            "game_id": game_id,
            "game_name": game_name,
            "num_players": 2,
            "recovery_codes": recovery_codes,
            "money_available": money_available,
            "exchange_rate": exchange_rate,
            "created_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise