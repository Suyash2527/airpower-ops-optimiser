"""Explanations (ALGORITHMS §8): templates filled with computed values only. No free-text claims.
Every sentence here is built from numbers and codes already produced by the engine."""

from __future__ import annotations

from collections import Counter

from app.models.entities import Mission
from app.models.enums import ReasonCode
from app.models.plans import BlockingReason, RiskBreakdown
from app.planning.context import PlanningContext
from app.planning.feasibility import MissionFeasibility

PHRASE: dict[ReasonCode, str] = {
    ReasonCode.NO_CAPABLE_AIRCRAFT: "no capable aircraft",
    ReasonCode.OUT_OF_RANGE: "out of range",
    ReasonCode.INSUFFICIENT_FUEL_ENDURANCE: "insufficient fuel/endurance",
    ReasonCode.LOADOUT_INCOMPATIBLE: "loadout incompatible or too heavy",
    ReasonCode.NO_LOADOUT_STOCK: "no loadout stock",
    ReasonCode.NO_QUALIFIED_CREW: "no qualified crew",
    ReasonCode.CREW_DUTY_LIMIT: "crew duty limit",
    ReasonCode.CREW_REST_VIOLATION: "crew rest violation",
    ReasonCode.AIRCRAFT_UNSERVICEABLE: "aircraft unserviceable or not yet available",
    ReasonCode.MAINTENANCE_DUE: "maintenance due",
    ReasonCode.AIRSPACE_CONFLICT: "airspace conflict",
    ReasonCode.WEATHER_BELOW_MINIMA_BASE: "weather below minima at base",
    ReasonCode.WEATHER_BELOW_MINIMA_TARGET: "weather below minima at target",
    ReasonCode.THREAT_RISK_EXCEEDS_LIMIT: "threat risk above the mission limit",
    ReasonCode.TIME_WINDOW_UNREACHABLE: "time window unreachable",
    ReasonCode.TURNAROUND_CONFLICT: "aircraft already committed (turnaround)",
    ReasonCode.BASE_RUNWAY_CAPACITY: "base runway capacity",
}


def blocking_reasons(
    feas: MissionFeasibility, contention: Counter[ReasonCode] | None = None
) -> list[BlockingReason]:
    """Reason codes with counts (aircraft options blocked), most common first. `contention` adds
    options that were feasible on their own but lost to other sorties already planned."""
    total: Counter[ReasonCode] = Counter(feas.tally)
    if contention:
        total.update(contention)
    out = [
        BlockingReason(code=c, count=n, example=feas.examples.get(c))
        for c, n in sorted(total.items(), key=lambda kv: (-kv[1], kv[0].value))
    ]
    for f in feas.mission_level:
        out.insert(0, BlockingReason(code=f.code, count=feas.n_capable, example=f.detail))
    return out


def explain_unassigned(
    mission: Mission, feas: MissionFeasibility, reasons: list[BlockingReason], n_options: int
) -> str:
    head = (
        f"{mission.id} (priority {mission.priority}, needs {mission.aircraft_required} "
        f"aircraft) was not assigned."
    )
    if not reasons:
        return f"{head} No blocking reason was recorded."
    parts = [
        f"{r.count} of {max(n_options, r.count)} aircraft options: "
        f"{PHRASE.get(r.code, r.code.value)} ({r.code.value})"
        for r in reasons[:3]
    ]
    return f"{head} Dominant blockers: " + "; ".join(parts) + "."


def explain_assignment(
    ctx: PlanningContext, mission: Mission, aircraft_id: str, loadout_id: str, takeoff: int,
    land: int, transit: int, risk: RiskBreakdown, crew_ids: list[str], planner: str,
    alternative: tuple[str, float] | None,
) -> str:
    a = ctx.aircraft[aircraft_id]
    arrive = takeoff + transit
    text = (
        f"{a.id} ({a.type_id}) from {a.base_id} takes {mission.id} (priority {mission.priority}): "
        f"takeoff T+{takeoff}, on station T+{arrive}..T+{arrive + mission.duration_min}, lands "
        f"T+{land}. Loadout {loadout_id}; crew {', '.join(crew_ids)}. Risk: threat "
        f"{risk.threat:.2f}, weather {risk.weather:.2f}, service {risk.service:.2f}, total "
        f"{risk.total:.2f}. Chosen by {planner}."
    )
    if alternative is not None:
        text += (
            f" Next-best option on paper, before other sorties were placed: {alternative[0]} "
            f"(total risk {alternative[1]:.2f})."
        )
    return text
