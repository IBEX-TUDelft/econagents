# Dictator Game Server Messages

This document describes the WebSocket message protocol for the Dictator Game server. The server manages two-player games where one player (dictator) decides how to allocate money with another player (receiver).

Each game supports exactly 2 players (1 dictator, 1 receiver)

## Game Flow

The game progresses through the following states:

- **WAITING**: Game is waiting for players to join
- **DECISION**: Dictator makes allocation decision
- **PAYOUT**: Players receive their payouts
- **FINISHED**: Game has completed

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

### decision

The dictator submits their allocation decision for how much money to send to the receiver.

```json
{
  "type": "decision",
  "money_send": 5.0
}
```

- `money_send` must be non-negative and cannot exceed the available money
- Only the dictator can make this decision
- Only valid during the decision phase

### action

Players can send action messages to indicate completion of phases.

```json
{
  "type": "action",
  "action": "done"
}
```

Valid actions: `"done"` - indicates player is finished with current phase

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
- Game not in decision phase
- Only dictator can make decisions
- Invalid money_send amount (negative or exceeds available)
- Role already taken

### assign-role

Sent to a player when they successfully join a game, assigning them their role.

```json
{
  "type": "event",
  "eventType": "assign-role",
  "data": {
    "player_name": "Dictator",
    "role": "dictator"
  }
}
```

Roles: `"dictator"` (first recovery code) or `"receiver"` (second recovery code)

### game-started

Sent to all players when the game begins (after both players have joined).

```json
{
  "type": "event",
  "eventType": "game-started",
  "data": {
    "game_id": 123,
    "role": "dictator",
    "money_available": 10.0,
    "exchange_rate": 3.0
  }
}
```

- `money_available`: Total amount the dictator can allocate
- `exchange_rate`: Multiplier applied to money sent to receiver

### phase-started

Sent to all players at the beginning of each phase.

```json
{
  "type": "event",
  "eventType": "phase-started",
  "data": {
    "gameId": 123,
    "phase": 1,
    "phase_name": "decision",
    "role": "dictator"
  }
}
```

Phase names:

- Phase 1: `"decision"` - Dictator makes allocation choice
- Phase 2: `"payout"` - Players receive results

### decision-result

Sent to all players after the dictator makes their decision.

```json
{
  "type": "event",
  "eventType": "decision-result",
  "data": {
    "gameId": 123,
    "money_sent": 5.0,
    "money_available": 10.0,
    "exchange_rate": 3.0,
    "payouts": {
      "dictator": 5.0,
      "receiver": 15.0
    },
    "payout": 5.0
  }
}
```

- `money_sent`: Amount dictator chose to send
- `payouts`: Final payouts for both players
- `payout`: This player's individual payout

### game-over

Sent to all players when the game ends after both players complete the payout phase.

```json
{
  "type": "event",
  "eventType": "game-over",
  "data": {
    "gameId": 123,
    "role": "dictator",
    "money_sent": 5.0,
    "money_available": 10.0,
    "exchange_rate": 3.0,
    "payouts": 5.0
  }
}
```

## Game Configuration

Games are configured via JSON files in the `games/` directory with the format `game_{id}.json`:

```json
{
  "recovery_codes": ["recovery_code_123", "recovery_code_456"],
  "money_available": 10.0,
  "exchange_rate": 3.0
}
```

- First recovery code assigns dictator role
- Second recovery code assigns receiver role
- `money_available` and `exchange_rate` are optional (defaults: 10.0 and 3.0)

## Payout Calculation

- **Dictator payout**: `money_available - money_sent`
- **Receiver payout**: `money_sent × exchange_rate`

Example with defaults ($10 available, 3x exchange rate):

- If dictator sends $0: Dictator keeps $10, Receiver gets $0
- If dictator sends $5: Dictator keeps $5, Receiver gets $15
- If dictator sends $10: Dictator keeps $0, Receiver gets $30
