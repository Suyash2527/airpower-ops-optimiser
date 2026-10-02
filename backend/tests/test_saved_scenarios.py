"""The committed scenarios/ files must be reproducible from the params stored inside them."""

import json
from pathlib import Path

import pytest

from app.models.scenario import GeneratorParams
from app.sim.generate import generate_scenario
from app.sim.scenario_io import load_scenario

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "scenarios"
FILES = sorted(SCENARIO_DIR.glob("*.json"))


def test_expected_files_exist() -> None:
    names = {f.stem for f in FILES}
    assert {"demo", "monsoon_flood_hadr", "winter_fog_north", "cyclone_east_coast"} <= names


def test_demo_is_seed_42_with_default_params() -> None:
    meta = json.loads((SCENARIO_DIR / "demo.json").read_text(encoding="utf-8"))["scenario"]
    assert meta["seed"] == 42
    assert meta["params"] == GeneratorParams(seed=42).model_dump(mode="json")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_saved_scenario_regenerates_byte_for_byte(path: Path) -> None:
    saved = load_scenario(path)
    regenerated = generate_scenario(GeneratorParams(**saved.scenario.params))
    on_disk = path.read_bytes().replace(b"\r\n", b"\n")  # tolerate a CRLF checkout on Windows
    assert regenerated.to_canonical_json().encode() == on_disk


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_saved_scenario_is_labelled_synthetic_and_has_hard_cases(path: Path) -> None:
    s = load_scenario(path)
    assert s.scenario.source == "SYNTHETIC" and "SYNTHETIC" in s.scenario.notes
    assert len(s.scenario.hard_cases) >= 4
    assert all(r.provenance.source in ("SYNTHETIC", "OURAIRPORTS") for r in s.bases)
