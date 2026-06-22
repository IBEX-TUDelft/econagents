# Changelog

All notable changes to econagents are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/IBEX-TUDelft/econagents/compare/v0.2.0...HEAD
