from typing import Any, Optional


class AgentConfigurationManager:
    """
    Loads, saves, and updates agent configuration data.
    """

    def __init__(self, agent_config: Optional[dict[str, dict[str, Any]]] = None) -> None:
        """Initialize the agent configuration manager."""
        self.agent_config = agent_config or {}

    def define_agent(self, agent_id: str, role: str, **other_attrs: Any) -> None:
        """Add or update an agent config entry."""
        self.agent_config[agent_id] = {"agent_id": agent_id, "role": role, **other_attrs}

    def get_agent_config(self, agent_id: str) -> Optional[dict[str, Any]]:
        """Get configuration for a specific agent."""
        return self.agent_config.get(agent_id)

    def list_agents(self) -> list[str]:
        """Get list of all configured agent IDs."""
        return list(self.agent_config.keys())

    def get_agents_by_role(self, role: str) -> list[dict[str, Any]]:
        """Get configurations for all agents with a specific role."""
        return [config for config in self.agent_config.values() if config.get("role") == role]

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent's configuration."""
        if agent_id in self.agent_config:
            del self.agent_config[agent_id]
            return True
        return False

    def get_all_configs(self) -> dict[str, dict[str, Any]]:
        """Get all agent configurations."""
        return self.agent_config.copy()
