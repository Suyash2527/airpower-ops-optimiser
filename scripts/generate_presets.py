"""Regenerate the seasonal preset scenarios in scenarios/ (INDIA_CONTEXT §3.8).

Run from the repo root:  backend/.venv/Scripts/python scripts/generate_presets.py
Each file is fully determined by the params below; the seed is also stored in the file.
demo.json is produced separately by the documented CLI:
    cd backend && python -m app.sim.generate --seed 42 --out ../scenarios/demo.json
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.sim.generate import generate_scenario  # noqa: E402
from app.sim.presets import PRESETS  # noqa: E402  (single source of the preset params)
from app.sim.scenario_io import save_scenario  # noqa: E402

if __name__ == "__main__":
    for name, params in PRESETS.items():
        if name == "demo":  # produced by the documented CLI, see the module docstring
            continue
        digest = save_scenario(generate_scenario(params), ROOT / "scenarios" / f"{name}.json")
        print(f"{name}.json seed={params.seed} sha256={digest[:16]}")
