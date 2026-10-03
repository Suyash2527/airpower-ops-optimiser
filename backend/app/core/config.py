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
    solver_time_limit_s: float
    solver_workers: int = 4  # fix to 1 for bit-for-bit reproducible solves


def _default_database_url() -> str:
    # Vercel functions can only write to /tmp (D-66); that database is per instance and temporary.
    return "sqlite:////tmp/airpower.db" if os.environ.get("VERCEL") else "sqlite:///./airpower.db"


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("AIRPOWER_DATABASE_URL", _default_database_url()),
        scenario_dir=Path(os.environ.get("AIRPOWER_SCENARIO_DIR", "../scenarios")),
        solver_time_limit_s=float(os.environ.get("AIRPOWER_SOLVER_TIME_LIMIT_S", "20")),
        solver_workers=int(os.environ.get("AIRPOWER_SOLVER_WORKERS", "4")),
    )
