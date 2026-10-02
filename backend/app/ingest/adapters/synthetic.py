"""Synthetic sources.

`SyntheticAdapter` hands the generator's records over as the primary feed.
`SecondarySyntheticAdapter` is a second, noisier synthetic feed built *from the same scenario* so
that fusion has real disagreements to resolve (BUILD_PLAN Phase 2). It is synthetic by
construction: its disagreements are random perturbations drawn from the scenario seed, not a model
of any real second system. Same seed -> same feed.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import BaseModel

from app.ingest.models import DEFAULT_MAX_AGE_MIN, FUSED_GROUPS, RecordBatch
from app.models.entities import Provenance
from app.models.scenario import GROUPS, ScenarioFile
from app.sim.geo import offset_km

SECONDARY_SOURCE = "SYNTHETIC_SECONDARY"

Perturb = Callable[[random.Random, Any, dict[str, Any]], Any]


class SyntheticAdapter:
    """The scenario's own records, unchanged, as the primary source."""

    name = "synthetic"

    def __init__(self, scenario: ScenarioFile) -> None:
        self._scenario = scenario

    def fetch(self) -> RecordBatch:
        return RecordBatch(
            adapter=self.name,
            records={g: list(getattr(self._scenario, g)) for g in FUSED_GROUPS},
        )


# ------------------------------------------------------------------------------ perturbations
def _signed(rng: random.Random, lo: float, hi: float) -> float:
    return rng.choice((-1, 1)) * rng.uniform(lo, hi)


def _add(lo: float, hi: float, floor: float, ceil: float, digits: int | None) -> Perturb:
    def apply(rng: random.Random, value: Any, _: dict[str, Any]) -> Any:
        new = min(ceil, max(floor, value + _signed(rng, lo, hi)))
        return round(new, digits) if digits is not None else int(round(new))

    return apply


def _scale(lo: float, hi: float, digits: int | None) -> Perturb:
    def apply(rng: random.Random, value: Any, _: dict[str, Any]) -> Any:
        new = value * rng.uniform(lo, hi)
        return round(new, digits) if digits is not None else int(round(new))

    return apply


def _swap(table: dict[str, str]) -> Perturb:
    def apply(_: random.Random, value: Any, __: dict[str, Any]) -> Any:
        return table.get(value, value)

    return apply


def _shift_center(rng: random.Random, value: Any, _: dict[str, Any]) -> Any:
    east, north = _signed(rng, 5, 30), _signed(rng, 5, 30)  # km
    lat, lon = offset_km(value["lat"], value["lon"], east, north)
    return {"lat": round(min(90.0, max(-90.0, lat)), 4), "lon": round(lon, 4)}


NOISE: dict[str, dict[str, Perturb]] = {
    "aircraft": {
        "status": _swap({
            "SERVICEABLE": "DEGRADED", "DEGRADED": "SERVICEABLE",
            "UNSERVICEABLE": "SERVICEABLE", "IN_MAINTENANCE": "SERVICEABLE",
        }),
        "fuel_state_pct": _add(8, 25, 0, 100, 1),
        "hours_since_maintenance": _add(2, 10, 0, 1e9, 1),
        "available_from_min": _add(30, 180, 0, 1e9, None),
    },
    "crew": {
        "status": _swap({
            "AVAILABLE": "ON_REST", "ON_REST": "AVAILABLE", "SICK": "AVAILABLE",
            "ON_DUTY": "AVAILABLE",
        }),
        "duty_minutes_last_24h": _add(60, 240, 0, 1e9, None),
    },
    "weapon_stocks": {"qty_available": _scale(0.4, 0.8, None)},
    "threats": {
        "severity": _add(0.15, 0.35, 0.0, 1.0, 2),
        "radius_km": _scale(1.2, 1.5, 1),
        "center": _shift_center,
    },
    # Mission requests come from one authoritative requester in this prototype: no noisy copy.
    "missions": {},
    "airspace": {"active_to_min": _add(60, 180, 0, 1e9, None)},
    "weather": {
        "visibility_km": _scale(0.4, 0.7, 1),
        "ceiling_ft": _scale(0.4, 0.7, None),
        "wind_kmh": _scale(1.3, 1.8, 1),
    },
}


@dataclass(frozen=True)
class SecondaryParams:
    """Placeholders; none of these describe a real system."""

    coverage: float = 0.5  # share of records the second feed reports at all
    field_noise_rate: float = 0.35  # share of noisy fields it gets "wrong" per reported record
    stale_fraction: float = 0.25  # share of reported records whose timestamp is already stale
    confidence_range: tuple[float, float] = (0.5, 0.9)
    fresh_age_range_min: tuple[int, int] = (0, 30)


class SecondarySyntheticAdapter:
    name = "synthetic_secondary"

    def __init__(self, scenario: ScenarioFile, params: SecondaryParams | None = None) -> None:
        self._scenario = scenario
        self._params = params or SecondaryParams()

    def fetch(self) -> RecordBatch:
        p = self._params
        t0 = self._scenario.scenario.t0
        rng = random.Random(f"airpower:{self._scenario.scenario.seed}:secondary-feed")
        out: dict[str, list[BaseModel]] = {}
        for group in FUSED_GROUPS:
            rows: list[BaseModel] = []
            for entity in getattr(self._scenario, group):
                if rng.random() >= p.coverage:
                    continue
                rec = entity.model_dump(mode="json")
                for fieldname, perturb in NOISE[group].items():
                    if rng.random() < p.field_noise_rate:
                        rec[fieldname] = perturb(rng, rec[fieldname], rec)
                limit = int(DEFAULT_MAX_AGE_MIN[group])
                age = (
                    rng.randint(limit + 10, limit + 240)  # past the stale threshold
                    if rng.random() < p.stale_fraction
                    else rng.randint(*p.fresh_age_range_min)
                )
                rec["provenance"] = Provenance(
                    source=SECONDARY_SOURCE, observed_at=t0 - timedelta(minutes=age),
                    ingested_at=t0, confidence=round(rng.uniform(*p.confidence_range), 2),
                    data_label="synthetic",
                ).model_dump(mode="json")
                rows.append(GROUPS[group].model_validate(rec))
            out[group] = rows
        return RecordBatch(adapter=self.name, records=out)
