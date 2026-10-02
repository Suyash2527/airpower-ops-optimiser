"""Wall-clock helper. Planning time never uses it (scenario time is minutes from t0); it only
stamps audit entries and pins, and is a single place to patch in tests."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
