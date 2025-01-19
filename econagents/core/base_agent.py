from typing import Any, Optional

from econagents.core.phases import Phase


class BaseAgent:
    """
    A simple agent that can be extended for LLM-based or human-based logic.
    """

    def __init__(self, agent_id: Optional[str] = None, role: Optional[str] = None, **kwargs: Any) -> None:
        """Initialize a new agent."""
        self.agent_id = agent_id or "agent_1"
        self.role = role or "default"
        self.state: dict[str, Any] = kwargs.get("state", {})

    def act(self, phase: Phase, game_state: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Called each step of the game."""
        return None

    def record_vote(self, vote: Any) -> None:
        """Record a vote in the agent's state."""
        self.state["vote"] = vote

    def get_state(self) -> dict[str, Any]:
        """Get the current agent state."""
        return self.state.copy()
