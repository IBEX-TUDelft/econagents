"""
econagents: A Python library that lets you use LLM agents in economic experiments.
"""

from econagents.config_parser import BaseConfigParser, BasicConfigParser
from econagents.core.agent_role import AgentRole
from econagents.core.game_runner import GameRunner, HybridGameRunnerConfig, TurnBasedGameRunnerConfig
from econagents.core.manager import AgentManager
from econagents.core.manager.phase import HybridPhaseManager, PhaseManager, TurnBasedPhaseManager
from econagents.core.state.fields import EventField
from econagents.core.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.core.transport import WebSocketTransport

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
    "MetaInformation",
    "PhaseManager",
    "PrivateInformation",
    "PublicInformation",
    "TurnBasedGameRunnerConfig",
    "TurnBasedPhaseManager",
    "WebSocketTransport",
]
