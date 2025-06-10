Using EconAgents UI for Configuration
=====================================

The `econagents` framework can be configured programmatically or through YAML configuration files. To simplify the creation and management of these configuration files, the **EconAgents UI** project was developed.

.. contents:: Table of Contents
   :depth: 2
   :local:

What is EconAgents UI?
----------------------

EconAgents UI is a web-based graphical user interface designed to streamline the setup of economic experiments for the `econagents` Python library. It allows researchers and developers to:

- Manage multiple experiment configurations (projects).
- Define agent roles, including their names, IDs, LLM models, and task phases.
- Structure the game state, detailing `MetaInformation`, `PrivateInformation`, and `PublicInformation` fields.
- Create and manage system and user prompts using Jinja templating, with support for reusable partials.
- Configure game runner settings, such as connection details and phase management.

The primary output of the EconAgents UI is a YAML configuration file (e.g., `experiment_config.yaml`) that is fully compatible with the `econagents` library.

You can access the EconAgents UI at `https://econagents.iwanalabs.com/`. The UI is hosted on a separate repository, `https://github.com/iwanalabs/econagents-ui`.

Workflow: From UI Configuration to Experiment Execution
-------------------------------------------------------

The general workflow for using the EconAgents UI with the `econagents` library is as follows:

1.  **Configure in the UI**:
    Use the EconAgents UI to create a new project or modify an existing one. Define all aspects of your experiment, including agent roles, game state definitions, prompts for various phases, and overall runner configurations.

2.  **Obtain the YAML Configuration File**:
    The UI will manage and allow you to access the YAML configuration file that represents your experiment setup. This file encapsulates all the settings you've defined. Examples of such configuration files can be seen in the `econagents` library under `examples/prisoner/prisoner.yaml` or `examples/ibex_tudelft/futarchy_yaml/futarchy_config.yaml`.

3.  **Run the Experiment with `econagents`**:
    Use the generated YAML file with the `econagents` Python library to run your experiment. The library includes parsers and runners that can directly consume this YAML file.

Running an Experiment from a YAML Configuration File
----------------------------------------------------

The `econagents` library provides a convenient function, `run_experiment_from_yaml`, to load an experiment configuration from a YAML file and execute it. This function handles the parsing of the YAML, initialization of agents, managers, and the game runner according to the specifications in the file.

Here's a conceptual example of how you might run an experiment using a YAML file:

.. code-block:: python

    import asyncio
    from pathlib import Path
    from econagents.config_parser.base import run_experiment_from_yaml
    # You'll typically have a helper script to create the game on your server
    # and get necessary details like game_id and login_payloads.
    # For instance:
    # from your_project.create_game_utils import create_game_and_get_details

    async def main():
        # Step 1: Create the game on your game server.
        # This step is specific to your game server's API.
        # You need to obtain the 'game_id' and 'login_payloads' for each agent.
        #
        # Example (replace with your actual game creation logic):
        # game_details = await create_game_and_get_details(
        #     game_server_url="http://localhost:8000",
        #     game_spec_file="path/to/your_game_spec.json"
        # )
        # game_id = game_details["game_id"]
        # login_payloads = game_details["login_payloads"]

        # For demonstration, using placeholder values:
        game_id = 12345  # Replace with actual game ID
        login_payloads = [
            {"agent_id": 1, "type": "join", "gameId": game_id, "recovery": "recovery_code_agent1"},
            {"agent_id": 2, "type": "join", "gameId": game_id, "recovery": "recovery_code_agent2"},
            # Add more agent login payloads as needed
        ]

        # Step 2: Specify the path to your YAML configuration file
        # This file is generated or managed by the EconAgents UI.
        config_file_path = Path("path/to/your_experiment_config.yaml")

        # Step 3: Run the experiment using the YAML configuration
        print(f"Running experiment for game_id: {game_id} using config: {config_file_path}")
        await run_experiment_from_yaml(
            config_yaml_path=config_file_path,
            login_payloads=login_payloads,
            game_id=game_id
            # You might need to pass other arguments depending on your setup,
        )
        print("Experiment completed.")

    if __name__ == "__main__":
        # Note: Ensure any necessary environment variables (e.g., API keys) are set.
        asyncio.run(main())

You can find practical examples of scripts that run experiments from YAML files in the `examples` directory of the `econagents` library, such as:
- `examples/prisoner/run_game_from_yaml.py`
- `examples/ibex_tudelft/futarchy_yaml/run_game_from_yaml.py`

These examples demonstrate how to integrate game creation on a server with the `run_experiment_from_yaml` function.

Further Information
-------------------

For detailed instructions on installing and using the EconAgents UI itself, please refer to the `README.md` file and any accompanying documentation within the EconAgents UI project repository. The UI is designed to be intuitive, but its specific documentation will provide the most up-to-date guidance on its features and operation.
