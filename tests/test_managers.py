"""
Tests for manager classes.
"""

import pytest

from econagents.core.phases import Phase
from econagents.managers.agent_manager import AgentManager
from econagents.managers.game_manager import GameManager


def test_game_manager_init():
    """Test GameManager initialization."""
    game_spec = {"name": "TestGame", "phases": ["instructions", "voting", "finished"], "roles": ["player1", "player2"]}
    gm = GameManager(game_spec)
    assert gm.game_spec["name"] == "TestGame"
    assert len(gm.game.phases) == 3


def test_game_manager_phases():
    """Test GameManager phase transitions."""
    game_spec = {"name": "TestGame", "phases": ["instructions", "voting", "finished"], "roles": ["player1", "player2"]}
    gm = GameManager(game_spec)

    gm.start_game()
    assert gm.get_current_phase() == Phase.INSTRUCTIONS
    assert not gm.is_finished()

    gm.next_phase()
    assert gm.get_current_phase() == Phase.VOTING

    gm.next_phase()
    assert gm.get_current_phase() == Phase.FINISHED
    assert gm.is_finished()


def test_agent_manager():
    """Test AgentManager functionality."""
    agent_configs = [{"agent_id": "agent1", "role": "player1"}, {"agent_id": "agent2", "role": "player2"}]
    am = AgentManager(agent_configs)

    assert len(am.agents) == 2
    assert am.agents[0].agent_id == "agent1"
    assert am.agents[1].role == "player2"


def test_agent_manager_step():
    """Test AgentManager step function."""
    agent_configs = [{"agent_id": "agent1", "role": "player1"}, {"agent_id": "agent2", "role": "player2"}]
    am = AgentManager(agent_configs)

    game_state = {"phase": Phase.VOTING, "current_votes": {}}
    actions = am.step(Phase.VOTING, game_state)

    # By default, agents return None for actions
    assert len(actions) == 0


def test_agent_manager_get_states():
    """Test AgentManager state retrieval."""
    agent_configs = [{"agent_id": "agent1", "role": "player1"}, {"agent_id": "agent2", "role": "player2"}]
    am = AgentManager(agent_configs)

    # Test getting individual agent state
    state = am.get_agent_state("agent1")
    assert state == {}  # Default empty state

    # Test getting all states
    all_states = am.get_all_states()
    assert len(all_states) == 2
    assert "agent1" in all_states
    assert "agent2" in all_states
