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


def explain_unassigned_after_planning(
    ctx: PlanningContext, mission: Mission, feas: MissionFeasibility, assignments: list
) -> tuple[list[BlockingReason], str]:
    """Explain a mission left out of a finished plan. If the matrix already shows it cannot be
    flown, say why (as before). If it could be flown on its own, replay the finished plan's
    resource use against each of its options and report what they collide with."""
    from app.planning.resources import Placed, ResourceLedger  # local: avoids an import cycle

    if not feas.options or not feas.coverable:
        reasons = blocking_reasons(feas)
        return reasons, explain_unassigned(mission, feas, reasons, feas.n_combos)

    ledger = ResourceLedger(ctx)
    for a in assignments:
        ledger.add(Placed(a.mission_id, a.aircraft_id, a.loadout_id, a.base_from, a.takeoff_min,
                          a.land_min, tuple(a.crew_ids)))
    contention: Counter[ReasonCode] = Counter()
    rivals: dict[str, int] = {}
    fits = 0
    for opt in feas.options:
        why_counts: Counter[ReasonCode] = Counter()
        fitted = False
        for slot in opt.slots:
            placed, why = ledger.try_place(mission, opt, slot)
            if placed is not None:
                ledger.remove(placed)
                fitted = True
                break
            why_counts[why or ReasonCode.NO_QUALIFIED_CREW] += 1
        if fitted:
            fits += 1
            continue
        contention[why_counts.most_common(1)[0][0]] += 1
        for a in assignments:
            if a.aircraft_id == opt.aircraft_id:
                rivals[a.mission_id] = ctx.missions[a.mission_id].priority

    reasons = blocking_reasons(feas, contention)
    reasons.insert(0, BlockingReason(
        code=ReasonCode.DROPPED_LOWER_PRIORITY, count=len(feas.options),
        example=f"{len(feas.options)} feasible aircraft options, {fits} still fit the finished "
                f"plan one at a time",
    ))
    parts = [
        f"{mission.id} (priority {mission.priority}, needs {mission.aircraft_required} aircraft) "
        f"could be flown on its own ({len(feas.options)} aircraft options) but is not in the plan."
    ]
    if contention:
        top = ", ".join(f"{n} blocked by {PHRASE.get(c, c.value)} ({c.value})"
                        for c, n in contention.most_common(3))
        parts.append(f"Against the other sorties in the plan: {top}.")
    if rivals:
        listed = ", ".join(f"{m} (priority {p})" for m, p in sorted(rivals.items())[:4])
        parts.append(f"Those aircraft are committed to {listed}.")
    if fits:
        parts.append(
            f"{fits} option(s) still fit individually; under the chosen objective weights the "
            f"plan scored higher without adding this mission."
        )
    return reasons, " ".join(parts)
