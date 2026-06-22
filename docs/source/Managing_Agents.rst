Agents
==============

``Agent`` is the runtime for one simulated player. It composes the
transport, protocol codec, state projector, phase engine, role, and prompt
directory into a single event loop.

Responsibilities
----------------

An agent:

* receives raw messages from ``WebSocketTransport``;
* decodes them with a ``MessageCodec`` such as ``IbexMessageCodec``;
* applies each event to ``GameState`` through a ``StateProjector``;
* detects phase transitions;
* executes role actions once for turn-based phases or repeatedly for
  continuous phases;
* encodes outbound actions and sends them through the transport;
* stops itself when the configured end-game event arrives.

Creating An Agent
-----------------

.. code-block:: python

   from pathlib import Path
   from econagents import Agent, PhaseEngine, create_game_state

   agent = Agent(
       url="ws://localhost:8765",
       state=create_game_state(MyState, game_id=1),
       role=MyRole(),
       prompts_dir=Path("prompts"),
       auth_mechanism_kwargs={"recovery": "<code>"},
       phase_transition_event="phase-started",
       phase_identifier_key="phase",
   )

   await agent.start()

Continuous Phases
-----------------

Use ``PhaseEngine`` when an agent should keep acting while a phase remains
active:

.. code-block:: python

   agent = Agent(
       url="ws://localhost:8765",
       state=create_game_state(MyState, game_id=1),
       role=MyRole(),
       prompts_dir=Path("prompts"),
       auth_mechanism_kwargs={"recovery": "<code>"},
       phase_engine=PhaseEngine(
           continuous_phases={"market"},
           min_action_delay=5,
           max_action_delay=10,
       ),
   )

Phase Handlers
--------------

Register a phase handler when a phase should be handled by application code
instead of the role's LLM decision path:

.. code-block:: python

   async def submit_ready(phase, state):
       return {"meta": {"type": "ready"}, "payload": {}}

   agent.register_phase_handler("setup", submit_ready)

Event Handlers
--------------

Register event handlers for side effects that should run after state
projection:

.. code-block:: python

   async def log_assignment(event):
       print(event.data)

   agent.register_event_handler("assign-role", log_assignment)

Runner Supervision
------------------

``GameRunner`` supervises agents. It assigns per-agent loggers, starts all
agents concurrently, enforces ``max_game_duration``, and stops running
agents during cleanup. Agent construction belongs in code or YAML assembly;
the runner does not build or mutate agents.
