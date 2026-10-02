import math
import random

import pytest

from app.sim import hazard


def test_failure_probability_is_monotone_in_hours_since_maintenance() -> None:
    probs = [hazard.failure_probability(h, 3.0, 100.0) for h in range(0, 301, 20)]
    assert probs == sorted(probs) and probs[-1] > probs[0]


def test_overdue_term_adds_hazard_beyond_pure_wear() -> None:
    interval, h, f = 100.0, 150.0, 3.0
    lam = hazard.SCALE_FACTOR * interval
    wear_only = ((h + f) / lam) ** hazard.WEIBULL_SHAPE - (h / lam) ** hazard.WEIBULL_SHAPE
    total = hazard.cumulative_hazard(h + f, interval) - hazard.cumulative_hazard(h, interval)
    assert total > wear_only


def test_zero_flight_hours_means_zero_failure_probability() -> None:
    assert hazard.failure_probability(80.0, 0.0, 100.0) == 0.0


def test_hand_checked_value_below_the_interval() -> None:
    # Below the interval H(h) = (h / lam) ** 1.8 with lam = SCALE_FACTOR * 100.
    # h=50, f=4:  p = 1 - exp(-((54/lam)**1.8 - (50/lam)**1.8))
    lam = hazard.SCALE_FACTOR * 100.0
    delta = (54 / lam) ** 1.8 - (50 / lam) ** 1.8
    assert hazard.failure_probability(50.0, 4.0, 100.0) == pytest.approx(
        1 - math.exp(-delta), abs=1e-9
    )


def test_hand_checked_value_crossing_the_interval_includes_the_overdue_term() -> None:
    # h=100, f=4 ends at 104 h, 4 h past the interval, so the overdue term (4/lam)**1.8 applies.
    lam = hazard.SCALE_FACTOR * 100.0
    delta = (104 / lam) ** 1.8 - (100 / lam) ** 1.8 + (4 / lam) ** 1.8
    assert hazard.failure_probability(100.0, 4.0, 100.0) == pytest.approx(
        1 - math.exp(-delta), abs=1e-9
    )


def test_history_is_reproducible() -> None:
    a, hours_a = hazard.simulate_history(random.Random("x"), 100.0, 200)
    b, hours_b = hazard.simulate_history(random.Random("x"), 100.0, 200)
    assert a == b and hours_a == hours_b


def test_faults_occur_and_reset_hours_since_maintenance() -> None:
    faults = 0
    for i in range(30):
        records, _ = hazard.simulate_history(random.Random(f"fleet{i}"), 100.0, 100)
        faults += sum(r.failure for r in records)
        for prev, cur in zip(records, records[1:], strict=False):
            if prev.failure:
                assert cur.hours_since_maintenance == 0.0
    assert faults > 0
