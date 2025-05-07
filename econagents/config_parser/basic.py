import json
from typing import Any, Dict, Optional

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import PhaseManager
from econagents.core.state.game import GameState
from econagents.config_parser.base import BaseConfigParser


class BasicConfigParser(BaseConfigParser):
    """
    Basic configuration parser that adds a custom event handler for sending a
    player-is-ready message when it receives a certain message from the server.
    """

    def create_manager(
        self, game_id: int, state: GameState, agent_role: Optional[AgentRole], auth_kwargs: Dict[str, Any]
    ) -> PhaseManager:
        """
        Create a manager instance with a custom event handler for the assign-name event.

        Args:
            game_id: The game ID
            state: The game state instance
            agent_role: The agent role instance
            auth_kwargs: Authentication mechanism keyword arguments

        Returns:
            A PhaseManager instance with custom event handlers
        """
        # Get the base manager
        manager = super().create_manager(game_id=game_id, state=state, agent_role=agent_role, auth_kwargs=auth_kwargs)

        # Register custom event handler for assign-name event
        async def handle_name_assignment(message: Message) -> None:
            """Handle the name assignment event."""
            # Include the agent ID from auth_kwargs in the ready message
            agent_id = auth_kwargs.get("agent_id")
            ready_msg = {"gameId": game_id, "type": "player-is-ready", "agentId": agent_id}
            await manager.send_message(json.dumps(ready_msg))

        manager.register_event_handler("assign-name", handle_name_assignment)

        return manager
