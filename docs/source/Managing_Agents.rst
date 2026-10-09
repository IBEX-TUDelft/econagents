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

An agent makes one decision at a time. The phase-entry action and the
continuous loop share a single decision slot, and the loop waits for the
phase-entry action to finish before its first delay. A repeated transition into
the current phase (for example a second snapshot after a reconnect) does not
start another decision or another loop while one is active; it is logged at
INFO. The current phase is identified by its phase id plus ``state.meta.round``
when the state defines a ``round`` field, so define one if your game reuses the
same phase id every round. Without it, a server that starts the next round
under the same phase id before the agent has acted gets no decision for that
round. When the phase changes, or the agent stops, the pending decision is
cancelled, and a result decided in a phase the agent has since left is logged
and dropped instead of sent. An exception raised by one continuous-phase action
is logged and the loop continues.

``execute_phase_action`` uses the same decision slot. A phase handler may call
it to run another phase's action inline, but must not await
``handle_phase_transition``, which raises ``RuntimeError`` inside a decision.

Connection Loss
---------------

``WebSocketTransport`` reconnects after the connection closes, whether the
close was abnormal or clean, and authenticates every new connection again
(``JoinPayloadAuth`` resends the ``join`` message) before reading from it. If
the server replays the current phase after the re-join while that phase's
decision or continuous loop is still active, the rule above ignores it, so the
reconnect does not start a second decision or loop. A replayed turn-based phase
whose decision already finished is decided again.

``transport.send()`` raises ``TransportSendError``, a ``ConnectionError``, when
the message was not transmitted. The agent logs such an action at ERROR as not
transmitted and does not retry it; a continuous phase goes on with its next
decision. Event handlers that call ``agent.transport.send()`` themselves should
catch ``ConnectionError``.

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
