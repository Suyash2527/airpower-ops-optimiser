"""The adapter contract (ARCHITECTURE decision 6: swapping synthetic for real feeds changes only
adapters). An adapter turns one source into canonical records that each carry a `Provenance`."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ingest.models import RecordBatch


class AdapterError(ValueError):
    """The whole input is unusable (missing file, bad format, unknown group). Per-row problems
    are not errors: they come back in `RecordBatch.rejected`."""


@runtime_checkable
class Adapter(Protocol):
    name: str

    def fetch(self) -> RecordBatch: ...
