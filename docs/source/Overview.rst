Overview
========

This guide provides an overview of the econagents framework.

.. contents:: Table of Contents
   :depth: 3
   :local:

econagents is a framework that lets you use LLM agents in economic experiments. It assumes that you have a game server that runs the experiment that you can connect to, as well as api-level access to LLM agents that can be used in the experiment.

There's a couple of default assumptions econagents makes about the game server:

1. The server uses WebSockets to send messages to the client
2. The server sends messages in the following JSON format:

.. code-block:: text

    {"message_type": <game_id>, "type": <event_type>, "data": <event_data>}

However, if the server doesn't use that format of messages, you can customize the `on_message_callback` of the `WebSocketTransport` to adjust the message parsing, so that it can be used with the rest of the framework.

Aside from that, the framework only assumes that you have a description of the game including:
   - the roles that agents can take,
   - the phases the game goes through and actions the agents can take in these phases, and
   - a description of the information about the game state that is relevant.

The library has four key components:

1. Agent Roles
2. Agent Manager
3. Game State
4. Game Runner

Agent Roles
~~~~~~~~~~~

Agent roles define the different roles players can take in your experiment. For example, in a Prisoner's Dilemma game, you would have a Prisoner role that can cooperate or defect. In the Harberger-for-spatial-planning problem used in the TUDelft-IBEX/harberger example, you would have the roles Developer, Owner, and Speculator each with their own tasks spread over the phases of the experiment.

When you define an agent role, you need to specify at least the following:

1. The role id
2. The name of the role
3. The LLM model to use

Here's how this looks in code:

.. code-block:: python

    from econagents import AgentRole

    class Speculator(AgentRole):
        role = 1
        name = "Speculator"
        llm = ChatOpenAI()

    class Developer(AgentRole):
        role = 2
        name = "Developer"
        llm = ChatOpenAI(model="gpt-4o")

    class Owner(AgentRole):
        role = 3
        name = "Owner"
        llm = ChatOpenAI(model="gpt-4o-mini")

Given that you want your roles to take actions in specific phases of the game, you need to specify prompts for the phases where the agent must perform a task.
Prompts are separated into system prompts and user prompts, each can be altered per role and phase, or made persistent as required.

For example, in a game where there is a market where tax shares are traded in the 6th phase of the game, you might have the following system and user prompts:

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

The prompts use [Jinja templates](https://jinja.palletsprojects.com/en/stable/). This allows you to use variables from the game state and other information to customize the prompts.

You can learn more about this in the :doc:`Customizing Agent Roles <Customizing_Agent_Roles>` section.

Agent Manager
~~~~~~~~~~~~~

For each player you want to simulate using an agent, you need to create an agent manager. The agent manager takes care of the connection to the game server, the initialization of the agent based on the role and model used, and the handling of the game events.

You can adjust the agent manager to add custom logic, such as assigning roles of agents after the game has started instead of before the game starts.

Here's an example of an agent manager with custom logic that assigns names and roles after the relevant events have been received from the server:

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
                continuous_phases={3, 5},  # Explicitly specify phases 3 and 5 as continuous
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

.. note::
   By default, all phases are treated as turn-based. Only phases explicitly specified in the ``continuous_phases`` parameter are treated as continuous, with automatic periodic action execution.

Game State
~~~~~~~~~~

The state file of a game defines the data structures for the game state.

For example, in the Harberger-for-spatial-planning problem used in the TUDelft-IBEX/harberger example, you might have the following state:

.. code-block:: python

    from econagents import GameState, MetaInformation, PrivateInformation, PublicInformation

    class Meta(MetaInformation):
        game_name: str

    class PrivateInfo(PrivateInformation):
        wallet: str

    class PublicInfo(PublicInformation):
        winning_condition: str

    class MyGameState(GameState):
        meta: Meta = Field(default_factory=Meta)
        private_information: PrivateInfo = Field(default_factory=PrivateInfo)
        public_information: PublicInfo = Field(default_factory=PublicInfo)

The game state will be available to all agents during the phases. You can use them in prompts or in any custom phase handling logic.
The game state can be split into different parts with different properties, as you can see in this example the game state contains meta information that is used for the administration of the game (e.g. ID of agent, phase, etc.), private information that is specific to the agent (e.g. remaining resources, private signals), and public information (e.g. offers currently available on the market, public signals)

The state is updated automatically using the information received from the game server. You can customize the state update logic using the approaches shown in the :doc:`Managing State <Managing_State>` section.

Game Runner
~~~~~~~~~~~

Finally, to run a game you need to use the `GameRunner` class. This class is responsible for gluing everything together: agent managers and roles, game state, and the game server.

The steps to running a game with the GameRunner are:

1. Create a new game on your server
2. Set up the agent roles, agent managers, and game state
3. Use the `GameRunner` to run the game

The `GameRunner` is responsible for: connecting to the game server, spawning the agents, and handling the game events.

Here's an sample of how to run a game using the `GameRunner` class:

.. code-block:: python

    from econagents import GameRunner, TurnBasedGameRunnerConfig

    config = TurnBasedGameRunnerConfig(
        # Game configuration
        game_id=1,
        # Server configuration
        hostname="localhost",
        port=8765,
        path="wss",
    )
    agents = [
        PDManager(
            game_id=1
        ),
        PDManager(
            game_id=1
        ),
    ]
    runner = GameRunner(config=config, agents=agents)

This will connect to the game server, spawn the agents, and handle the game events.
