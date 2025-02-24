"""
econagents: A Python library for setting up and running economic experiments with LLMs or human subjects.
"""

from econagents.core.agent import HybridAgent, TurnBasedAgent, MarketAgent
from econagents.core.agent_manager import AgentManager
from econagents.core.events import Message
from econagents.core.state.game import GameState
from econagents.core.state.market import MarketState

# Don't manually change, let poetry-dynamic-versioning handle it.
__version__ = "0.1.0"

__all__: list[str] = ["HybridAgent", "AgentManager", "Message", "GameState", "TurnBasedAgent", "MarketAgent"]
