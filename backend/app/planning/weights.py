"""Objective weight presets loaded from `app/config/weights.yaml` (ALGORITHMS §3.3)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

WEIGHTS_FILE = Path(__file__).resolve().parents[1] / "config" / "weights.yaml"
SCALE = 10  # CP-SAT needs integers: every coefficient is multiplied by this, then rounded


@dataclass(frozen=True)
class Weights:
    name: str
    coverage: float
    risk: float
    cost: float
    stability: float
    early: float

    def coverage_points(self, mission_weight: float) -> int:
        return round(SCALE * self.coverage * mission_weight)

    def risk_points(self, total_risk: float) -> int:
        return round(SCALE * self.risk * 1000 * total_risk)

    def cost_points(self, flight_min: float) -> int:
        return round(SCALE * self.cost * flight_min)

    def early_points(self, slot_index: int) -> int:
        return round(SCALE * self.early * slot_index)

    def stability_points(self) -> int:
        return round(SCALE * self.stability)


@lru_cache(maxsize=1)
def _load(path: str) -> dict[str, Weights]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {name: Weights(name=name, **vals) for name, vals in doc["presets"].items()}


def preset_names() -> list[str]:
    return sorted(_load(str(WEIGHTS_FILE)))


def get_weights(name: str) -> Weights:
    presets = _load(str(WEIGHTS_FILE))
    if name not in presets:
        raise KeyError(f"unknown weight preset {name!r}; choose one of {sorted(presets)}")
    return presets[name]
