"""Plan-side entities from docs/DATA_MODEL.md (data shapes only; no planning logic yet)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.models.entities import GeoPoint, Model
from app.models.enums import PlanStatus, ProposalStatus, ReasonCode


class RiskBreakdown(Model):
    threat: float = Field(ge=0, le=1)
    weather: float = Field(ge=0, le=1)
    service: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)


class Assignment(Model):
    """One sortie."""

    id: str
    mission_id: str
    aircraft_id: str
    crew_ids: list[str]
    loadout_id: str
    takeoff_min: int
    land_min: int
    base_from: str
    base_to: str
    route: list[GeoPoint]
    risk: RiskBreakdown
    frozen: bool = False
    reasons: list[ReasonCode] = Field(default_factory=list)
    explanation: str = ""


class BlockingReason(Model):
    code: ReasonCode
    count: int = Field(ge=0)
    example: str | None = None


class UnassignedMission(Model):
    mission_id: str
    blocking_reasons: list[BlockingReason]
    explanation: str = ""


class PlanKPIs(Model):
    priority_weighted_coverage: float = Field(ge=0, le=1)
    missions_covered: int = Field(ge=0)
    missions_total: int = Field(ge=0)
    by_priority: dict[str, float] = Field(default_factory=dict)
    aircraft_utilisation: float = Field(ge=0, le=1)
    crew_utilisation: float = Field(ge=0, le=1)
    mean_risk: float = Field(ge=0, le=1)
    max_risk: float = Field(ge=0, le=1)
    total_flight_minutes: int = Field(ge=0)
    changes_vs_parent: int | None = None


class SolverInfo(Model):
    name: str
    status: str
    wall_ms: int = Field(ge=0)
    objective: float | None = None
    gap: float | None = None


class Plan(Model):
    id: str
    scenario_id: str
    version: int = Field(ge=1)
    parent_plan_id: str | None = None
    status: PlanStatus
    created_at: AwareDatetime
    created_by: str
    assignments: list[Assignment]
    unassigned: list[UnassignedMission]
    kpis: PlanKPIs
    solver: SolverInfo
    data_label: Literal["synthetic", "open", "mixed"]


class FieldChange(Model):
    assignment_id: str
    field: str
    from_: Any = Field(alias="from")
    to: Any


class PlanDiff(Model):
    added: list[str]
    removed: list[str]
    changed: list[FieldChange]
    n_changes: int = Field(ge=0)
    coverage_delta: float
    risk_delta: float


class Proposal(Model):
    id: str
    event_id: str
    base_plan_id: str
    rank: int = Field(ge=1)
    fallback: bool = False
    plan: Plan
    diff: PlanDiff
    score_breakdown: dict[str, float]
    explanation: str
    status: ProposalStatus


class AuditEntry(Model):
    id: str
    ts: AwareDatetime
    actor: str
    action: str
    object_type: str
    object_id: str
    details_json: dict[str, Any] = Field(default_factory=dict)
