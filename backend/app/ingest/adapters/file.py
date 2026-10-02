"""FileAdapter: the template for plugging in a real feed (PRD F-1).

A real source (a fleet-status export, a roster dump, a stock report) is wired in by writing a CSV
or JSON file whose rows follow the canonical schema of one group (docs/DATA_MODEL.md), then
pointing a `FileAdapter` at it. Nothing else in the system changes: fusion treats it like any other
source. To go beyond files, implement `Adapter.fetch()` for the new transport and return the same
`RecordBatch`.

File format
-----------
* JSON: a list of objects, or `{"records": [...]}`. Field names and types are the entity's own.
* CSV: a header row of field names. Cells holding lists/objects (`[...]`/`{...}`) are parsed as
  JSON; an empty cell means `null`; numbers and booleans are coerced by the schema.
* Provenance: an optional `provenance` object (JSON only), or the adapter defaults, optionally
  overridden per row with the metadata columns `_observed_at`, `_confidence` and `_ingested_at`.
  Metadata columns start with `_` so they cannot collide with entity fields (Threat has its own
  `confidence`). Every record needs an observed time, from a row or from `observed_at`.
* A row that fails validation is not dropped silently: it is returned in `RecordBatch.rejected`
  with the reason, and appears in the fusion report.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.clock import utcnow
from app.ingest.adapters.base import AdapterError
from app.ingest.models import FUSED_GROUPS, RecordBatch, RejectedRecord
from app.models.entities import DataLabel, Provenance
from app.models.scenario import GROUPS

_META_PREFIX = "_"


class FileAdapter:
    def __init__(
        self,
        path: str | Path,
        group: str,
        *,
        source: str | None = None,
        observed_at: datetime | None = None,
        confidence: float = 0.7,
        data_label: DataLabel = "external",
        ingested_at: datetime | None = None,
    ) -> None:
        if group not in FUSED_GROUPS:
            raise AdapterError(f"group {group!r} cannot be fused; use one of {FUSED_GROUPS}")
        self.path = Path(path)
        self.group = group
        self.source = source or f"FILE:{self.path.stem}"
        self.name = self.source
        self._observed_at = observed_at
        self._confidence = confidence
        self._data_label: DataLabel = data_label
        self._ingested_at = ingested_at

    # ---------------------------------------------------------------------------------- reading
    def fetch(self) -> RecordBatch:
        rows = self._read_rows()
        ingested = self._ingested_at or utcnow()
        model = GROUPS[self.group]
        records: list[BaseModel] = []
        rejected: list[RejectedRecord] = []
        for number, row in enumerate(rows, start=1):
            try:
                records.append(model.model_validate(self._with_provenance(row, ingested)))
            except (ValidationError, ValueError) as exc:
                rejected.append(
                    RejectedRecord(
                        adapter=self.name, group=self.group, row=number, message=_first_error(exc)
                    )
                )
        return RecordBatch(adapter=self.name, records={self.group: records}, rejected=rejected)

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            raise AdapterError(f"feed file not found: {self.path}")
        suffix = self.path.suffix.lower()
        if suffix == ".json":
            return self._read_json()
        if suffix == ".csv":
            return self._read_csv()
        raise AdapterError(f"unsupported feed format {suffix!r} (use .json or .csv)")

    def _read_json(self) -> list[dict[str, Any]]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AdapterError(f"{self.path.name} is not valid JSON: {exc}") from exc
        rows = doc.get("records") if isinstance(doc, dict) else doc
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise AdapterError(f"{self.path.name}: expected a list of objects")
        return rows

    def _read_csv(self) -> list[dict[str, Any]]:
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            return [
                {k: _cell(v) for k, v in row.items() if k is not None}
                for row in csv.DictReader(handle)
            ]

    # ------------------------------------------------------------------------------- provenance
    def _with_provenance(self, row: dict[str, Any], ingested: datetime) -> dict[str, Any]:
        entity = {k: v for k, v in row.items() if not k.startswith(_META_PREFIX)}
        if "provenance" in entity:
            return entity
        observed = row.get("_observed_at") or self._observed_at
        if observed is None:
            raise ValueError("no observed time: set `_observed_at` or the adapter's `observed_at`")
        confidence = row.get("_confidence")
        entity["provenance"] = Provenance(
            source=self.source,
            observed_at=observed,
            ingested_at=row.get("_ingested_at") or ingested,
            confidence=self._confidence if confidence is None else confidence,
            data_label=self._data_label,
        ).model_dump(mode="json")
        return entity


def _cell(text: str | None) -> Any:
    """CSV cell -> JSON-ish value. Only structured cells are parsed here; scalars are left as text
    for the schema to coerce, so an id such as `007` is never turned into the number 7."""
    if text is None or text.strip() == "":
        return None
    stripped = text.strip()
    if stripped[0] in "[{":
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return stripped


def _first_error(exc: ValidationError | ValueError) -> str:
    if isinstance(exc, ValidationError):
        err = exc.errors()[0]
        where = ".".join(str(p) for p in err["loc"])
        return f"{where}: {err['msg']}"
    return str(exc)
