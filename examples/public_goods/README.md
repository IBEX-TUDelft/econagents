# Public Goods Game

This is an implementation of the Public Goods game, a classic economic experiment where players decide how much to contribute to a shared public good.

## Game Rules

- Players: 4 (default, configurable)
- Initial Endowment (M): $20 per player
- Public Good Efficiency (a): 0.5 (configurable)

Each player starts with an endowment of M tokens and must decide how much to contribute (gi) to a public good. The total contributions are multiplied by the efficiency factor (a) and distributed equally among all players.

**Payoff formula for player i:**
```
Payoff_i = M - gi + a * Σ(g)
```
Where:
- M = initial endowment
- gi = player i's contribution
- a = public good efficiency factor
- Σ(g) = sum of all players' contributions

## Running the Game

### Start the Server

First, start the WebSocket server:

```bash
cd examples/public_goods
python -m server.server
```

The server will start on `localhost:8765`.

### Run the Game with AI Agents

In a separate terminal, run the game with AI agents:

```bash
cd examples/public_goods
python run_game.py
```

This will:
1. Create a new game with specified parameters
2. Launch AI agents that connect to the server
3. Execute the two phases:
   - Phase 1: Contribution decision
   - Phase 2: Payout calculation and display
4. Log all interactions in the `logs/` directory

## Configuration

You can modify game parameters in `run_game.py`:

- `num_players`: Number of players (default: 4)
- `initial_endowment`: Starting tokens per player (default: 20.0)
- `public_good_efficiency`: Multiplier for public good (default: 0.5)

## File Structure

```
public_goods/
├── state.py              # Game state definitions
├── manager.py            # Agent role and manager classes
├── run_game.py           # Main game runner script
├── server/
│   ├── server.py         # WebSocket server implementation
│   ├── create_game.py    # Game creation utilities
│   └── games/            # Stored game configurations
├── prompts/              # Jinja2 templates for agent prompts
│   ├── player_system.jinja2        # System prompt for all players
│   ├── player_user_phase_1.jinja2  # Phase 1 contribution prompt
│   └── player_user_phase_2.jinja2  # Phase 2 payout display prompt
└── logs/                 # Game logs directory
```

## Game Phases

1. **Contribution Phase**: Each player decides how many tokens to contribute to the public good
2. **Payout Phase**: Server calculates and displays final payoffs based on all contributions