"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DATA_LABEL = "synthetic"


@dataclass(frozen=True)
class Settings:
    database_url: str
    scenario_dir: Path
    default_seed: int
    solver_time_limit_s: float


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("AIRPOWER_DATABASE_URL", "sqlite:///./airpower.db"),
        scenario_dir=Path(os.environ.get("AIRPOWER_SCENARIO_DIR", "../scenarios")),
        default_seed=int(os.environ.get("AIRPOWER_DEFAULT_SEED", "42")),
        solver_time_limit_s=float(os.environ.get("AIRPOWER_SOLVER_TIME_LIMIT_S", "20")),
    )
