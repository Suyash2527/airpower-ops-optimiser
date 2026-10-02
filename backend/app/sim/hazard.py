"""Ground-truth failure hazard for the SYNTHETIC maintenance history.

This is the process the serviceability model (Phase 7) is later asked to recover. It is synthetic
by construction; nothing here is calibrated to any real fleet (HONESTY.md).

Hazard model (documented, placeholder parameters)
- Let h = flight hours since last maintenance and L = the type's maintenance interval (hours).
- Cumulative hazard:   H(h) = (h / lam)^k  +  beta * (max(0, h - L) / lam)^k
    * Weibull wear-out term with shape k = 1.8 > 1 (hazard rises with h) and scale
      lam = 1.2 * L. Placeholder: gave about 1.2% faults per aircraft-day in a script run of
      12,000 simulated aircraft-days, enough signal for a model to learn from.
    * Extra "overdue" term: once h exceeds L the hazard grows faster (beta = 1.0).
- A day with `f` flight hours starting at hours-since-maintenance `h` fails with probability
      p = 1 - exp(-(H(h + f) - H(h)))
  which is non-decreasing in h for fixed f because H is convex (k > 1).
- A fault resets h to 0 (repair includes maintenance). Scheduled maintenance is taken with
  probability 0.6 on any day with h >= L, so aircraft are sometimes overdue.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

WEIBULL_SHAPE = 1.8
SCALE_FACTOR = 1.2  # lam = SCALE_FACTOR * interval
OVERDUE_BETA = 1.0
MAINTENANCE_TAKEUP_PROB = 0.6
FLY_DAY_PROB = 0.75
FLIGHT_HOURS_RANGE = (1.0, 4.5)
RECENT_WINDOW_DAYS = 7


def cumulative_hazard(hours_since: float, interval_h: float) -> float:
    lam = SCALE_FACTOR * interval_h
    wear = (hours_since / lam) ** WEIBULL_SHAPE
    overdue = OVERDUE_BETA * (max(0.0, hours_since - interval_h) / lam) ** WEIBULL_SHAPE
    return wear + overdue


def failure_probability(hours_since: float, flight_hours: float, interval_h: float) -> float:
    delta = cumulative_hazard(hours_since + flight_hours, interval_h) - cumulative_hazard(
        hours_since, interval_h
    )
    return 1.0 - math.exp(-delta)


@dataclass(frozen=True)
class DayRecord:
    day_offset: int
    hours_since_maintenance: float
    flight_hours: float
    recent_fault_count: int
    failure: bool
    event: str  # "NONE" | "FAULT" | "SCHEDULED_MAINTENANCE"


def simulate_history(
    rng: random.Random, interval_h: float, days: int
) -> tuple[list[DayRecord], float]:
    """Simulate `days` days before t0; returns the records and hours-since-maintenance at t0."""
    hours = rng.uniform(0.0, interval_h)
    records: list[DayRecord] = []
    for day in range(-days, 0):
        flown = rng.uniform(*FLIGHT_HOURS_RANGE) if rng.random() < FLY_DAY_PROB else 0.0
        recent = sum(1 for r in records[-RECENT_WINDOW_DAYS:] if r.failure)
        failed = rng.random() < failure_probability(hours, flown, interval_h)
        event = "FAULT" if failed else "NONE"
        records.append(
            DayRecord(day, round(hours, 2), round(flown, 2), recent, failed, event)
        )
        hours += flown
        if failed:
            hours = 0.0
        elif hours >= interval_h and rng.random() < MAINTENANCE_TAKEUP_PROB:
            records[-1] = DayRecord(
                day, round(records[-1].hours_since_maintenance, 2), records[-1].flight_hours,
                recent, False, "SCHEDULED_MAINTENANCE",
            )
            hours = 0.0
    return records, round(hours, 2)
