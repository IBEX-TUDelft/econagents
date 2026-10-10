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
same phase id every round. Without it, a next round that the server starts
under the same phase id, with no other phase in between, is the same
occurrence: a continuous phase's loop simply goes on, and a turn-based phase
gets no decision for that round, neither while the previous one is in flight
nor after it completed (see the decision gate below). When the phase changes, or the agent stops, the pending decision is
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
whose decision already finished is not decided again (see the decision gate
below).

The first reconnect after a connection that stayed open for
``stable_connection_seconds`` (default 5) is immediate. Connections that close
sooner, for example because the server answers the ``join`` with an
``auth-error`` and closes the socket after a server restart, are retried with
an exponential backoff with jitter that starts at ``reconnect_delay`` (default
0.5 s) and is capped at ``max_reconnect_delay`` (default 30 s). All three are
``WebSocketTransport`` constructor arguments, and ``stop()`` interrupts a
pending backoff.

``transport.send()`` raises ``TransportSendError`` (``from econagents import
TransportSendError``), a ``ConnectionError``, when the message was not
transmitted. The agent logs such an action at ERROR as not
transmitted and does not retry it; a continuous phase goes on with its next
decision. Event handlers that call ``agent.transport.send()`` themselves should
catch ``ConnectionError``.

Decision Gate
-------------

An agent decides each occurrence of a turn-based (non-continuous) phase at
most once. Once that decision has completed, a later transition into the same
occurrence, for example the snapshot a server sends after a re-join, is
logged at INFO and ignored instead of asking the role again. An occurrence is
the phase id plus ``state.meta.round``, as above. A decision counts as
completed when:

* its action was sent; or
* the phase handler or role returned no action. The agent cannot tell a
  deliberate hold from a result the role dropped, so a role that wants a
  failed decision retried on the next transition should raise instead.

It does not count when the handler or role raised, when the decision was
cancelled or dropped because the agent left the phase, or when sending raised
``ConnectionError``: such an action never reached the server, so the next
transition into the occurrence decides again. Continuous phases are not gated.

This memory belongs to the ``Agent`` instance and resets when the agent moves
to another occurrence, so returning to a phase with the same id and round
later in the game still gets a decision, and a restarted process decides
again. To keep decisions across restarts, pass a ``DecisionGate`` backed by
durable storage. The agent consults it, in addition to its own memory, before
a turn-based decision, and records every completed decision in it:

.. code-block:: python

   from econagents import DecisionOutcome, PhaseOccurrence

   class JournalGate:
       def is_decided(self, occurrence: PhaseOccurrence) -> bool:
           return journal.has(occurrence.phase, occurrence.round)

       def mark_decided(self, occurrence: PhaseOccurrence, outcome: DecisionOutcome) -> None:
           journal.add(occurrence.phase, occurrence.round, outcome)  # "sent" or "hold"

   agent = Agent(..., decision_gate=JournalGate())

The in-memory record forgets an occurrence as soon as the agent moves to
another one, but a store keyed on ``(phase, round)`` like the one above also
answers "decided" when the game comes back to the same phase id within one
round. That is fine for games whose phase ids are unique within a round (the
futarchy game is one); otherwise include something in the key that tells the
visits apart. If ``is_decided`` raises, the agent logs the error and makes no
decision on that transition, so a broken store cannot cause a second
submission; the next transition into the occurrence asks again. If
``mark_decided`` raises, the error is logged and the in-memory record still
holds.

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
the runner does not build agents. It only registers one event handler per
agent on the agent's phase event, to follow the phase for its timeout clock.

``max_game_duration`` bounds gameplay, not waiting for players. Time spent
in ``pre_game_phases`` (default ``{"introduction"}``) does not count, so a
human who joins or readies late does not use up the agents' budget. The clock
starts at the first phase outside that set that any agent reports, logs
``Gameplay started (phase=...)`` once, and pauses in a later round's pre-game
phase without resetting. Phases are tracked per round (``state.meta.round``,
or the event's ``round``), so a replayed phase after a join or reconnect
changes nothing. If no agent reports a phase, the budget counts from the start
of the run, as before.

The wait before gameplay is unbounded by default. Set
``max_pre_game_duration`` to stop the run when the pre-game wait, summed over
the run, exceeds it; that timeout is logged as ``pre-game wait timeout``.
After a run, ``runner.timeout_reason`` is ``"gameplay"``, ``"pre_game"`` or
``None``.
