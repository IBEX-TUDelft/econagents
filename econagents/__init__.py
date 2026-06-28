"""
econagents: A Python library that lets you use LLM agents in economic experiments.
"""

from econagents.adapters.config import YamlExperimentLoader
from econagents.adapters.protocol import IbexMessageCodec
from econagents.adapters.protocol import INTRODUCTION_PHASE, build_message, join_message, ready_message
from econagents.adapters.transport import JoinPayloadAuth, SimpleLoginPayloadAuth, WebSocketTransport
from econagents.domain import Action, AgentContext, Event, PhaseId, PlayerId
from econagents.domain.role import Role
from econagents.domain.state.fields import EventField
from econagents.domain.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.runtime import (
    Agent,
    GameRunner,
    HybridGameRunnerConfig,
    PhaseEngine,
    TurnBasedGameRunnerConfig,
    create_game_state,
)

try:
    from econagents._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

__all__: list[str] = [
    "Agent",
    "Action",
    "Role",
    "AgentContext",
    "YamlExperimentLoader",
    "Event",
    "EventField",
    "GameRunner",
    "GameState",
    "HybridGameRunnerConfig",
    "IbexMessageCodec",
    "INTRODUCTION_PHASE",
    "JoinPayloadAuth",
    "MetaInformation",
    "PhaseEngine",
    "PhaseId",
    "PlayerId",
    "PrivateInformation",
    "PublicInformation",
    "SimpleLoginPayloadAuth",
    "TurnBasedGameRunnerConfig",
    "WebSocketTransport",
    "build_message",
    "create_game_state",
    "join_message",
    "ready_message",
]
