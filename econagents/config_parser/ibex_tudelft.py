import json
import importlib
from typing import Any, Dict, Optional, Type

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import PhaseManager
from econagents.core.state.game import GameState
from econagents.config_parser.basic import BasicConfigParser


class IbexTudelftConfigParser(BasicConfigParser):
    """
    IBEX-TUDelft configuration parser that extends the BasicConfigParser
    and adds role assignment functionality.
    """

    def __init__(self, config_path: str, role_module_path: Optional[str] = None):
        """
        Initialize the IBEX-TUDelft config parser.

        Args:
            config_path: Path to the YAML configuration file
            role_module_path: Optional module path where role classes are defined
        """
        super().__init__(config_path)
        self.role_module_path = role_module_path
        self._role_classes: Dict[int, Type[AgentRole]] = {}

    def register_role_class(self, role_id: int, role_class: Type[AgentRole]) -> None:
        """
        Register a role class for a specific role ID.

        Args:
            role_id: The role ID
            role_class: The agent role class
        """
        self._role_classes[role_id] = role_class

    def create_manager(
        self, game_id: int, state: GameState, agent_role: Optional[AgentRole], auth_kwargs: Dict[str, Any]
    ) -> PhaseManager:
        """
        Create a manager instance with custom event handlers for assign-name and assign-role events.
        The manager won't have a role initially, but will be assigned one during the game.

        Args:
            game_id: The game ID
            state: The game state instance
            agent_role: The agent role instance (may be None)
            auth_kwargs: Authentication mechanism keyword arguments

        Returns:
            A PhaseManager instance with custom event handlers
        """
        # Get the manager with the name assignment handler
        manager = super().create_manager(
            game_id=game_id,
            state=state,
            agent_role=agent_role if agent_role is not None else AgentRole(),
            auth_kwargs=auth_kwargs,
        )

        # Register custom event handler for assign-role event
        async def handle_role_assignment(message: Message) -> None:
            """Handle the role assignment event."""
            role_id = int(message.data.get("role", 0))
            manager.logger.info(f"Role assigned: {role_id}")

            # Initialize the agent based on the assigned role
            self._initialize_agent(manager, role_id)

        manager.register_event_handler("assign-role", handle_role_assignment)

        return manager

    def _initialize_agent(self, manager: PhaseManager, role_id: int) -> None:
        """
        Initialize the agent instance based on the assigned role.

        Args:
            manager: The phase manager instance
            role_id: The role ID
        """
        # Check if we have a registered role class for this role ID
        if role_id in self._role_classes:
            role_class = self._role_classes[role_id]
            manager.agent_role = role_class()
            manager.agent_role.logger = manager.logger
        # If role_module_path is provided, try to import role classes
        elif self.role_module_path:
            try:
                module = importlib.import_module(self.role_module_path)
                # Look for role classes in the module
                role_classes = {
                    name: cls
                    for name, cls in module.__dict__.items()
                    if isinstance(cls, type) and issubclass(cls, AgentRole) and hasattr(cls, "role")
                }

                # Find matching role class
                for name, cls in role_classes.items():
                    if getattr(cls, "role", None) == role_id:
                        manager.agent_role = cls()
                        manager.agent_role.logger = manager.logger
                        return

                manager.logger.error(f"No role class found for role ID {role_id}")
                raise ValueError(f"No role class found for role ID {role_id}")
            except (ImportError, AttributeError) as e:
                manager.logger.error(f"Error importing role classes: {e}")
                raise ValueError(f"Error importing role classes: {e}")
        else:
            manager.logger.error("Invalid role assigned; cannot initialize agent.")
            raise ValueError("Invalid role for agent initialization.")
