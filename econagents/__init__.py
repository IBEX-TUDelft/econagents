"""
econagents: A Python library that lets you use LLM agents in economic experiments.
"""

from econagents.config_parser import BaseConfigParser, BasicConfigParser
from econagents.core.agent_role import AgentRole
from econagents.core.game_runner import GameRunner, HybridGameRunnerConfig, TurnBasedGameRunnerConfig
from econagents.core.manager import AgentManager
from econagents.core.manager.phase import HybridPhaseManager, PhaseManager, TurnBasedPhaseManager
from econagents.core.protocol import INTRODUCTION_PHASE, build_message, join_message, ready_message
from econagents.core.state.fields import EventField
from econagents.core.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.core.transport import JoinPayloadAuth, SimpleLoginPayloadAuth, WebSocketTransport

try:
    from econagents._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

__all__: list[str] = [
    "AgentManager",
    "AgentRole",
    "BaseConfigParser",
    "BasicConfigParser",
    "EventField",
    "GameRunner",
    "GameState",
    "HybridGameRunnerConfig",
    "HybridPhaseManager",
    "INTRODUCTION_PHASE",
    "JoinPayloadAuth",
    "MetaInformation",
    "PhaseManager",
    "PrivateInformation",
    "PublicInformation",
    "SimpleLoginPayloadAuth",
    "TurnBasedGameRunnerConfig",
    "TurnBasedPhaseManager",
    "WebSocketTransport",
    "build_message",
    "join_message",
    "ready_message",
]
