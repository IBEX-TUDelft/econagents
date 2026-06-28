import pytest

from econagents.runtime import PhaseEngine


def test_phase_engine_accepts_string_and_numeric_phase_ids():
    engine = PhaseEngine(continuous_phases={1, "market"})

    assert engine.is_continuous(1)
    assert engine.is_continuous("market")
    assert not engine.is_continuous("decision")


def test_phase_engine_uses_configured_delay_generator():
    engine = PhaseEngine(min_action_delay=2, max_action_delay=5, random_int=lambda low, high: high)

    assert engine.next_action_delay() == 5


def test_phase_engine_requires_delays_for_continuous_loop():
    engine = PhaseEngine()

    with pytest.raises(ValueError):
        engine.next_action_delay()
