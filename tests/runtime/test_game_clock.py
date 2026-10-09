import asyncio
import logging

import pytest

from econagents.runtime.game_clock import GameClock

LOGGER = logging.getLogger("test_game_clock")


def make_clock(gameplay: float | None = None, pre_game: float | None = None) -> GameClock:
    return GameClock(
        max_game_duration=gameplay,
        max_pre_game_duration=pre_game,
        pre_game_phases={"introduction"},
        logger=LOGGER,
    )


async def timeout_after(clock: GameClock, limit: float = 2.0) -> tuple[str, float]:
    loop = asyncio.get_running_loop()
    start = loop.time()
    reason = await asyncio.wait_for(clock.wait_for_timeout(), limit)
    return reason, loop.time() - start


@pytest.mark.asyncio
async def test_budgets_of_zero_or_none_disable_the_clock():
    assert not make_clock().enabled
    assert not make_clock(gameplay=0, pre_game=-1).enabled
    assert make_clock(pre_game=1).enabled


@pytest.mark.asyncio
async def test_without_phase_reports_gameplay_counts_from_start():
    reason, elapsed = await timeout_after(make_clock(gameplay=0.2))
    assert reason == "gameplay"
    assert 0.15 <= elapsed <= 0.4


@pytest.mark.asyncio
async def test_pre_game_budget_counts_the_wait_before_the_first_phase_report():
    clock = make_clock(gameplay=1.0, pre_game=0.3)

    async def report_introduction() -> None:
        await asyncio.sleep(0.1)
        clock.observe(1, "introduction")

    asyncio.create_task(report_introduction())
    reason, elapsed = await timeout_after(clock)
    assert reason == "pre_game"
    assert 0.25 <= elapsed <= 0.5


@pytest.mark.asyncio
async def test_first_gameplay_report_discards_the_provisional_from_start_time():
    clock = make_clock(gameplay=0.3)

    async def report_gameplay() -> None:
        await asyncio.sleep(0.2)
        clock.observe(1, "presentation")

    asyncio.create_task(report_gameplay())
    reason, elapsed = await timeout_after(clock)
    assert reason == "gameplay"
    assert 0.45 <= elapsed <= 0.7
    assert clock.gameplay_start_phase == "presentation"


@pytest.mark.asyncio
async def test_repeated_occurrences_do_not_move_the_game_back(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    clock = make_clock(gameplay=10)
    clock.observe(1, "introduction")
    clock.observe(1, "presentation")
    clock.observe(1, "introduction")
    clock.observe(1, "market")
    clock.observe(1, "presentation")

    assert clock.in_gameplay and clock.phase == "market"
    assert [r.getMessage() for r in caplog.records if "Gameplay started" in r.getMessage()] == [
        "Gameplay started (phase=presentation, round=1); gameplay budget 10s"
    ]

    clock.observe(2, "introduction")
    assert not clock.in_gameplay
    assert any("Gameplay clock paused (phase=introduction, round=2)" in r.getMessage() for r in caplog.records)
    clock.observe(2, "presentation")
    assert any("Gameplay clock resumed (phase=presentation, round=2)" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_no_budget_in_force_waits_until_a_phase_change():
    clock = make_clock(gameplay=0.2)
    clock.observe(1, "introduction")

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(clock.wait_for_timeout(), 0.4)
