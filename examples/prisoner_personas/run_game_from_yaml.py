"""Entry point for the persona-driven prisoner experiment.

Reuses the local game server from ``examples/prisoner/`` and dispatches via
``run_experiment_from_yaml``. The behavioral and demographic differences between
the two players come entirely from their persona references in
``prisoner.yaml`` — there is no per-role logic in this example.

Server first (in another terminal):

    uv run python examples/prisoner/server/server.py

Then this:

    uv run python examples/prisoner_personas/run_game_from_yaml.py
"""

import asyncio
from pathlib import Path

from econagents.adapters.config import run_experiment_from_yaml
from examples.prisoner.server.create_game import create_game_from_specs


async def main() -> None:
    game_specs = create_game_from_specs()
    login_payloads = [
        {"agent_id": i, "type": "join", "gameId": game_specs["game_id"], "recovery": code}
        for i, code in enumerate(game_specs["recovery_codes"], start=1)
    ]

    await run_experiment_from_yaml(
        Path(__file__).parent / "prisoner.yaml",
        login_payloads,
        game_id=game_specs["game_id"],
    )


if __name__ == "__main__":
    asyncio.run(main())
