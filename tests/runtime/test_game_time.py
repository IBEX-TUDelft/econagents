"""``GameTime``: the game's time from ``meta.gametime``, standing still while the game is paused."""

from econagents.runtime import GameTime


class LocalClock:
    def __init__(self, now: float = 50_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_nothing_is_known_before_a_message_carries_a_game_time():
    game_time = GameTime(local_now=LocalClock())
    game_time.observe(None)
    game_time.observe("12")
    game_time.observe(True)
    game_time.observe(float("nan"))

    assert game_time.offset is None
    assert game_time.now() is None
    assert game_time.remaining(1000) is None
    assert game_time.local_time_of(1000) is None


def test_time_flows_with_the_local_clock():
    clock = LocalClock()
    game_time = GameTime(local_now=clock)
    game_time.observe(43_000)
    clock.now += 2_000

    assert game_time.now() == 45_000
    assert game_time.remaining(103_000) == 58_000
    assert game_time.local_time_of(103_000) == clock.now + 58_000
    assert game_time.remaining(1_000) == 0


def test_the_least_delayed_of_the_last_messages_sets_the_estimate():
    clock = LocalClock()
    game_time = GameTime(local_now=clock, samples=2)
    game_time.observe(1_000, received_at=50_300)
    game_time.observe(2_000, received_at=51_020)
    assert game_time.offset == 49_020

    game_time.observe(3_000, received_at=52_500)
    game_time.observe(4_000, received_at=53_400)
    assert game_time.offset == 49_400, "only the last two pairs count"


def test_a_countdown_stands_still_during_a_pause_and_goes_on_from_the_same_value():
    clock = LocalClock()
    game_time = GameTime(local_now=clock)
    game_time.observe(10_000)
    clock.now += 5_000
    assert game_time.remaining(60_000) == 45_000

    game_time.pause(15_000)
    clock.now += 600_000
    game_time.observe(15_000)
    assert game_time.paused
    assert game_time.now() == 15_000
    assert game_time.remaining(60_000) == 45_000

    game_time.resume(15_000)
    assert not game_time.paused
    assert game_time.remaining(60_000) == 45_000
    clock.now += 1_000
    assert game_time.remaining(60_000) == 44_000


def test_pause_and_resume_without_a_game_time_use_the_estimate():
    clock = LocalClock()
    game_time = GameTime(local_now=clock)
    game_time.observe(10_000)
    clock.now += 5_000

    game_time.pause()
    clock.now += 30_000
    assert game_time.now() == 15_000

    game_time.resume()
    clock.now += 2_000
    assert game_time.now() == 17_000


def test_a_pause_before_any_game_time_is_known():
    clock = LocalClock()
    game_time = GameTime(local_now=clock)
    game_time.pause()
    assert game_time.paused
    assert game_time.now() is None

    game_time.resume(7_000)
    clock.now += 500
    assert game_time.now() == 7_500


def test_repeated_pause_and_resume_change_nothing():
    clock = LocalClock()
    game_time = GameTime(local_now=clock)
    game_time.observe(10_000)
    game_time.resume(99_000)
    assert game_time.now() == 10_000

    game_time.pause(10_000)
    game_time.pause(99_000)
    assert game_time.now() == 10_000
