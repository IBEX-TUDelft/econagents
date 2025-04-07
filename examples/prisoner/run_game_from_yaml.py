import asyncio
from pathlib import Path

from econagents.config_parser import BasicConfigParser
from examples.prisoner.server.create_game import create_game_from_specs


async def main():
    """Main function to run the game."""
    game_specs = create_game_from_specs()
    login_payloads = [
        {"agent_id": i, "type": "join", "gameId": game_specs["game_id"], "recovery": code}
        for i, code in enumerate(game_specs["recovery_codes"], start=1)
    ]

    parsed_config = BasicConfigParser(config_path=Path(__file__).parent / "config.yaml")
    await parsed_config.run_experiment(login_payloads)


if __name__ == "__main__":
    asyncio.run(main())
