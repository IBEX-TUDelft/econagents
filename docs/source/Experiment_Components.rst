Experiment Components
=====================

This guide provides a of the components of an experiment using the econagents framework.

.. contents:: Table of Contents
   :depth: 3
   :local:

Project Structure Overview
--------------------------

To run an experiment, you can start from the following structure:

.. code-block:: text

    experiment_name/
    ├── __init__.py                # Package initialization
    ├── agents.py                  # Agent class definitions
    ├── manager.py                 # Agent manager for handling game events
    ├── state.py                   # Game state definition
    ├── run_game.ipynb             # Script for running experiments
    ├── specs/                     # Game specifications
    │   └── experiment.json        # Game parameters
    └── prompts/                   # LLM prompts for agents

Prerequisites
-------------

Before running an experiment, ensure you have:

1. Python 3.10+ installed
2. Required environment variables set (API keys, server configuration)
3. All dependencies installed

Create a ``.env`` file in your project root with the following variables:

.. code-block:: text

    LANGCHAIN_API_KEY=<your_langsmith_api_key>
    LANGSMITH_TRACING=true
    LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
    LANGSMITH_PROJECT="econagents"

    OPENAI_API_KEY=<your_openai_api_key>
    GAME_USERNAME=<your_game_username>
    GAME_PASSWORD=<your_game_password>

    HOSTNAME=<your_game_server_hostname>
    PORT=<your_game_server_port>


Understanding the Key Components
--------------------------------

These are the key components of an experiment:

Agent Classes (agents.py)
~~~~~~~~~~~~~~~~~~~~~~~~~

Agent classes define the different roles in your experiment:

.. code-block:: python

    from econagents.core.agent import Agent

    class Speculator(Agent):
        role = 1
        name = "Speculator"
        task_phases = [3, 6, 8]  # Phases where this agent must perform a task

    class Developer(Agent):
        role = 2
        name = "Developer"
        task_phases = [2, 6, 7]

    class Owner(Agent):
        role = 3
        name = "Owner"
        task_phases = [2, 6, 7]

Agent Manager (manager.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~

The manager handles game events and initializes appropriate agents. You can add custom logic such as assigning roles of agents after the game has started.

.. code-block:: python

    class HarbergerAgentManager(TurnBasedWithContinuousManager):
        # Class definition omitted for brevity

        def _initialize_agent(self) -> Agent:
            """
            Create and cache the agent instance based on the assigned role.
            """
            path_prompts = Path(__file__).parent / "prompts"
            if self._agent is None:
                if self.role == 1:
                    self._agent = Speculator(
                        llm=self.llm, game_id=self.game_id, logger=self.logger, prompts_path=path_prompts
                    )
                elif self.role == 2:
                    self._agent = Developer(
                        llm=self.llm, game_id=self.game_id, logger=self.logger, prompts_path=path_prompts
                    )
                elif self.role == 3:
                    self._agent = Owner(
                        llm=self.llm, game_id=self.game_id, logger=self.logger, prompts_path=path_prompts
                    )
                else:
                    self.logger.error("Invalid role assigned; cannot initialize agent.")
                    raise ValueError("Invalid role for agent initialization.")
            return self._agent

Game State (state.py)
~~~~~~~~~~~~~~~~~~~~~

The state file defines data structures for game state:

.. code-block:: python

    class HarbergerGameState(GameState):
        meta: HarbergerMetaInformation = Field(default_factory=HarbergerMetaInformation)
        private_information: HarbergerPrivateInformation = Field(default_factory=HarbergerPrivateInformation)
        public_information: HarbergerPublicInformation = Field(default_factory=HarbergerPublicInformation)

Game Specifications (specs/experiment.json)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The specifications file contains parameters for your experiment:

.. code-block:: json

    {
      "title": "",
      "tax_rate": {
        "initial": 1,
        "final": 33
      },
      "signal": {
        "low": 0.95,
        "high": 1.05,
        "generate": false
      },
      "speculators": {
        "count": 1,
        "balance": 50000,
        "shares": 5,
        "max_lot_purchases": 3,
        "cash_for_snipers": 250000,
        "base_points": 400000,
        "reward_scale_factor": 20000
      },
      // Additional configuration omitted for brevity
    }

Agent Prompts (prompts/)
~~~~~~~~~~~~~~~~~~~~~~~~

Prompts guide LLM-based agents in different game phases:

- ``*_system.jinja2``: System prompts that define the agent's role
- ``*_user_phase_X.jinja2``: User prompts for specific game phases
- ``all_*.jinja2``: Prompts applicable to all agent types

Running an Experiment
---------------------

To run an experiment you need to:

1. Create a new game from specifications and run it, or
2. Connect to an existing game and run it

For example, you could run an experiment on a notebook with the following code:

.. code-block:: python
    import nest_asyncio
    nest_asyncio.apply()

    import argparse
    import asyncio
    import os
    from datetime import datetime
    from pathlib import Path

    from dotenv import load_dotenv

    from econagents.core.game_runner import GameRunner, GameRunnerConfig
    from examples.server.create_game import create_game_from_specs
    from your_experiment.manager import YourAgentManager

    load_dotenv()

    # Configure the game runner
    config = GameRunnerConfig(hostname=HOSTNAME, port=PORT, log_path=LOG_PATH, games_path=GAMES_PATH)

    # Create game runner with your specific agent manager
    runner = GameRunner(config=config, agent_manager_class=YourAgentManager)

    # Generate a game name with timestamp
    game_name = f"your_experiment {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    # Create and run the game
    await runner.create_and_run_game(
        specs_path=specs_path, game_creator_func=create_game_from_specs, game_name=game_name
    )
