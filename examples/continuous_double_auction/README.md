# Continuous Double Auction

This local example implements a continuous double auction, a standard market institution in experimental economics. Buyers have induced private values and cash endowments, sellers have induced private costs, and LLM-backed agents submit bids or asks while the market phase remains open.

The important runtime feature is the continuous phase:

- The server emits `phase-transition` with `phase="market"`.
- Each agent is configured with `PhaseEngine(continuous_phases={"market"}, min_action_delay=8, max_action_delay=8)`.
- The agent acts once on entry, then keeps calling the role's LLM-backed market phase until the server moves out of `market`.
- The default induced schedules give each of the two buyers and two sellers five marginal units. That allows up to ten total unit trades, with several more surplus-preserving trades than the original two-unit schedule.
- The default local run keeps the market open for 60 seconds, unless all possible units trade first.
- After the market closes, the server emits a receive-only `summary` phase with final trades, cash balances, and surplus. Agents do not send an action in this phase.

The traders use `ChatOpenAI` and structured output for market orders, so set `OPENAI_API_KEY` before running the LLM-backed experiment. You can set `OPENAI_MODEL` to override the default model.

## Running The Example

Start the local WebSocket server:

```bash
uv run python examples/continuous_double_auction/server/server.py
```

In a separate terminal, run the agents:

```bash
uv run python examples/continuous_double_auction/run_game.py
```

The runner writes per-game and per-agent logs under `examples/continuous_double_auction/logs/game_<game_id>/`.
The local server writes submitted orders and trades to `examples/continuous_double_auction/logs/server.log`.

You can also run the end-to-end verification, which starts the server and agents in the same process:

```bash
uv run python examples/continuous_double_auction/verify.py
```

## Files

```text
continuous_double_auction/
├── agents.py             # LLM-backed trader role and structured action schema
├── run_game.py           # Local runner using HybridGameRunnerConfig
├── prompts/              # Trader prompts used by the LLM role
├── state.py              # EventField-backed market state
├── verify.py             # Local end-to-end check with a deterministic LLM stub
└── server/
    ├── create_game.py    # Game spec and induced value/cost schedule
    └── server.py         # WebSocket CDA server
```
