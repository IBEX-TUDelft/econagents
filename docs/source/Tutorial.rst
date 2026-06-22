Tutorial
========

This tutorial will guide you through setting up and running the Prisoner's Dilemma experiment included in the ``examples/prisoner`` directory.

For more examples, see the `econagents cookbook <https://github.com/iwanalabs/econagents-cookbook/tree/main/>`_.

Prerequisites
-------------

Before running an experiment, ensure you have:

1. Python 3.10+ installed
2. All dependencies installed
3. Have set up API keys for OpenAI and LangSmith

Create a ``.env`` file in your project root with the following variables:

.. code-block:: text

    LANGCHAIN_API_KEY=<your_langsmith_api_key>
    LANGSMITH_TRACING=true
    LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
    LANGSMITH_PROJECT="econagents"

    OPENAI_API_KEY=<your_openai_api_key>

Understanding the Prisoner's Dilemma Experiment
-----------------------------------------------

The Prisoner's Dilemma is a classic game theory scenario where two players must decide whether to cooperate or defect simultaneously. The experiment in this repository demonstrates how AI agents can be used in this scenario to observe their decision-making processes.

The experiment consists of:

1. A game server that manages the game state and rules
2. AI agents that play the roles of prisoners
3. A game runner that coordinates the interaction between agents and the server

How State Management Works
--------------------------

The Prisoner's Dilemma experiment uses the econagents framework's hierarchical state management system. In ``examples/prisoner/state.py``, you can find the three components:

.. code-block:: python

    class PDMeta(MetaInformation):
        # Game metadata, including game ID, current round, and total rounds
        game_id: int = EventField(default=0, exclude_from_mapping=True)
        phase: int = EventField(default=0, event_key="round")
        total_rounds: int = EventField(default=5)

    class PDPrivate(PrivateInformation):
        # Player-specific information not visible to other players
        total_score: int = EventField(default=0)

    class PDPublic(PublicInformation):
        # Information visible to all players
        history: list[dict[str, Any]] = EventField(default_factory=list)

    class PDGameState(GameState):
        # Main game state that combines all components
        meta: PDMeta = Field(default_factory=PDMeta)
        private_information: PDPrivate = Field(default_factory=PDPrivate)
        public_information: PDPublic = Field(default_factory=PDPublic)

The state gets updated automatically through the ``EventField`` system, which maps data from incoming events from the server to state fields.

For example, in our server implementation, the server sends events like after each round finishes:

.. code-block:: json

    {
        "meta": {"type": "round-result"},
        "payload": {
            "gameId": 1743761219,
            "round": 1,
            "choices": {
                "1": "cooperate",
                "2": "cooperate"
            },
            "payoffs": {
                "1": 3,
                "2": 3
            },
            "total_score": 3,
            "history": [
                {"round": 1, "my_choice": "cooperate", "opponent_choice": "cooperate", "my_payoff": 3, "opponent_payoff": 3}
            ]
        }
    }

The framework reads the event type from ``meta.type`` and the event data from ``payload``. In this case, the ``EventField`` system updates the phase (using the ``round`` key) in ``PDMeta``, ``total_score`` in ``PDPrivate``, and ``history`` in ``PDPublic`` state. The ``payoffs`` key is ignored, because it was not included in the state definition.


Agent Implementation
----------------------------

The prisoner example defines a role and an agent factory:

.. code-block:: python

    from econagents import Role
    from econagents.runtime import Agent, GameRunnerConfig, create_game_state

    class Prisoner(Role):
        role = 1
        name = "Prisoner"
        llm = ChatOpenAI()

    def create_prisoner_agent(config: GameRunnerConfig, recovery_code: str):
        return Agent(
            url=config.server_url(),
            auth_mechanism=config.auth_mechanism,
            auth_mechanism_kwargs={"gameId": config.game_id, "recovery": recovery_code},
            state=create_game_state(PDGameState, game_id=config.game_id),
            role=Prisoner(),
            prompts_dir=config.prompts_dir,
            phase_transition_event=config.phase_transition_event,
            phase_identifier_key=config.phase_identifier_key,
        )

The agent connects to the game server, maintains local state, and orchestrates
actions based on server events. When a new round starts, the agent projects the
event into state and prompts the role to make a decision.

The connection authenticates with the default :class:`~econagents.JoinPayloadAuth`, which
sends ``{"meta": {"type": "join"}, "payload": {...}}`` built from ``auth_mechanism_kwargs``.
During the ``introduction`` phase the agent declares itself ready by returning
``ready_message()``
(``{"meta": {"type": "ready", "component": {"type": "standard:ready"}}, "payload": {}}``).

To customize the handshake, register your own phase handler:

.. code-block:: python

    from econagents import INTRODUCTION_PHASE, build_message

    async def custom_ready(phase, state) -> dict:
        return build_message("ready", component="standard:ready")

    agent.register_phase_handler(INTRODUCTION_PHASE, custom_ready)

Prompt System and Agent Behavior
--------------------------------

The Prisoner's Dilemma example uses template-based prompts located in ``examples/prisoner/prompts/`` to define the agent's behavior.

1. **System Prompt** (``all_system.jinja2``): Sets up the agent's role and explains the game rules:

   .. code-block:: jinja

       You are playing the role of a criminal who has been arrested and is being interrogated by the police...

       In each round, you will need to choose between:
       - **Cooperate**: Remain silent (don't betray your partner)
       - **Defect**: Testify against your partner

       Your payoffs depend on both your choice and your partner's choice:
       - Both cooperate: You get 3, opponent gets 3
       - You cooperate, opponent defects: You get 0, opponent gets 5
       - You defect, opponent cooperates: You get 5, opponent gets 0
       - Both defect: You get 1, opponent gets 1

2. **User Prompt** (``all_user.jinja2``): Provides the current game state and instructions for the current round:

   .. code-block:: jinja

    # Make Your Choice

    ## Current Game State

    Round {{ meta.phase }} of {{ meta.total_rounds }} rounds
    Your current score: {{ private_information.total_score }}

    ## Your History

    {% if public_information.history %}
    Previous rounds:
    {% for round in public_information.history %}
    Round {{round.round}}: You chose **{{ round.my_choice}}**, opponent chose **{{ round.opponent_choice }}**. You earned {{ round.my_payoff }} points.
    {% endfor %}
    {% else %}
    This is the first round.
    {% endif %}

    ## Instructions

    Based on the current game state and your strategy, please choose whether to **cooperate** or **defect** in this round.

    Respond with only one of the following:
    1. "COOPERATE" - if you choose to remain silent (cooperate)
    2. "DEFECT" - if you choose to testify against the other player (defect)

    Respond with a JSON message of exactly this shape:
    ```json
    {
        "meta": {"type": "submit-choice", "component": {"type": "standard:coordination"}},
        "payload": {"choice": "COOPERATE"}
    }
    ```

These templates leverage Jinja2 to dynamically insert the current game state. The agent's decision-making process follows the prompt resolution logic described in :doc:`Customizing_Agent_Roles`:

1. The system looks for phase-specific prompts first
2. If none are found, it falls back to general prompts
3. The LLM receives both system and user prompts and generates a response
4. The response is parsed into a dictionary by the default ``parse_phase_llm_response`` and sent to the server

Rather than writing a custom parser, make the **response schema** the outbound message
envelope. The default ``parse_phase_llm_response`` returns ``response.model_dump()`` for a
structured response, so the validated schema *is* the message that gets sent — no custom
parser needed:

.. code-block:: python

    from typing import Literal

    from pydantic import BaseModel, Field
    from econagents import Role

    class Component(BaseModel):
        type: Literal["standard:coordination"] = "standard:coordination"

    class ChoiceMeta(BaseModel):
        type: Literal["submit-choice"] = "submit-choice"
        component: Component = Field(default_factory=Component)

    class ChoicePayload(BaseModel):
        choice: Literal["COOPERATE", "DEFECT"]

    class SubmitChoice(BaseModel):
        meta: ChoiceMeta = Field(default_factory=ChoiceMeta)
        payload: ChoicePayload

    class Prisoner(Role):
        role = 1
        name = "Prisoner"
        llm = ChatOpenAI()
        default_response_schema = SubmitChoice

The LLM produces ``{"meta": {"type": "submit-choice", "component": {"type": "standard:coordination"}}, "payload": {"choice": "COOPERATE"}}`` directly.

Running the Experiment
----------------------

Step 1: Start the Game Server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

First, you need to start the Prisoner's Dilemma game server. The server defines the game logic and handles the communication between agents.

.. code-block:: bash

    # Navigate to the prisoner server directory
    cd examples/prisoner/server

    # Start the server
    python server.py

This will start a WebSocket server on localhost port 8765. The server has methods to create a new game and generate recovery codes that agents use to join the game.

Step 2: Run the Prisoner's Dilemma Game
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once the server is running, you can start the game with AI agents. The game runner will:

1. Create a game by connecting to the server
2. Initialize AI agents with the appropriate roles
3. Handle the turn-based game flow
4. Log interactions for analysis

To run the game, **open a new terminal** and run:

.. code-block:: bash

    # Navigate to the project root
    cd examples/prisoner

    # Run the game
    python run_game.py

This will start the game runner, which will connect to the server and start the game. You should run this in a new terminal, and keep the server running in the other terminal.

Behind the scenes, here's what happens:

1. The ``run_game.py`` script creates a game on the server via ``create_game_from_specs()``
2. It initializes a ``TurnBasedGameRunnerConfig`` with paths to logs and prompts
3. It creates one ``Agent`` for each player with appropriate authentication
4. The ``GameRunner`` starts all agents and supervises the game flow
5. When a new round starts, each agent receives the current state and makes a decision
6. The server processes the decisions and updates the game state
7. This cycle continues until all rounds are completed

Step 3: Analyzing the Results
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After the game completes, you can analyze the results by:

1. Checking the logs in the ``examples/prisoner/logs`` directory
2. In LangSmith, you can view the full interaction history and decision-making processes in your LangSmith dashboard

The logs contain detailed information about:
- Agent decisions in each round
- Game state updates after each round
- Outcomes and scores

Customizing the Experiment
--------------------------

You can customize several aspects of the experiment:

Modifying Agent Prompts
~~~~~~~~~~~~~~~~~~~~~~~

Edit the templates in ``examples/prisoner/prompts/`` to change the agent's behavior:

- Change the payoff matrix in ``all_system.jinja2`` to explore different incentive structures (don't forget to update the game logic in server.py)
- Modify the instructions in ``all_user.jinja2`` to guide the agent toward specific strategies
- Create phase-specific prompts like ``all_system_phase_3.jinja2`` to change behavior in specific rounds

You can also define new roles (e.g., ``Cooperator``) and create role-specific prompts (e.g., ``cooperator_system.jinja2``) to customize the agent's behavior.

You can also use the methods described in :doc:`Customizing_Agent_Roles` to create more sophisticated agents with phase-specific behaviors.


Modifying Game Rules
~~~~~~~~~~~~~~~~~~~~

For more advanced usage, you can:

1. Create your own game server for different economic experiments
2. Customize roles with different personalities or strategies. For example, check out the `public goods game example <https://github.com/IBEX-TUDelft/econagents/tree/main/examples/public_goods>` for an scenario where each agent has a different personality and strategy.
3. Implement more complex game rules and state management
4. Explore multi-agent scenarios with more than two players

Refer to the documentation on :doc:`Managing_Agents`, :doc:`Managing_State`, and :doc:`Customizing_Agent_Roles` for more details.
