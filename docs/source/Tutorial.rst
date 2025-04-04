Tutorial
========

This tutorial will guide you through setting up and running the Prisoner's Dilemma experiment included in the ``examples/prisoner`` directory.

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
        "type": "event",
        "eventType": "round-result",
        "data": {
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

In this case, the ``EventField`` system updates the phase (using the ``round`` key) in ``PDMeta``, ``total_score`` in ``PDPrivate``, and ``history`` in ``PDPublic`` state. The ``payoffs`` key is ignored, because it was not included in the state definition.


Agent Manager Implementation
----------------------------

The ``PDManager`` class in ``examples/prisoner/manager.py`` extends the ``TurnBasedPhaseManager`` to handle the turn-based nature of the Prisoner's Dilemma game:

.. code-block:: python

    class Prisoner(AgentRole):
        # Define the agent role
        role = 1
        name = "Prisoner"
        llm = ChatOpenAI()

    class PDManager(TurnBasedPhaseManager):
        # Manager for the Prisoner's Dilemma game
        def __init__(self, game_id: int, auth_mechanism_kwargs: dict[str, Any]):
            super().__init__(
                auth_mechanism_kwargs=auth_mechanism_kwargs,
                state=PDGameState(game_id=game_id),
                agent_role=Prisoner(),
            )
            self.game_id = game_id
            self.register_event_handler("assign-name", self._handle_name_assignment)

        async def _handle_name_assignment(self, message: Message) -> None:
            """Handle the name assignment event."""
            ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
            await self.send_message(json.dumps(ready_msg))

The manager connects to the game server, maintains the game state, and orchestrates the agent's actions based on server events. When a new round starts, the manager updates the state and prompts the agent to make a decision.

In this example, the server assigns a name to the agent, and then expects the agent to send a ``player-is-ready`` event when it's ready to start the game. This is handled by the ``_handle_name_assignment`` method.

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

    Provide your choice as a JSON object with the following fields:
    - `gameId`: The ID of the game
    - `type`: The type of message, which should be "choice"
    - `choice`: The choice you made

    Example:
    ```json
    {
        "gameId": {{ meta.game_id }},
        "type": "choice",
        "choice": "COOPERATE",
    }
    ```

These templates leverage Jinja2 to dynamically insert the current game state. The agent's decision-making process follows the prompt resolution logic described in :doc:`Customizing_Agent_Roles`:

1. The system looks for phase-specific prompts first
2. If none are found, it falls back to general prompts
3. The LLM receives both system and user prompts and generates a response
4. The response is assumed to be a JSON object, which is parsed into a dictionary and sent as is to the server

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

To run the game:

.. code-block:: bash

    # Navigate to the project root
    cd examples/prisoner

    # Run the game
    python run_game.py

Behind the scenes, here's what happens:

1. The ``run_game.py`` script creates a game on the server via ``create_game_from_specs()``
2. It initializes a ``TurnBasedGameRunnerConfig`` with paths to logs and prompts
3. It creates ``PDManager`` instances for each player with appropriate authentication
4. The ``GameRunner`` connects all managers to the server and coordinates the game flow
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

You can also new agent roles (e.g., ``Cooperator``) and create agent-specific prompts (e.g., ``cooperator_system.jinja2``) to customize the agent's behavior.

You can also use the methods described in :doc:`Customizing_Agent_Roles` to create more sophisticated agents with phase-specific behaviors.


Modifying Game Rules
~~~~~~~~~~~~~~~~~~~~

For more advanced usage, you can:

1. Create your own game server for different economic experiments
2. Customize agent roles with different personalities or strategies
3. Implement more complex game rules and state management
4. Explore multi-agent scenarios with more than two players

Refer to the documentation on :doc:`Managing_Agents`, :doc:`Managing_State`, and :doc:`Customizing_Agent_Roles` for more details.
