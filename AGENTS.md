# Repository Guidelines

## Project Structure & Module Organization

- `econagents/`: Source package.
  - `core/` (agent_role, manager, state, game_runner, events, transport, logging_mixin)
  - `llm/` (openai, ollama, observability integrations)
  - `config_parser/` and `cli.py` (entry point `econagents`)
- `tests/`: Pytest suite mirroring package layout (see `tests/core/*`, `tests/llm/*`).
- `examples/`: Runnable experiments (`prisoner/`, `dictator/`, `public_goods/`) with local servers.
- `docs/`: Sphinx documentation (`make html`).
- `assets/`: Static assets (e.g., logo).

## Build, Test, and Development Commands

- Prereqs: Python 3.10+, Poetry. Install all extras and dev tooling:
  - `poetry install --all-extras`
- Run tests:
  - `poetry run pytest -q`
  - Coverage: `poetry run pytest --cov=econagents --cov-report=term-missing`
- Lint and format (Ruff):
  - `poetry run ruff check .`
  - `poetry run ruff format .`
- Build docs: `poetry run make -C docs html`
- Run an example locally:
  - Server: `poetry run python examples/prisoner/server/server.py`
  - Client: `poetry run python examples/prisoner/run_game.py`

## Coding Style & Naming Conventions

- Use type hints throughout. Prefer Pydantic models for validated data structures in `core/state`.
- Naming: modules/packages `snake_case`; classes `CamelCase`; functions/vars `snake_case`; tests `test_*.py`.
- Keep public APIs documented with concise docstrings. Avoid unused imports and dead code. Run Ruff before committing.
- Don't use excessive comments; code should be self-explanatory. When deleting code, remove it entirely rather than commenting out. Don't add comments about code deletions.

## Testing Guidelines

- Framework: Pytest (with `pytest-asyncio` when needed). Place tests under `tests/` mirroring source (e.g., `tests/core/test_game_runner.py`).
- Conventions: files `test_*.py`, functions `test_*`. Prefer unit tests, mock network/LLM calls, and use fixtures from `tests/conftest.py`.
- Aim for meaningful coverage; include failure paths. Generate reports with `--cov=econagents`.

## Commit & Pull Request Guidelines

- Commits: imperative, concise, and scoped (e.g., "Add public goods game", "Bump ruff to 0.12.12").
- PRs: clear description, motivation, and linked issues; include tests and docs updates; keep changes focused and small.
- Enable hooks: `pre-commit install` (see `.pre-commit-config.yaml`). All hooks must pass locally.

## Security & Configuration Tips

- Never commit secrets. Use `.env` (example in `.env.example`). Common vars: `OPENAI_API_KEY`, `OLLAMA_HOST`, `LANGSMITH_API_KEY`, `LANGFUSE_*`.
- Prefer local providers (e.g., Ollama) during development; avoid real network calls in tests.
