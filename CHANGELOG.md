# Changelog

All notable changes to econagents are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.1] - 2026-10-10

### Changed

- The `monty` extra now requires `pydantic-monty>=1.0.0,<2`.
  `PythonExecutionTool` runs each call in a fresh session checked out of a
  single-worker `AsyncMonty` pool, because 1.0 executes code in subprocess
  workers and dropped the one-shot `Monty(code).run_async()` API.
- Bumped ruff to 0.16 (dev group and pre-commit hook) and pinned the lint
  selection to the previous default rule set (`E4`, `E7`, `E9`, `F`), since
  0.16 enables a broader default set. Refreshed pydantic, pytest-asyncio and
  websockets in the lockfile.

## [0.5.0] - 2026-10-10

### Added

- `Agent.execute_phase_action` returns an `ActionOutcome` (`sent`,
  `not-transmitted`, `stale`, `no-action` or `skipped`, with the payload,
  frame and send error), and `Agent.register_action_listener` receives the
  outcome of every decision, including those started by phase transitions and
  the continuous loop. A failed send is therefore visible to the caller and to
  listeners, not only logged (IBEX-game_suite#7).
- `LLMCallRecord` and `econagents.adapters.llm.capture_llm_calls`: `ChatOpenAI`
  reports the finish reason (`completed` or the incomplete reason, such as
  `max_output_tokens`), token usage and raw text of every provider response
  (IBEX-game_suite#7). `parse_error` marks a model response whose structured
  output failed to parse; `response_error` marks an HTTP body that was not a
  model response at all (for example a proxy page served with status 200), so
  callers can tell model output failures from infrastructure failures.

### Fixed

- `ChatOpenAI` now tracks and logs a response whose structured output fails to
  parse (for example JSON truncated at `max_output_tokens`) before re-raising
  the SDK's `ValidationError`; previously the call never reached
  observability or the logger, so its finish reason and usage were lost. The
  forced final answer after `max_tool_iterations` is now tracked too.
  Structured requests go through `client.responses.with_raw_response.parse`.

## [0.4.0] - 2026-10-10

### Changed

- `max_game_duration` now bounds gameplay only: the `GameRunner` watchdog
  counts time from the first phase outside `GameRunnerConfig.pre_game_phases`
  (default `{"introduction"}`) that an agent reports, and pauses while a later
  round is back in a pre-game phase, so waiting for players to join and ready
  no longer uses up the budget (IBEX-game_suite#5). Phases are tracked per
  round and phase, so a phase replayed after a join or reconnect neither starts
  nor restarts the clock. Behaviour change: a run that waits in `introduction`
  is no longer stopped after `max_game_duration`. If no agent reports a phase,
  for example agents without `register_event_handler`, the budget still counts
  from the start of the run. The timeout warning still starts with
  `Game <id> reached maximum duration of <N>s` and now names the phase the
  gameplay clock started in.

### Added

- `GameRunnerConfig.max_pre_game_duration` (seconds, default `None`:
  unbounded) stops a run whose wait before gameplay, summed over the run,
  exceeds it, with a distinct `pre-game wait timeout` warning.
- `GameRunner.timeout_reason`: `"gameplay"`, `"pre_game"` or `None` after
  `run_game()`.
- A single `Gameplay started (phase=...)` log record per run, plus
  `Gameplay clock paused`/`resumed` records around later pre-game phases.

## [0.3.0] - 2026-10-09

### Fixed

- `Agent` makes one decision at a time: the phase-entry action and the
  continuous-phase loop no longer run two role decisions concurrently, and the
  loop starts its first delay after the phase-entry action finishes
  (IBEX-game_suite#6).
- A repeated phase-transition event for the current phase no longer starts a
  second continuous loop or a second decision while one is active. The current
  phase is identified by the phase id plus `state.meta.round` when the state
  defines one, so a game that reuses a phase id every round still gets a new
  decision when the round changes. A game whose state has no `meta.round` and
  that moves to the next round under the same phase id, with no other phase in
  between, stays in the same occurrence: the transition is logged at INFO and
  ignored while the old decision or loop is active, and for a turn-based phase
  also after the decision completed (see the decision gate below).
- A decision that is still in flight when the phase changes is cancelled, and a
  result decided in a phase the agent has left, or after `Agent.stop()`, is
  dropped instead of sent.
- `WebSocketTransport` authenticates every new connection: after an unexpected
  (1006) or clean (1001) close it reconnects and sends the `join` (or other
  `auth_mechanism`) message again before reading, so the server no longer drops
  everything the agent sends after a reconnect (IBEX-game_suite#8). A connection
  lost while authenticating is retried instead of stopping the transport.
  Reconnects back off: the first one after a connection that stayed open for
  `stable_connection_seconds` (default 5) is immediate, and connections that
  close sooner (for example a `join` rejected with `auth-error` after a server
  restart) are retried with exponential backoff and jitter from
  `reconnect_delay` (default 0.5 s) up to `max_reconnect_delay` (default 30 s),
  all three new `WebSocketTransport` arguments.
- A re-join no longer repeats a turn-based decision: once the decision for a
  non-continuous phase occurrence (phase id plus `state.meta.round`) has
  completed, by sending its action or by returning none, a later transition
  into the same occurrence, such as the snapshot requested after a reconnect,
  is logged at INFO and ignored (IBEX-game_suite#8). Before, a second
  declaration was refused by the server and a second speculation replaced the
  first. A decision that raised, was dropped as stale, or whose send raised
  `ConnectionError` is decided again on the next transition. Continuous phases
  are unchanged. This also applies to a game without `meta.round` that reuses a
  phase id for the next round (see Changed).

### Added

- `Agent(decision_gate=...)` takes an optional `DecisionGate` (`is_decided`,
  `mark_decided`) that the agent consults before a turn-based decision and
  updates after each completed one, so a store that outlives the process can
  stop a restarted agent from deciding again. Without one the gate is in
  memory, per `Agent` instance. `DecisionGate`, `DecisionOutcome` and
  `PhaseOccurrence` are exported from `econagents`. An exception from
  `is_decided` is logged and no decision is made on that transition; one from
  `mark_decided` is logged.

### Changed

- **Breaking:** a turn-based (non-continuous) phase occurrence, the phase id
  plus `state.meta.round`, is decided at most once per `Agent`. A game whose
  state has no `meta.round` and that starts the next round under the same phase
  id, with no other phase in between, used to get a new decision once the
  previous one had completed; it now gets none for that round. Give the state a
  `meta.round` field (or pass through another phase) so each round is a new
  occurrence. The bundled examples are not affected.
- **Breaking:** `WebSocketTransport.send()` raises `TransportSendError` (a
  `ConnectionError` subclass, exported from `econagents`,
  `econagents.adapters.transport` and `econagents.ports`) when there is no open
  connection, or when the connection closes or the socket fails while writing
  the frame. It used to log and return
  `None`, so a lost message was invisible to the caller. `TransportPort.send()`
  documents the same contract. `Agent` catches it and logs the action at ERROR
  as not transmitted, without retrying; code that calls `agent.transport.send()`
  directly (for example to request a snapshot) must handle `ConnectionError`.
- `WebSocketTransport.start_listening()` runs one listen loop per transport; a
  second call while one is active logs a warning and returns.
- An exception raised by a continuous-phase action is logged at ERROR level with
  its traceback and the loop continues; previously it ended the loop.
- `Agent.stop()` also cancels an in-flight phase-entry decision.
- `Agent.execute_phase_action()` waits for the agent's single decision slot, and
  its result is dropped if the phase changes while it is being decided. Called
  from inside a phase handler or role decision, it runs inline.
  `Agent.handle_phase_transition()` raises `RuntimeError` when awaited from
  inside a phase decision instead of deadlocking.

## [0.2.12] - 2026-09-07

### Added

- Added an `examples` extra (`pip install "econagents[examples]"`) that installs
  the dependencies the bundled example scripts need.
- Added `examples/prisoner/prisoner_openrouter.yaml`, a runnable OpenRouter
  variant of the Prisoner's Dilemma experiment, and an optional config path
  argument to `examples/prisoner/run_game_from_yaml.py`.

### Changed

- Relative `logs_dir` and `prompts_dir` values in a YAML `runner` section are
  now resolved against the directory containing the YAML file instead of the
  current working directory.
- `prisoner.yaml` now assigns agent 2 to the defector role, matching the README.
- Docs and docstrings invoke the examples as modules
  (`python -m examples.prisoner.run_game`) from the repository root.
- README, Tutorial and Installation docs describe a pip-only setup alongside
  `uv`, drop the stale LangSmith prerequisite, and note the Debian/Ubuntu
  `python3-venv` requirement.

### Fixed

- The stub LLMs in the `examples/*/verify.py` scripts accept the `logger`
  keyword the runtime now passes, so the key-free verification runs again.
- `WebSocketTransport` no longer tries to reconnect after `stop()` closed the
  connection, which removed the spurious "connect failed; reconnecting" log
  lines at the end of every game.

## [0.2.11] - 2026-08-13

### Fixed

- Updated `ChatOpenAI` reasoning-effort typing for `gpt-5.4-mini` to accept
  `none` and `xhigh` and remove the unsupported `minimal` value.

## [0.2.10] - 2026-08-10

### Added

- Added a `ChatOpenRouter` LLM adapter with structured outputs, tool calling,
  reasoning controls, model routing options, and optional app attribution.

## [0.2.9] - 2026-07-27

### Changed

- Reverted the 0.2.8 first-person `PERSONA_INSTRUCTION` rewrite: it left
  explicit-persona behaviour unchanged but substantially weakened implicit
  persona fidelity (implicit selfish went from 0% to 44% cooperation in the
  Prisoner's Dilemma benchmark). The directive is back to the 0.2.7 wording.

## [0.2.8] - 2026-07-27

### Changed

- Reframed `PERSONA_INSTRUCTION` to first-person reasoning: the model is asked
  to think through its decision as "I", from its own situation and outlook,
  instead of deciding "as this person would" from the outside. Drops the
  "neutral analyst" contrast clause.

## [0.2.7] - 2026-07-24

### Added

- LLM adapters now accept an optional `logger` in `get_response` and log every
  full provider response (reasoning items, output content, usage) at DEBUG
  level. Roles pass their per-agent logger automatically, so full LLM responses
  appear in the per-game log files alongside the prompts.

## [0.2.5] - 2026-07-14

### Fixed

- Fixed a race condition in per-agent log file setup where concurrent agent
  processes sharing the same log path could crash when another process removed
  the file first; the cleanup now tolerates an already-missing file.

## [0.2.4] - 2026-07-01

### Changed

- Enabled LangSmith observability in the continuous double auction OpenAI runner
  when the environment is configured for LangSmith.

### Fixed

- Fixed `observability_provider` wiring for code-created game runners so
  manually constructed agents send LLM traces to the configured observability
  backend instead of keeping the default no-op provider.

## [0.2.3] - 2026-06-29

### Added

- Added a local continuous double auction example with LLM-backed traders,
  structured market actions, a continuous `market` phase, a receive-only
  `summary` phase, local verification, and OpenAI-backed run instructions.

### Changed

- Updated game runner logging so an agent's WebSocket transport uses the
  per-agent run logger, capturing transport send/receive events in the same
  per-game log files as agent lifecycle events.
- Included local examples in source distributions while excluding generated
  local run logs and game specs.

## [0.2.2] - 2026-06-25

### Added

- Added local verification scripts for the prisoner, dictator, and public goods
  examples so each example can be exercised end-to-end against its local server
  without making external LLM calls.

### Changed

- Organized the package around explicit hexagonal boundaries:
  `domain`, `ports`, `runtime`, and `adapters`.
- Moved protocol, transport, configuration, prompt, parser, state projection,
  and LLM provider implementations under `econagents.adapters`.
- Moved roles, state models, events, and stable message types under
  `econagents.domain`.
- Moved runtime orchestration, phase handling, experiment factories, and game
  supervision under `econagents.runtime`.
- Renamed the participant runtime and behavior policy concepts to `Agent` and
  `Role`.
- Renamed the YAML configuration entry point to `YamlExperimentLoader` and the
  loaded YAML models to `ExperimentSpec`, `RoleSpec`, `AgentSpec`,
  `StateSpec`, `RuntimeSpec`, and `RunnerSpec`.
- Renamed the default response parser to `JsonResponseParser`.
- Updated local examples and local servers for the refactored runtime,
  transport, prompt rendering, and state projection APIs.
- Updated OpenAI-backed examples and documentation snippets to use
  `gpt-5.4-mini`.
- Updated the prisoner YAML examples to use the standard submit-choice envelope
  and explicit `phase` and `round` state fields.

### Fixed

- Fixed prompt state resolution in local examples so prompts render the current
  event-projected state, including per-round prisoner prompts, dictator payout
  prompts, and public goods personality and payoff prompts.
- Fixed dictator local server payout ordering so phase-two prompts receive the
  resolved decision and payout state before the payout phase starts.

[0.5.1]: https://github.com/IBEX-TUDelft/econagents/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/IBEX-TUDelft/econagents/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/IBEX-TUDelft/econagents/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.12...v0.3.0
[0.2.12]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.11...v0.2.12
[0.2.11]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.10...v0.2.11
[0.2.5]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.1...v0.2.2
