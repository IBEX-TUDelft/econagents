# Dictator Game Implementation

This is an implementation of the Modified Dictator Game, an economic experiment where one player (the dictator) decides how to split a sum of money with another player (the receiver).

## Game Description

### Roles
- **Dictator**: Receives an amount of money and decides how much to send to the receiver
- **Receiver**: Passively receives whatever the dictator sends (multiplied by exchange rate)

### Phases
1. **Decision Phase**: The dictator decides how much money to send
2. **Payout Phase**: Both players receive their payouts

### Parameters
- `money_available`: The initial amount given to the dictator (default: $10)
- `exchange_rate`: Multiplier applied to the amount sent to receiver (default: 3x)

### Payoffs
- **Dictator**: Keeps `money_available - money_sent`
- **Receiver**: Receives `money_sent × exchange_rate`

## Running the Game

### 1. Start the Server
```bash
python run_server.py
```

### 2. Run the Game (in another terminal)
```bash
python run_game.py
```

## File Structure

- `state.py`: Game state management classes
- `manager.py`: Agent manager for handling game logic
- `run_game.py`: Main script to run the game with agents
- `run_server.py`: Script to run the WebSocket server
- `server/`: Server implementation
  - `server.py`: WebSocket server for game coordination
  - `create_game.py`: Game creation utilities
- `prompts/`: Jinja2 templates for agent prompts
  - `dictator_system.jinja2`, `dictator_user.jinja2`: Prompts for dictator role
  - `receiver_system.jinja2`, `receiver_user.jinja2`: Prompts for receiver role
- `logs/`: Game logs (created automatically)

## Example Scenario

With default parameters ($10 available, 3x exchange rate):
- If dictator sends $0: Dictator keeps $10, Receiver gets $0
- If dictator sends $5: Dictator keeps $5, Receiver gets $15
- If dictator sends $10: Dictator keeps $0, Receiver gets $30
