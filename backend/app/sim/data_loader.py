"""Loads the committed open-data inputs (see sim/data/ and scripts/fetch_open_data.py)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def load_sites() -> dict[str, Any]:
    return json.loads((DATA_DIR / "sites.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_airports() -> dict[str, Any]:
    return json.loads((DATA_DIR / "india_airports.json").read_text(encoding="utf-8"))
