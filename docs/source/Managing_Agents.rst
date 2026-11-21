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

``ChatOpenAI`` reports the finish reason, token usage, raw text and any reasoning
summaries of every provider response it receives as an ``LLMCallRecord``, also
when a structured output fails to parse (for example JSON cut off at
``max_output_tokens``, where the SDK raises a pydantic ``ValidationError`` that
``get_response`` re-raises).
That response is also tracked by the observability provider and logged to the
``logger`` passed to ``get_response``. Collect the records with
``capture_llm_calls``:

.. code-block:: python

   from econagents.adapters.llm import capture_llm_calls

   with capture_llm_calls() as calls:
       response = await llm.get_response(messages, tracing_extra={}, response_schema=Decision)
   calls[-1].finish_reason  # "completed", "max_output_tokens", ...
   calls[-1].usage          # {"input_tokens": ..., "output_tokens": ..., "reasoning_tokens": ...}
   calls[-1].reasoning_summary  # ["First summary entry", ...], or None

To request native summaries from a supported OpenAI model, configure
``ChatOpenAI(reasoning_summary="auto")``. The adapter collects text from
``summary_text`` entries in each response's ``reasoning`` output items, in
response order. These summaries are separate from the action output and do
not require changes to prompts or client messages. Missing or empty summaries
are recorded as ``None``. Summaries are retained for each response in a tool
loop and when structured-output parsing fails.

When the HTTP body is not a Responses API payload at all (for example an HTML
page from a proxy, served with status 200), no model output was received: the
record has ``response_error`` set instead of ``parse_error``, and the original
decoding error is re-raised. ``parse_error`` therefore means the model answered
and its output did not fit the schema; ``response_error`` means the call itself
failed.

Adapters other than ``ChatOpenAI`` do not report records yet, so the list stays
empty for them.

Prompt Size Limit
-----------------

A prompt that includes game state or text typed by participants can grow
without bound. ``ChatOpenAI``, ``ChatOpenRouter`` and ``ChatOllama`` accept
``max_message_tokens`` to cap it:

.. code-block:: python

   llm = ChatOpenAI(model_name="gpt-5.4-mini", max_message_tokens=4000)

In a YAML config it goes under the role's ``llm_params``:

.. code-block:: yaml

   roles:
     - role_id: 1
       name: "player"
       llm_type: "ChatOpenAI"
       llm_params:
         model_name: "gpt-5.4-mini"
         max_message_tokens: 4000

``build_messages`` then cuts the system prompt and the user prompt to their
first ``max_message_tokens`` tokens each. The limit applies to each message,
not to the two together, and it is the end of a prompt that is dropped. A
prompt at or under the limit is sent unchanged. Each cut is logged as a
WARNING with the token counts, for example ``user message trimmed from 5210
to 2000 tokens``. The model-call log holds the messages after the cut. Tool
results added during a tool loop and the model's output are never cut.

Tokens are counted with ``tiktoken``, which the ``tokens`` extra installs
(``pip install econagents[tokens]``). An adapter created with
``max_message_tokens`` raises ``ImportError`` when it is missing. tiktoken
only knows OpenAI models. For any other model name, which includes most Ollama
and OpenRouter models, the count is made with the ``o200k_base`` encoding and
is an estimate of what the model's own tokenizer gives. tiktoken downloads an
encoding's file the first time it is used and caches it; the adapter loads it
when it is created.

Request Limits and Moderation
-----------------------------

``ChatOpenAI`` and ``ChatOpenRouter`` bound how long a model call can take:

- ``timeout`` (seconds, default ``120``): one request fails with a timeout
  after that long. The ``openai`` package's own default is 600 seconds;
  ``timeout=None`` restores it.
- ``max_retries`` (default ``None``, the package's 2): how often the package
  sends a failed request again, after a connection error, a timeout or a 408,
  409, 429 or 5xx answer. So a call that never answers fails after
  ``timeout x (max_retries + 1)`` seconds, six minutes by default. With
  ``max_retries=0`` one model call is one request, and ``Role.decision_retries``
  is then the only retry.

``ChatOpenAI`` has two more settings, both off by default:

- ``moderation``: OpenAI moderates the request's input and the model's output
  on the same call. ``True`` uses ``omni-moderation-latest``; a string names
  another moderation model. The result never blocks or changes the response.
  It is reported in ``LLMCallRecord.moderation`` (per side: ``flagged``, the
  flagged ``categories``, the ``category_scores`` and the moderation ``model``,
  or ``error`` and ``message`` when moderation failed), which the model-call
  log includes, and flagged content is logged as a WARNING. Use it when prompts
  carry text typed by participants. It sends a ``moderation`` parameter with
  every request, which a server that only imitates the Responses API may
  refuse.
- ``safety_identifier``: a stable identifier for the end user behind the
  requests, so that OpenAI can act on one user rather than on the whole
  organization. Send a hash, never a name or an address.

.. code-block:: python

   llm = ChatOpenAI(
       model_name="gpt-5.4-mini",
       timeout=60,
       max_retries=0,
       moderation=True,
       safety_identifier="3f1c9a52",
   )

In a YAML config they go under the role's ``llm_params``, like
``max_message_tokens``.

Other limits of the Responses API go through ``response_kwargs``, unchanged:
``max_output_tokens`` caps the output including reasoning tokens (a response
cut there has the finish reason ``max_output_tokens`` in its call record, and
a structured output cut there fails to parse), and ``store: False`` keeps
OpenAI from storing the response. A key in ``response_kwargs`` wins over the
setting of the same name.

Spending limits are not request parameters: set a budget for the API key's
project in the provider's dashboard.

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
disposition starting with ``"unknown"``. The tracker reconciles such a
decision by returning its ``decision_id`` from ``observe`` again with a
disposition that is not unknown, once it has evidence (for example a snapshot
newer than the submission). With ``on_unknown="block"`` (the default) the
agent makes no new decision in that phase occurrence until the tracker
reconciles it; no event releases the block by itself. When the agent moves to
a different phase occurrence, the action's phase has closed and the next
decision reads the new occurrence's state: the decision stops blocking and
keeps its ``"unknown"`` disposition. While it waits the agent calls
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
``"not-transmitted"`` and ``"superseded"``. A decision whose disposition was
unknown gets a second record: with the reconciled ``disposition`` and
``reconciled_from`` when the tracker reconciles it, or with
``unresolved_at_phase_close: True`` (and the unknown disposition) when its phase
occurrence ends first. Revisions are only computed when a trace or a guard mode
needs them.

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
provider response the adapter reports, its id, model, finish reason, usage,
raw text and any reasoning summaries (see ``capture_llm_calls``).
