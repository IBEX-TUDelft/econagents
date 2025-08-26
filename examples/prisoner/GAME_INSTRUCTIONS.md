# Repeated Prisoner's Dilemma Game Description

## Overview

The Prisoner's Dilemma is a classic game theory experiment. Players take on the roles of arrested criminals who must decide whether to cooperate (remain silent) or defect (testify against their partner). In the repeated version of the game, players engage in multiple rounds, allowing for the development of strategies based on previous interactions.

## Roles

The game defines a single role, "prisoner", for the players. During each phase, the prisoner must decide whether to cooperate or defect.

## Game Phases

The game consists of `n` rounds where each player must decide whether to cooperate or defect. The outcome of each round is determined by the combination of choices made by both players.

## Game Mechanics

### Choices

- **COOPERATE**: Remain silent (don't betray partner)
- **DEFECT**: Testify against partner

### Payoff Matrix

- Both cooperate: Each gets 3 points
- You cooperate, opponent defects: You get 0, opponent gets 5
- You defect, opponent cooperates: You get 5, opponent gets 0
- Both defect: Each gets 1 point
