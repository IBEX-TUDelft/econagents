# Changelog

All notable changes to econagents are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-21

The default WebSocket message structure and authentication mechanism now use
the `{"meta": {...}, "payload": {...}}` envelope. This is **not** backward
compatible with the previous flat `{type, eventType, data}` protocol.

### Changed

- **Breaking:** `AgentManager._extract_message_data` now parses the envelope
  `{"meta": {"type": ...}, "payload": {...}}`. `meta.type` becomes the event
  type and `payload` the event data; every inbound message is treated as an
  event. Servers speaking the old `{type, eventType, data}` shape are no
  longer understood by the default parser.
- **Breaking:** `GameRunnerConfig.auth_mechanism` now defaults to the new
  `JoinPayloadAuth` (join handshake) instead of `SimpleLoginPayloadAuth`.

### Added

- `econagents.core.protocol` with `build_message`, `join_message`,
  `ready_message`, and the `INTRODUCTION_PHASE` constant for constructing
  message envelopes. All are re-exported from the top-level package.
- `econagents.JoinPayloadAuth`: authentication mechanism that sends the
  `{"meta": {"type": "join"}, "payload": {...}}` envelope. Keyword args become
  the payload (e.g. `recovery="<code>"`); a kwargs dict that already contains
  `meta` is sent through unchanged.
- `TurnBasedPhaseManager` and `HybridPhaseManager` now register a default
  handler for the `introduction` phase that declares the agent ready
  (`ready_message()`). Register your own handler for `INTRODUCTION_PHASE` to
  override it.
- `PhaseManager` now resolves the agent's own `state.meta.player_number` from
  any event carrying a `players` list (e.g. the `snapshot`), matching the
  `recovery` code from `auth_mechanism_kwargs` against each player entry. It is
  a no-op for games without a players list, a recovery code, or a
  `meta.player_number` field.
- `econagents.SimpleLoginPayloadAuth` is now exported at the top level (it
  remains available for servers using the flat login payload).

### Migration

- Update your server to speak the `{"meta": {...}, "payload": {...}}` envelope.
- Replace `auth_mechanism_kwargs={"type": "join", ...}` (raw payload sent by
  `SimpleLoginPayloadAuth`) with `auth_mechanism_kwargs={"recovery": "<code>"}`
  under the default `JoinPayloadAuth`, or pass a full `{"meta": ..., "payload":
  ...}` envelope.
- Remove any per-game `_extract_message_data` override and outbound-envelope
  or ready-handshake boilerplate that the new defaults now provide.
- To keep the previous behaviour, set
  `auth_mechanism=SimpleLoginPayloadAuth()` on your `GameRunnerConfig` and
  override `_extract_message_data` in your manager.

## [0.1.0] - 2026-04-23

### Changed

- **Breaking:** `openai` is now a required runtime dependency. The
  `econagents[openai]` extra has been removed — `pip install econagents`
  pulls in the OpenAI client by default.
- The `[standard]` extra now adds only `langsmith` on top of the base
  install (OpenAI is no longer listed there because it is required).
- `econagents.config_parser.basic` imports `AgentRole` from its canonical
  module (`econagents.core.agent_role`) instead of the top-level package,
  removing a latent circular import.

### Added

- `econagents.BaseConfigParser` and `econagents.BasicConfigParser` are
  now exposed at the top level.
- `econagents.core.state` re-exports `GameState`, `MetaInformation`,
  `PrivateInformation`, `PublicInformation`, `GameStateProtocol`,
  `PropertyMapping`, and `EventField`, so consumers can import directly
  from the subpackage.

### Removed

- **Breaking:** `ChatOpenAI` is no longer re-exported from the top-level
  `econagents` package. Use `from econagents.llm import ChatOpenAI`.
- Stale `econagents/core/transport/` directory (the implementation lives
  in `econagents/core/transport.py`; only orphaned `__pycache__` files
  remained).
- `examples/__init__.py` (examples are runnable scripts, not a package).

### Migration

- If you imported `ChatOpenAI` from the top-level package, switch to
  `from econagents.llm import ChatOpenAI`.
- If you installed via `pip install econagents[openai]`, drop the extra
  — `pip install econagents` is now sufficient.
- If you installed via `econagents[standard]`, nothing changes for you:
  both `openai` and `langsmith` are still installed.

[Unreleased]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/IBEX-TUDelft/econagents/compare/v0.1.2...v0.2.0
[0.1.0]: https://github.com/IBEX-TUDelft/econagents/releases/tag/v0.1.0
