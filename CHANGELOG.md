# Changelog

All notable changes to econagents are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.1...v0.2.2
