Overview
========

This guide provides an overview of the econagents framework.

.. contents:: Table of Contents
   :depth: 3
   :local:

Components
----------

econagents is a framework that lets you use LLM agents into economic experiments. For that, it assumes that you have a game server that can be connected to.

There's a couple of assumptions econagents makes about the game server:

1. The server uses WebSockets to send messages to the client
2. The server sends messages in the following format:

.. code-block:: text

    {"message_type": <game_id>, "type": <event_type>, "data": <event_data>}

However, if the server doesn't use that format of messages, you can customize the `on_message_callback` of the `WebSocketTransport` to adjust the message parsing, so that it can be used with the rest of the framework.

Aside from that, the framework only assumes that you have a roles that agents can take, information about the game state, and phases where agents might take actions.

Key Components
-------------------------

econagents have four key components:

1. Agent Roles
2. Agent Manager
3. Game State
4. Game Runner


Agent Roles
~~~~~~~~~~~

Agent roles define the different roles players can take in your experiment:

For example, in a Harberger game, you might have the following roles:

.. code-block:: python

    from econagents import AgentRole

    class Speculator(AgentRole):
        role = 1
        name = "Speculator"
        task_phases = [3, 6, 8]  # Phases where this agent must perform a task
        llm = ChatOpenAI()

    class Developer(AgentRole):
        role = 2
        name = "Developer"
        task_phases = [2, 6, 7]
        llm = ChatOpenAI(model="gpt-4o")

    class Owner(AgentRole):
        role = 3
        name = "Owner"
        task_phases = [2, 6, 7]
        llm = ChatOpenAI(model="gpt-4o-mini")

When you create an agent role, you need to specify the following:

1. The role id
2. The name of the role
3. The task phases where the agent must perform a task
4. The LLM model to use

You must also specify prompts for the phases where the agent must perform a task.

For example, for a market phase, you might have the following system and user prompts:

.. code-block:: jinja
    :caption: System prompt for market phase (all_system_phase_6.jinja2)

    You are simulating a participant in an economic experiment focused on land development and tax share trading. Your goal is to maximize profits through strategic trading of tax shares, where each share's value depends on the total tax revenue collected.

    Key considerations:
    - Each share pays (Total Tax Revenue / 100) as dividends
    - You have access to both public and private signals about share values
    - You can post asks (sell offers) or bids (buy offers) for single shares

.. code-block:: jinja
   :caption: User prompt for market phase (all_user_phase_6.jinja2)

   **Game Information**:
   - Phase: Phase {{ meta.phase }}
   - Your Role: {{ meta.role }} (Player #{{ meta.player_number }})
   - Name: {{ meta.player_name }}
   - Your Wallet:
     - Tax Shares: {{ private_information.wallet.shares }}
     - Balance: {{ private_information.wallet.balance }}

    **Your Decision Options**:
    Provide the output (one of these options) as a JSON object:
    A. Post a new order:
    {
        "gameId": {{ meta.game_id }},
        "type": "post-order",
        "order": {
            "price": <number>, # if now=true, put 0 (will be ignored)
            "quantity": 1,
            "type": <"ask" or "bid">,
            "now": <true or false>,
            "condition": {{ public_information.winning_condition }}
        },
    }

    B. Cancel an existing order:
    {
        "gameId": {{ meta.game_id }},
        "type": "cancel-order",
        "order": {
            "id": <order_id>,
            "condition": {{ public_information.winning_condition }}
        },
    }

    C. Do nothing:
    {}

The prompts use Jinja templates, so you can use the game information to customize the prompts, and there is a flexible prompt resolution system. You can learn more about it in the :doc:`Customizing Agents <Customizing_Agents>` section.

Agent Manager
~~~~~~~~~~~~~

For each player you want to simulate, you need to create an agent manager. This agent manager takes care of the connection to the game server, the initialization of the agent based on the role, and the handling of the game events.

You can also adjust the agent manager to add custom logic, such as assigning roles of agents after the game has started.

.. code-block:: python

    from econagents import HybridPhaseManager
    from harberger.state import HLGameState

    class HAgentManager(HybridPhaseManager):
        def __init__(
            self,
            game_id: int,
            auth_mechanism_kwargs: dict[str, Any],
        ):
            super().__init__(
                state=HLGameState(game_id=game_id),
                auth_mechanism_kwargs=auth_mechanism_kwargs,
            )
            self.game_id = game_id
            self.register_event_handler("assign-name", self._handle_name_assignment)
            self.register_event_handler("assign-role", self._handle_role_assignment)

        def _handle_name_assignment(self, message: Message):
            ...
            # Custom logic to handle the name assignment event

        def _handle_role_assignment(self, message: Message):
            ...
            # Custom logic to handle the role assignment event



Game State
~~~~~~~~~~

The state file defines data structures for game state:

.. code-block:: python

    from econagents import GameState, MetaInformation, PrivateInformation, PublicInformation

    class Meta(MetaInformation):
        another_meta_info_field: str

    class PrivateInfo(PrivateInformation):
        private_info_field: str

    class PublicInfo(PublicInformation):
        public_info_field: str

    class MyGameState(GameState):
        meta: Meta = Field(default_factory=Meta)
        private_information: PrivateInfo = Field(default_factory=PrivateInfo)
        public_information: PublicInfo = Field(default_factory=PublicInfo)

This state will be available to all agents when handling phases. You can use them in prompts or in any custom phase handling logic.

The state is updated automatically using the information received from the game server. You can customize the state update logic using the approaches shown in the :doc:`State Management <State_Management>` section.

Game Runner
-----------

To run an experiment you need to:

1. Create a new game on your server
2. Set up the agent roles, agent managers, and game state
3. Use the `GameRunner` to run the experiment

The `GameRunner` is responsible for: connecting to the game server, spawning the agents, and handling the game events.

For example, you could run an experiment on a notebook with the following code:

.. code-block:: python

    from econagents import GameRunner, GameRunnerConfig

    config = GameRunnerConfig(
        game_id=1
    )
    game_runner = GameRunner(config=config, agents=[HAgentManager(game_id=1), HAgentManager(game_id=1)])
    await game_runner.run_game()

This will connect to the game server, spawn the agents, and handle the game events.
