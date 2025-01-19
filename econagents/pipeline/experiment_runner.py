from typing import Any, Callable, Optional

from econagents.managers.agent_manager import AgentManager
from econagents.managers.game_manager import GameManager


class ExperimentRunner:
    """
    Orchestrates the flow of the experiment, using a GameManager and AgentManager.
    """

    def __init__(
        self,
        game_manager: GameManager,
        agent_manager: AgentManager,
        on_phase_complete: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        """Initialize the experiment runner."""
        self.game_manager = game_manager
        self.agent_manager = agent_manager
        self.on_phase_complete = on_phase_complete
        self.results: dict[str, Any] = {}

    def run_experiment(self) -> dict[str, Any]:
        """Run the complete experiment."""
        self.game_manager.start_game()

        while not self.game_manager.is_finished():
            self.step()

        return self.finalize()

    def step(self) -> dict[str, Any]:
        """Execute a single step of the experiment."""
        phase = self.game_manager.get_current_phase()
        if not phase:
            raise ValueError("No current phase")

        game_state = self.game_manager.get_state()

        actions = self.agent_manager.step(phase, game_state)

        step_results = {"phase": phase, "game_state": game_state, "actions": actions}

        if self.on_phase_complete:
            self.on_phase_complete(step_results)

        self.game_manager.next_phase()

        return step_results

    def finalize(self) -> dict[str, Any]:
        """Finalize the experiment and collect results."""
        game_results = self.game_manager.finalize_game()
        agent_states = self.agent_manager.get_all_states()

        self.results = {
            "game_results": game_results,
            "agent_states": agent_states,
            "final_state": self.game_manager.get_state(),
        }

        return self.results

    def get_results(self) -> dict[str, Any]:
        """Get current experiment results."""
        return self.results
