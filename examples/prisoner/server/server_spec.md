# Prisoner's Dilemma Server Messages

This document describes the WebSocket message protocol for the Prisoner's Dilemma game server. The server manages two-player games across multiple rounds where players must choose to cooperate or defect.

## Game Flow

The game progresses through the following states:

- **WAITING**: Game is waiting for players to join
- **PLAYING**: Game is active, players make choices each round
- **FINISHED**: Game has completed all rounds

## Client Messages (Sent to Server)

### join

Players use this message to join a game using a game ID and recovery code.

```json
{
  "type": "join",
  "gameId": 123,
  "recovery": "recovery_code_123"
}
```

### choice

Players submit their choice (cooperate or defect) for the current round.

```json
{
  "type": "choice",
  "choice": "cooperate"
}
```

Valid choices: `"cooperate"` or `"defect"`

## Server Messages (Sent to Client)

### error

Sent when there's an error with the client's request or game state.

```json
{
  "type": "error",
  "message": "Game 123 does not exist"
}
```

Common error scenarios:

- Invalid game ID
- Invalid recovery code
- Game is full (already has 2 players)
- Game not in playing state
- Invalid choice value

### assign-name

Sent to a player when they successfully join a game, assigning them a player name and number.

```json
{
  "type": "event",
  "eventType": "assign-name",
  "data": {
    "player_name": "Player 1",
    "player_number": 1
  }
}
```

### game-started

Sent to all players when the game begins (after both players have joined).

```json
{
  "type": "event",
  "eventType": "game-started",
  "data": {
    "game_id": 123,
    "player_number": 1,
    "player_name": "Player 1",
    "opponent_number": 2,
    "opponent_name": "Player 2",
    "rounds": 5,
    "payoff_matrix": {
      "cooperate": {
        "cooperate": [3, 3],
        "defect": [0, 5]
      },
      "defect": {
        "cooperate": [5, 0],
        "defect": [1, 1]
      }
    }
  }
}
```

The payoff matrix shows the rewards for each combination of player choices:

- Both cooperate: both get 3 points
- Player 1 cooperates, Player 2 defects: Player 1 gets 0, Player 2 gets 5
- Player 1 defects, Player 2 cooperates: Player 1 gets 5, Player 2 gets 0
- Both defect: both get 1 point

### round-started

Sent to all players at the beginning of each round.

```json
{
  "type": "event",
  "eventType": "round-started",
  "data": {
    "gameId": 123,
    "round": 1,
    "total_rounds": 5
  }
}
```

### round-result

Sent to all players after both have made their choices for a round.

```json
{
  "type": "event",
  "eventType": "round-result",
  "data": {
    "gameId": 123,
    "round": 1,
    "choices": {
      "1": "cooperate",
      "2": "defect"
    },
    "payoffs": {
      "1": 0,
      "2": 5
    },
    "total_score": 0,
    "history": [
      {
        "round": 1,
        "my_choice": "cooperate",
        "opponent_choice": "defect",
        "my_payoff": 0,
        "opponent_payoff": 5
      }
    ]
  }
}
```

The `history` array contains all rounds played so far from the perspective of the receiving player.

### game-over

Sent to all players when the game ends after all rounds are completed.

```json
{
  "type": "event",
  "eventType": "game-over",
  "data": {
    "gameId": 123,
    "result": "lose",
    "myFinalScore": 12,
    "opponentFinalScore": 18,
    "history": [
      {
        "round": 1,
        "myChoice": "cooperate",
        "opponentChoice": "defect",
        "myPayoff": 0,
        "opponentPayoff": 5
      },
      {
        "round": 2,
        "myChoice": "defect",
        "opponentChoice": "cooperate",
        "myPayoff": 5,
        "opponentPayoff": 0
      }
    ]
  }
}
```

The `result` field indicates the outcome from the receiving player's perspective:

- `"win"`: Player scored higher than opponent
- `"lose"`: Player scored lower than opponent
- `"tie"`: Both players scored the same

## Game Configuration

Games are configured via JSON files in the `games/` directory with the format `game_{id}.json`:

```json
{
  "recovery_codes": ["recovery_code_123", "recovery_code_456"]
}
```

Each game supports exactly 2 players and runs for 5 rounds by default.
