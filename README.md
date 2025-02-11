<div align="center">
  <img src="https://raw.githubusercontent.com/iwanalabs/economic-agents/main/assets/logo_200w.png">
</div>

<div align="center">

![Python compat](https://img.shields.io/badge/%3E=python-3.10-blue.svg)
[![PyPi](https://img.shields.io/pypi/v/economic-agents.svg)](https://pypi.python.org/pypi/economic-agents)
[![GHA Status](https://github.com/iwanalabs/economic-agents/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/iwanalabs/economic-agents/actions?query=workflow%3Atests)
[![Coverage](https://codecov.io/github/iwanalabs/economic-agents/coverage.svg?branch=main)](https://codecov.io/github/iwanalabs/economic-agents?branch=main)
[![Documentation Status](https://readthedocs.org/projects/economic-agents/badge/?version=latest)](https://economic-agents.readthedocs.io/en/latest/?badge=latest)

</div>

---

econagents is a Python library for creating and running economic experiments.

# Installation

We're still in the early stages of development, so the library is not yet available on PyPI, and it doesn't really work as a library yet.

For now, there's a single experiment available in the `experimental` directory. This is a Proof of Concept for a Harberger Tax game.

Follow these steps to get started:

1. Create a virtual environment and install the dependencies using poetry:

```shell
poetry install
```

2. Copy the `.env.example` file to `.env` and fill in the values.

## Creating a new game

You can create new game programmatically by running the `create_game.py` script:

```shell
cd experimental/harberger
python create_game.py
```

This will create a new game and save the game specifications to the `specs` directory. It will use the parameters from the `harberger.json` file in the `experimental/harberger/specs/example` directory. If you'd like to use different parameters, you can create a new JSON file in the `specs` directory and change the `specs_path` argument in the `create_game.py` script.

## Running the game

You can run the game in two ways:

1. Create and run a new game:

```bash
cd experimental/harberger
python run_game.py
```

This will create a new game using the default parameters from `specs/example/harberger.json` and start running it immediately.

2. Run an existing game:

```shell
cd experimental/harberger
python run_game.py --game-id YOUR_GAME_ID
```

Replace `YOUR_GAME_ID` with the ID of the game you want to run.

The game will create the following directory structure for logs:

```shell
experimental/harberger/logs/
├── agents/     # Individual agent logs
└── game/       # Game-wide logs
```

These logs can be useful for debugging and analyzing the game's progress.
