import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from econagents.core.game_runner import GameRunner, GameRunnerConfig
from econagents.core.manager.phase import PhaseManager


# TODO: We might want to remove this mock
class MockAgentManager(PhaseManager):
    def __init__(self, url=None, logger=None, auth_mechanism_kwargs=None, name="MockAgent", hang_duration=10.0):
        super().__init__(url=url, logger=logger or logging.getLogger(name), auth_mechanism_kwargs=auth_mechanism_kwargs)
        self.name = name
        self.start_called_event = asyncio.Event()
        self.stop_called_event = asyncio.Event()
        self.start_should_hang = True
        self.hang_duration = hang_duration
        self._start_task = None

    async def start(self):
        self.logger.info(f"Agent '{self.name}': Manager start called.")
        self.running = True
        self.start_called_event.set()

        if self.start_should_hang:
            self.logger.info(f"Agent '{self.name}': Manager will simulate work for up to {self.hang_duration}s.")
            try:
                self._start_task = asyncio.create_task(asyncio.sleep(self.hang_duration))
                await self._start_task
                self.logger.info(f"Agent '{self.name}': Manager finished simulated work naturally.")
                self.running = False  # Work is done
            except asyncio.CancelledError:
                self.logger.info(f"Agent '{self.name}': Manager start task was cancelled.")
                if self.running:
                    await self.stop()
                raise
            finally:
                self._start_task = None
        else:
            self.logger.info(f"Agent '{self.name}': Manager start finished (not hanging).")
            self.running = False
        self.logger.info(f"Agent '{self.name}': Manager start method exiting. Running: {self.running}")

    async def stop(self):
        self.logger.info(f"Agent '{self.name}': Manager stop called.")
        self.running = False
        self.stop_called_event.set()
        if self._start_task and not self._start_task.done():
            self._start_task.cancel()
            try:
                await self._start_task
            except asyncio.CancelledError:
                self.logger.info(f"Agent '{self.name}': Manager's internal start task cancelled during stop.")
        if self.transport:
            if hasattr(self.transport, "stop") and asyncio.iscoroutinefunction(self.transport.stop):
                await self.transport.stop()
            elif hasattr(self.transport, "_running"):
                self.transport._running = False

    async def execute_phase_action(self, phase: int):
        self.logger.info(f"Agent '{self.name}': Executing action for phase {phase}")
        await asyncio.sleep(0.01)


@pytest.fixture
def base_config(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    return GameRunnerConfig(
        hostname="localhost",
        port=1234,
        path="ws",
        game_id=1,
        logs_dir=logs_dir,
        prompts_dir=prompts_dir,
        log_level=logging.DEBUG,  # Use DEBUG for more verbose test logs
    )


@pytest.mark.asyncio
async def test_game_times_out_and_stops_agents(base_config, caplog):
    """Test that the game stops agents when max_game_duration is reached."""
    caplog.set_level(logging.INFO)
    timeout_duration = 0.1  # seconds for quick test
    base_config.max_game_duration = timeout_duration

    agent1 = MockAgentManager(name="Agent1_Timeout", hang_duration=5)  # Will hang longer than timeout
    agent2 = MockAgentManager(name="Agent2_Timeout", hang_duration=5)

    runner = GameRunner(config=base_config, agents=[agent1, agent2])

    agent1.transport = MagicMock()
    agent1.transport.stop = AsyncMock()
    agent2.transport = MagicMock()
    agent2.transport.stop = AsyncMock()

    await asyncio.wait_for(runner.run_game(), timeout=timeout_duration * 10)

    assert agent1.start_called_event.is_set(), "Agent1 start was not called"
    assert agent2.start_called_event.is_set(), "Agent2 start was not called"

    try:
        await asyncio.wait_for(agent1.stop_called_event.wait(), timeout=1)
        await asyncio.wait_for(agent2.stop_called_event.wait(), timeout=1)
    except asyncio.TimeoutError:
        pytest.fail("Agents stop methods not called within expected time after timeout.")

    assert agent1.stop_called_event.is_set(), "Agent1 stop was not called after timeout"
    assert not agent1.running, "Agent1 should not be running after timeout"
    assert agent2.stop_called_event.is_set(), "Agent2 stop was not called after timeout"
    assert not agent2.running, "Agent2 should not be running after timeout"

    assert any(f"Game {base_config.game_id} reached maximum duration" in record.message for record in caplog.records)
    assert any("Timeout: Stopping agent 1" in record.message for record in caplog.records)
    assert any("Timeout: Stopping agent 2" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_game_finishes_before_timeout(base_config, caplog):
    """Test that the timeout watchdog is cancelled if the game finishes early."""
    caplog.set_level(logging.DEBUG)
    base_config.max_game_duration = 5

    agent1 = MockAgentManager(name="agent1", hang_duration=0.1)
    agent2 = MockAgentManager(name="agent2", hang_duration=0.1)

    runner = GameRunner(config=base_config, agents=[agent1, agent2])

    agent1.transport = MagicMock()
    agent1.transport.stop = AsyncMock()
    agent2.transport = MagicMock()
    agent2.transport.stop = AsyncMock()

    await asyncio.wait_for(runner.run_game(), timeout=2)

    assert agent1.start_called_event.is_set()
    assert agent2.start_called_event.is_set()
    await asyncio.sleep(0.1)
    assert not agent1.running, "agent1 should not be running after game finishes"
    assert not agent2.running, "agent2 should not be running after game finishes"

    assert any(
        f"Game {base_config.game_id} finished or errored before timeout. Cancelling timeout watchdog." in record.message
        for record in caplog.records
    )
    assert any(
        f"Timeout watchdog for game {base_config.game_id} successfully cancelled in finally block." in record.message
        for record in caplog.records
    )
    assert not any(
        f"Game {base_config.game_id} reached maximum duration" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_game_timeout_disabled_with_zero_duration(base_config, caplog):
    """Test that timeout is disabled if max_game_duration is 0."""
    caplog.set_level(logging.INFO)
    base_config.max_game_duration = 0

    agent1 = MockAgentManager(name="Agent1_NoTimeout", hang_duration=0.1)
    runner = GameRunner(config=base_config, agents=[agent1])
    agent1.transport = MagicMock()
    agent1.transport.stop = AsyncMock()

    await asyncio.wait_for(runner.run_game(), timeout=1)

    assert agent1.start_called_event.is_set()
    await asyncio.sleep(0.1)
    assert not agent1.running

    assert not any(
        "TimeoutWatchdog" in task.get_name() for task in asyncio.all_tasks() if "TimeoutWatchdog" in task.get_name()
    )
    assert not any(
        f"Game {base_config.game_id} reached maximum duration" in record.message for record in caplog.records
    )
    assert not any(
        "Cancelling timeout watchdog" in record.message for record in caplog.records
    )  # No watchdog to cancel


@pytest.mark.asyncio
async def test_game_timeout_disabled_with_negative_duration(base_config, caplog):
    """Test that timeout is disabled if max_game_duration is negative."""
    caplog.set_level(logging.INFO)
    base_config.max_game_duration = -100

    agent1 = MockAgentManager(name="Agent1_NegTimeout", hang_duration=0.1)
    runner = GameRunner(config=base_config, agents=[agent1])
    agent1.transport = MagicMock()
    agent1.transport.stop = AsyncMock()

    await asyncio.wait_for(runner.run_game(), timeout=1)

    assert agent1.start_called_event.is_set()
    await asyncio.sleep(0.1)
    assert not agent1.running

    assert not any(
        "TimeoutWatchdog" in task.get_name() for task in asyncio.all_tasks() if "TimeoutWatchdog" in task.get_name()
    )
    assert not any(
        f"Game {base_config.game_id} reached maximum duration" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_agent_start_raises_exception(base_config, caplog):
    """Test GameRunner behavior when an agent's start() method raises an exception."""
    caplog.set_level(logging.ERROR)
    base_config.max_game_duration = 10

    failing_agent = MockAgentManager(name="FailingAgent", hang_duration=0.1)
    failing_agent.start = AsyncMock(side_effect=ValueError("Agent failed to start"))
    failing_agent.stop = AsyncMock()

    runner = GameRunner(config=base_config, agents=[failing_agent])
    failing_agent.transport = MagicMock()
    failing_agent.transport.stop = AsyncMock()

    await runner.run_game()

    failing_agent.start.assert_called_once()

    assert any(
        "Agent task AgentTask-1-1 failed with: Agent failed to start" in record.message for record in caplog.records
    )

    assert not failing_agent.running, "Failed agent should not be running"
