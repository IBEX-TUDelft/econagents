from typing import Any, Optional

from econagents.core.base_agent import BaseAgent
from econagents.core.phases import Phase


class AgentManager:
    """
    Manages a collection of Agent objects: their creation, updates, and retrieving actions during each phase.
    """

    def __init__(self, agent_configs: Optional[list[dict[str, Any]]] = None) -> None:
        """Initialize the agent manager."""
        self.agents: list[BaseAgent] = []
        if agent_configs:
            for cfg in agent_configs:
                agent = BaseAgent(**cfg)
                self.agents.append(agent)

    def add_agent(self, agent: BaseAgent) -> None:
        """Add a new agent to the manager."""
        self.agents.append(agent)

    def step(self, phase: Phase, game_state: dict[str, Any]) -> dict[str, Any]:
        """Give all agents a chance to act or respond in the current phase."""
        actions: dict[str, Any] = {}
        for agent in self.agents:
            action = agent.act(phase, game_state)
            if action is not None:
                actions[agent.agent_id] = action
        return actions

    def get_agent_state(self, agent_id: str) -> Optional[dict[str, Any]]:
        """Return the state of a specific agent."""
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent.get_state()
        return None

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Get states of all agents."""
        return {agent.agent_id: agent.get_state() for agent in self.agents}

    def get_agents_by_role(self, role: str) -> list[BaseAgent]:
        """Get all agents with a specific role."""
        return [agent for agent in self.agents if agent.role == role]
