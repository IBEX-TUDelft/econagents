import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def default_trader_specs() -> list[dict[str, Any]]:
    """Return a small induced-value schedule for a classic double auction."""
    return [
        {
            "name": "Buyer 1",
            "trader_type": "buyer",
            "limit_prices": [110.0, 100.0, 90.0, 80.0, 70.0],
            "cash_endowment": 450.0,
        },
        {
            "name": "Buyer 2",
            "trader_type": "buyer",
            "limit_prices": [105.0, 95.0, 85.0, 75.0, 65.0],
            "cash_endowment": 425.0,
        },
        {"name": "Seller 1", "trader_type": "seller", "limit_prices": [35.0, 45.0, 55.0, 65.0, 75.0]},
        {"name": "Seller 2", "trader_type": "seller", "limit_prices": [40.0, 50.0, 60.0, 70.0, 80.0]},
    ]


def generate_recovery_codes(num_players: int) -> list[str]:
    """Generate recovery codes for all traders."""
    return [str(uuid.uuid4()) for _ in range(num_players)]


def save_game_data(
    specs_path: Path,
    game_id: int,
    game_name: str,
    trader_specs: list[dict[str, Any]],
    market_duration: int,
    summary_duration: int,
) -> Path:
    """Save game data to the server specs directory."""
    specs_dir = specs_path.parent / "games"
    specs_dir.mkdir(parents=True, exist_ok=True)

    recovery_codes = generate_recovery_codes(len(trader_specs))
    traders = []
    for spec, recovery in zip(trader_specs, recovery_codes):
        traders.append({**spec, "recovery": recovery})

    game_data = {
        "game_id": game_id,
        "game_name": game_name,
        "num_players": len(traders),
        "recovery_codes": recovery_codes,
        "traders": traders,
        "market_duration": market_duration,
        "summary_duration": summary_duration,
        "created_at": datetime.now().isoformat(),
    }

    output_file = specs_dir / f"game_{game_id}.json"
    with output_file.open("w") as f:
        json.dump(game_data, f, indent=2)
    logger.info(f"Game data saved to {output_file}")
    return output_file


def create_game_from_specs(
    trader_specs: list[dict[str, Any]] | None = None,
    market_duration: int = 60,
    summary_duration: int = 2,
) -> dict[str, Any]:
    """Create a local continuous double auction game spec."""
    game_id = int(datetime.now().timestamp())
    game_name = f"Continuous Double Auction {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    trader_specs = trader_specs or default_trader_specs()

    save_game_data(
        specs_path=Path(__file__).parent / "games",
        game_id=game_id,
        game_name=game_name,
        trader_specs=trader_specs,
        market_duration=market_duration,
        summary_duration=summary_duration,
    )

    recovery_codes = []
    game_file = Path(__file__).parent / "games" / f"game_{game_id}.json"
    with game_file.open("r") as f:
        recovery_codes = json.load(f)["recovery_codes"]

    return {
        "game_id": game_id,
        "game_name": game_name,
        "num_players": len(trader_specs),
        "recovery_codes": recovery_codes,
        "market_duration": market_duration,
        "summary_duration": summary_duration,
        "created_at": datetime.now().isoformat(),
    }
