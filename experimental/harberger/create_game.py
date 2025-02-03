import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

HOSTNAME = os.getenv("HOSTNAME")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_game_specs(specs_path: str) -> dict[str, Any]:
    """Load game specifications from JSON file."""
    try:
        with Path(specs_path).open("r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load game specs: {e}")
        raise


def create_game(base_url: str, username: str, password: str, game_params: dict[str, Any]) -> dict[str, Any]:
    """Create a new game using the API."""
    endpoint = f"{base_url}/api/v1/games/create-for-llm"

    payload = {"username": username, "password": password, "gameParameters": game_params}

    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to create game: {e}")
        raise


def main():
    base_url = f"http://{HOSTNAME}"
    specs_path = Path(__file__).parent / "game_specs.json"

    username = os.getenv("GAME_USERNAME")
    password = os.getenv("GAME_PASSWORD")

    if not username or not password:
        logger.error("Missing credentials. Please set GAME_USERNAME and GAME_PASSWORD environment variables.")
        return

    try:
        # Load game specifications
        game_params = load_game_specs(specs_path)
        game_params["title"] = f"Harberger Game {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        logger.info("Creating new game...")
        result = create_game(base_url, username, password, game_params)

        if result.get("status"):
            game_id = result["data"]["id"]
            logger.info(f"Game created successfully! Game ID: {game_id}")
        else:
            logger.error(f"Failed to create game: {result.get('message', 'Unknown error')}")

    except Exception as e:
        logger.error(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
