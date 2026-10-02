"""Scenario JSON save/load in the canonical, byte-stable format."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.models.scenario import ScenarioFile


def save_scenario(scenario: ScenarioFile, path: Path) -> str:
    """Write canonical JSON (LF, UTF-8) and return its SHA-256 hex digest."""
    data = scenario.to_canonical_json().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def load_scenario(path: Path) -> ScenarioFile:
    return ScenarioFile.model_validate_json(path.read_bytes())


def scenario_digest(scenario: ScenarioFile) -> str:
    return hashlib.sha256(scenario.to_canonical_json().encode("utf-8")).hexdigest()
