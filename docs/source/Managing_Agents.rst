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

Action Outcomes
---------------

``agent.execute_phase_action(phase)`` returns an ``ActionOutcome`` (``from
econagents import ActionOutcome``) saying what became of the decision. Its
``status`` is ``"sent"``, ``"not-transmitted"`` (the transport raised
``ConnectionError``, kept in ``error``), ``"stale"`` (the decision finished
after the agent left the phase occurrence, so nothing was sent),
``"no-action"``, ``"skipped"`` or ``"superseded"`` (a revision guard discarded
it, see below); ``transmitted`` is ``True`` only for ``"sent"``. Its
``decision_id`` names the decision in the decision trace, and its
``disposition`` is set once the decision is settled. To record outcomes of every decision, including the ones started
by phase transitions and the continuous loop, register a listener:

.. code-block:: python

   def on_action(outcome):
       if not outcome.transmitted and outcome.payload:
           journal.add(outcome.phase, outcome.status, outcome.payload)

   agent.register_action_listener(on_action)

Listeners may be async. They run after the send attempt, inside the
agent's single-flight decision; an exception in a listener is logged and
ignored.

Model Call Metadata
-------------------

``ChatOpenAI`` reports the finish reason, token usage and raw text of every
provider response it receives as an ``LLMCallRecord``, also when a structured
output fails to parse (for example JSON cut off at ``max_output_tokens``, where
the SDK raises a pydantic ``ValidationError`` that ``get_response`` re-raises).
That response is also tracked by the observability provider and logged to the
``logger`` passed to ``get_response``. Collect the records with
``capture_llm_calls``:

.. code-block:: python

   from econagents.adapters.llm import capture_llm_calls

   with capture_llm_calls() as calls:
       response = await llm.get_response(messages, tracing_extra={}, response_schema=Decision)
   calls[-1].finish_reason  # "completed", "max_output_tokens", ...
   calls[-1].usage          # {"input_tokens": ..., "output_tokens": ..., "reasoning_tokens": ...}

When the HTTP body is not a Responses API payload at all (for example an HTML
page from a proxy, served with status 200), no model output was received: the
record has ``response_error`` set instead of ``parse_error``, and the original
decoding error is re-raised. ``parse_error`` therefore means the model answered
and its output did not fit the schema; ``response_error`` means the call itself
failed.

Adapters other than ``ChatOpenAI`` do not report records yet, so the list stays
empty for them.

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

Dispositions and Decision Traces
--------------------------------

Sending an action does not mean the server accepted it. A
``DispositionTracker`` maps server events to the dispositions of the agent's
own submissions, and the agent does not start its next decision, in any
phase, until the previous submission has one:

.. code-block:: python

   class AckTracker:
       def __init__(self):
           self.pending = []

       def submitted(self, decision_id, message, state) -> bool:
           self.pending.append(decision_id)
           return True  # wait for this submission's disposition

       def observe(self, event, state):
           if event.type in ("order-accepted", "order-refused") and self.pending:
               return [(self.pending.pop(0), "accepted" if event.type == "order-accepted" else "refused")]
           return []

   agent = Agent(..., disposition_tracker=AckTracker(), decision_trace=records.append)

``submitted`` runs just before the frame is handed to the transport; if the
send raises, the agent calls the tracker's optional
``not_transmitted(decision_id)`` and does not wait. ``observe`` sees every
event in arrival order, after state projection and before event handlers.
A hold or no-op needs no disposition. Each decision gets its own
``decision_id``, so a later decision may send a byte-identical payload.

``disposition_timeout`` (seconds; ``None``, the default, waits indefinitely)
records a missing answer as ``"unknown"``; a tracker may also return a
disposition starting with ``"unknown"``. With ``on_unknown="block"`` (the
default) the agent then makes no new decision until the next
``phase_transition_event`` reconciles the state. While it waits it calls
``reconcile_request`` (for example a function that asks the server for a
snapshot) at once and then every ``reconcile_retry_interval`` seconds, at most
``reconcile_retry_limit`` times. ``on_unknown="continue"`` only records it.

The role decides on a frozen deep copy of the state, taken when the decision
starts (``decision_input="frozen"``, the default), so events that arrive
during a model call do not change its input. ``"guard-discard"`` decides on the
live state and drops the action (status ``"superseded"``) when the state's
revision changed during the decision; ``"guard-rerun"`` decides once more on
the new state first. ``input_revision`` computes the revision (default: sha256
of the state's JSON form).

``decision_trace`` receives one record per decision once it is settled:
``decision_id``, ``phase``, ``round``, ``phase_epoch``, ``input_revision``,
``send_revision``, ``input_changed_during_call``, ``submitted`` (the frame or
``None``), ``status`` and ``disposition``. Without a tracker, a sent action is
settled with disposition ``"sent"``; other values are ``"no-action"``,
``"stale-phase"`` (decided in a phase occurrence the agent has left),
``"not-transmitted"`` and ``"superseded"``. Revisions are only computed when a
trace or a guard mode needs them.

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

Agent Logs and Identity
-----------------------

With ``logs_dir`` set, the runner writes ``game_<id>/agent_<n>.log`` per agent,
tags its records ``[AGENT n]`` in ``all.log``, and names both by the agent's
player number when ``state.meta.player_number`` is set at launch. An agent
without one uses its launch index (offset past the largest player number if it
would collide with a seat's file). ``agent_log_naming="launch-index"`` keeps
launch-index names for every agent.

The first line of every agent log is a JSON identity header
(``"record": "agent-identity"``) with ``trace_schema_version``, ``run_id``
(``GameRunnerConfig.run_id``), ``game_id``, ``player_number``, ``role``,
``seat_kind``, ``agent_instance_id``, ``launch_index`` and ``log_naming``. The
log is appended to, not truncated: a replacement agent for the same seat (a
second runner with the same ``logs_dir``) adds its own header with a new
``agent_instance_id`` and keeps the earlier instance's records.

The header holds the configured seat. Once the server confirms it, the agent
logs an ``Identity bound`` record and exposes ``agent.bound_identity`` (also
``transport.bound_identity`` on ``WebSocketTransport``). The agent takes it
from the snapshot's own ``playerNumber`` and ``role``, else from the first
``player-joined`` received after each join, else from the roster entry with
its recovery token. An agent launched without a player number gets it this
way. If the server binds a configured agent to another seat or role, the agent
logs ``identity-mismatch``, sets ``agent.identity_error`` and stops.

Each model call made by the default ``Role`` LLM path is written as one JSON
line to ``agent_<n>.model_calls.jsonl``: the messages as sent and, for every
provider response the adapter reports, its id, model, finish reason, usage and
raw text (see ``capture_llm_calls``).
