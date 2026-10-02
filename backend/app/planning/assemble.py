"""Turn placed sorties into a `Plan` with KPIs. Shared by every planner (greedy now, CP-SAT in
Phase 4) so KPIs mean the same thing everywhere.

KPI definitions
- priority_weighted_coverage: sum of weights of fully covered missions / sum of weights of all
  plannable missions. A mission is covered when it has `aircraft_required` sorties.
- by_priority: covered missions / plannable missions, per priority level.
- aircraft_utilisation / crew_utilisation: distinct aircraft / crew used / all in the snapshot.
- mean_risk / max_risk: over assignments, `risk.total`.
- total_flight_minutes: sum of (land - takeoff).
"""

from __future__ import annotations

from collections import defaultdict

from app.core.clock import utcnow
from app.models.entities import GeoPoint
from app.models.enums import PlanStatus, ReasonCode
from app.models.plans import (
    Assignment,
    Plan,
    PlanKPIs,
    RiskBreakdown,
    SolverInfo,
    UnassignedMission,
)
from app.planning.context import PlanningContext
from app.planning.feasibility import PLANNABLE


def compute_kpis(
    ctx: PlanningContext, assignments: list[Assignment], parent: Plan | None = None
) -> PlanKPIs:
    missions = [m for m in ctx.scenario.missions if m.status in PLANNABLE]
    per_mission: dict[str, int] = defaultdict(int)
    for a in assignments:
        per_mission[a.mission_id] += 1
    covered = [m for m in missions if per_mission[m.id] >= m.aircraft_required]
    total_w = sum(m.weight for m in missions)
    by_priority: dict[str, float] = {}
    for prio in sorted({m.priority for m in missions}):
        group = [m for m in missions if m.priority == prio]
        by_priority[str(prio)] = round(sum(m in covered for m in group) / len(group), 4)
    risks = [a.risk.total for a in assignments]
    return PlanKPIs(
        priority_weighted_coverage=(
            round(sum(m.weight for m in covered) / total_w, 4) if total_w else 0
        ),
        missions_covered=len(covered), missions_total=len(missions), by_priority=by_priority,
        aircraft_utilisation=round(
            len({a.aircraft_id for a in assignments}) / max(1, len(ctx.aircraft)), 4
        ),
        crew_utilisation=round(
            len({c for a in assignments for c in a.crew_ids}) / max(1, len(ctx.crew)), 4
        ),
        mean_risk=round(sum(risks) / len(risks), 4) if risks else 0.0,
        max_risk=max(risks) if risks else 0.0,
        total_flight_minutes=sum(a.land_min - a.takeoff_min for a in assignments),
        changes_vs_parent=None if parent is None else _changes(parent, assignments),
    )


def _changes(parent: Plan, assignments: list[Assignment]) -> int:
    old = {(a.mission_id, a.aircraft_id, a.takeoff_min, tuple(a.crew_ids), a.loadout_id)
           for a in parent.assignments}
    new = {(a.mission_id, a.aircraft_id, a.takeoff_min, tuple(a.crew_ids), a.loadout_id)
           for a in assignments}
    return len(old ^ new)


def make_assignment(
    ctx: PlanningContext, seq: int, mission_id: str, aircraft_id: str, loadout_id: str,
    takeoff: int, land_offset: int, crew_ids: list[str], risk: RiskBreakdown, explanation: str,
    reasons: list[ReasonCode] | None = None,
) -> Assignment:
    a = ctx.aircraft[aircraft_id]
    base = ctx.bases[a.base_id]
    aoi = ctx.missions[mission_id].aoi.center
    return Assignment(
        id=f"S-{mission_id}-{seq}", mission_id=mission_id, aircraft_id=aircraft_id,
        crew_ids=crew_ids, loadout_id=loadout_id, takeoff_min=takeoff,
        land_min=takeoff + land_offset, base_from=base.id, base_to=base.id,
        route=[GeoPoint(lat=base.lat, lon=base.lon), GeoPoint(lat=aoi.lat, lon=aoi.lon),
               GeoPoint(lat=base.lat, lon=base.lon)],
        risk=risk, frozen=False, reasons=reasons or [ReasonCode.ASSIGNED_BEST_SCORE],
        explanation=explanation,
    )


def assemble_plan(
    ctx: PlanningContext, scenario_id: str, planner: str, assignments: list[Assignment],
    unassigned: list[UnassignedMission], wall_ms: int, solver_status: str,
    objective: float | None = None,
) -> Plan:
    assignments = sorted(assignments, key=lambda a: (a.takeoff_min, a.mission_id, a.id))
    return Plan(
        id=f"p_{planner}_{scenario_id}", scenario_id=scenario_id, version=1, parent_plan_id=None,
        status=PlanStatus.DRAFT, created_at=utcnow(), created_by=planner,
        assignments=assignments, unassigned=unassigned, kpis=compute_kpis(ctx, assignments),
        solver=SolverInfo(name=planner, status=solver_status, wall_ms=wall_ms, objective=objective),
        data_label=ctx.scenario.scenario.data_label,
    )
