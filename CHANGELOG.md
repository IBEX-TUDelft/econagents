# Changelog

All notable changes to econagents are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/IBEX-TUDelft/econagents/releases/tag/v0.1.0
