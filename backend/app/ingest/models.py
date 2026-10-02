"""Fusion data structures (ALGORITHMS §1, PRD F-1..F-4).

Everything here is configuration or output of the fusion step. Numbers in `FusionConfig` are
placeholders we chose; they are configuration, not empirical (HONESTY.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from app.models.entities import Model

# Groups that carry live, per-source observations and therefore go through fusion. The rest
# (bases, aircraft types, loadouts, alternate airfields, maintenance history, events) are
# reference data and pass through untouched.
FUSED_GROUPS: tuple[str, ...] = (
    "aircraft", "crew", "weapon_stocks", "missions", "threats", "airspace", "weather",
)

DEFAULT_SOURCE_TRUST: dict[str, float] = {
    "SYNTHETIC": 1.0,
    "SYNTHETIC_SECONDARY": 0.7,
    "OPEN_METEO": 0.9,
    "FILE": 0.8,  # any "FILE:<name>" source
}

# Observations older than this (minutes) are stale. ALGORITHMS §1 gives aircraft 60, weather 180
# and threats 30; the rest are our own placeholders.
DEFAULT_MAX_AGE_MIN: dict[str, float] = {
    "aircraft": 60, "crew": 120, "weapon_stocks": 240, "missions": 1440,
    "threats": 30, "airspace": 360, "weather": 180,
}


class FusionConfig(Model):
    source_trust: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_SOURCE_TRUST))
    default_trust: float = Field(0.5, ge=0, le=1)  # sources not listed above
    max_age_min: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_MAX_AGE_MIN))
    # Time-decay constant per group; defaults to max_age_min (score falls to ~0.37 at the limit).
    tau_min: dict[str, float] = Field(default_factory=dict)
    # Two numbers differ materially when |a-b| > max(abs, rel * max(|a|, |b|)).
    numeric_rel_tol: float = Field(0.05, ge=0)
    numeric_abs_tol: float = Field(1e-6, ge=0)
    # "group.field" -> (abs, rel) overrides; lat/lon leaves are always absolute (~2 km).
    field_tolerances: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {"airspace.polygon": (0.02, 0.0)}
    )
    coordinate_abs_tol_deg: float = Field(0.02, ge=0)
    notice: str = (
        "Source trust, max ages and tolerances are configuration values chosen by us, "
        "not empirical measurements."
    )

    def trust_for(self, source: str) -> float:
        if source in self.source_trust:
            return self.source_trust[source]
        return self.source_trust.get(source.split(":", 1)[0], self.default_trust)

    def tau_for(self, group: str) -> float:
        return self.tau_min.get(group, self.max_age_min[group])

    def tolerance_for(self, group: str, fieldname: str) -> tuple[float, float]:
        return self.field_tolerances.get(
            f"{group}.{fieldname}", (self.numeric_abs_tol, self.numeric_rel_tol)
        )


# ----------------------------------------------------------------------------- adapter output
class RejectedRecord(Model):
    """An input row that could not be turned into a canonical record (surfaced, never dropped
    silently)."""

    adapter: str
    group: str
    row: int  # 1-based position in the input
    message: str


@dataclass
class RecordBatch:
    """What an adapter's `fetch()` returns: canonical entities per group, each carrying its own
    `Provenance`, plus any rows it had to reject."""

    adapter: str
    records: dict[str, list[BaseModel]]
    rejected: list[RejectedRecord] = field(default_factory=list)


# --------------------------------------------------------------------------- fusion outputs
class FusionReason(StrEnum):
    """Why the fused value is what it is (machine-readable; HARD RULE 4)."""

    HIGHEST_SCORE = "HIGHEST_SCORE"
    STALE_OBSERVATION_DISCARDED = "STALE_OBSERVATION_DISCARDED"
    ALL_OBSERVATIONS_STALE = "ALL_OBSERVATIONS_STALE"
    PINNED_BY_HUMAN = "PINNED_BY_HUMAN"


class Pin(Model):
    """A human decision that fixes one field of one record (audited)."""

    conflict_id: str
    group: str
    entity_id: str
    field: str
    value: Any
    actor: str
    reason: str | None
    chosen_source: str | None  # set when the value was picked from a reported source
    ts: AwareDatetime


class Candidate(Model):
    """One source's observation of a field, with the numbers that decided the outcome."""

    source: str
    value: Any
    observed_at: AwareDatetime
    confidence: float
    trust: float
    age_min: float
    score: float
    stale: bool
    selected: bool
    discarded_stale: bool  # excluded from the contest because it was stale and a fresh one existed


class Conflict(Model):
    id: str  # "cf_" + stable hash of (group, entity, field)
    group: str
    entity_id: str
    field: str
    status: Literal["open", "pinned"]
    reason: FusionReason
    resolved_value: Any
    resolved_source: str
    candidates: list[Candidate]  # best score first
    pin: Pin | None = None
    explanation: str


class RecordFusion(Model):
    """Per-record fusion metadata (PRD F-2). Kept beside the entity because entities are strict
    models with no staleness field."""

    group: str
    entity_id: str
    source: str  # source that won the most fields
    sources: list[str]  # every source that reported this record
    observed_at: AwareDatetime  # oldest observation among the winning fields
    confidence: float  # lowest confidence among the winning fields (conservative)
    staleness_min: float  # now - observed_at
    stale: bool
    stale_fields: dict[str, float] = Field(default_factory=dict)  # field -> staleness_min
    conflict_fields: list[str] = Field(default_factory=list)
    pinned_fields: list[str] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)  # only fields not won by `source`


class SourceSummary(Model):
    source: str
    trust: float
    records: int
    fields_won: int


class GroupCounts(Model):
    records: int = 0
    multi_source: int = 0
    conflicts: int = 0
    stale_records: int = 0


class StaleItem(Model):
    group: str
    entity_id: str
    source: str
    staleness_min: float
    max_age_min: float
    fields: list[str]


class FusionCounts(Model):
    records: int = 0
    single_source: int = 0
    multi_source: int = 0
    fields_compared: int = 0  # fields with at least two observations
    fields_agree: int = 0
    conflicts: int = 0
    conflicts_open: int = 0
    conflicts_pinned: int = 0
    stale_records: int = 0
    stale_fields: int = 0
    discarded_stale_observations: int = 0
    duplicates_dropped: int = 0
    rejected_records: int = 0


class FusionReport(Model):
    scenario_id: str | None = None
    data_label: str = "synthetic"
    now: AwareDatetime
    now_min: int | None = None
    state_version: int = 0
    secondary_source_enabled: bool | None = None
    sources: list[SourceSummary]
    counts: FusionCounts
    by_group: dict[str, GroupCounts]
    conflicts: list[Conflict]
    stale: list[StaleItem]
    rejected: list[RejectedRecord]
    config: FusionConfig

