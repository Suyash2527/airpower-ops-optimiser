"""Baseline planners (ALGORITHMS §6), used for honest comparison and as the fallback later.

- `greedy_priority`: missions by priority, then window start, then id; for each, take the lowest-
  cost feasible options (lowest total risk, then earliest takeoff, then aircraft id). No look-ahead.
- `fifo`: missions in request order (their order in the scenario); for each, the first feasible
  option in aircraft order, earliest slot first.

Both use the same feasibility matrix and the same resource ledger, and must pass `validate`.
A mission needing several aircraft is placed all-or-nothing (a partial set is rolled back).
Sorties of one mission are independent: each covers the whole on-station duration inside the
window; they are not required to fly in formation (limitation, see DECISIONS).
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Literal

from app.models.entities import Mission
from app.models.enums import ReasonCode
from app.models.plans import Assignment, Plan, UnassignedMission
from app.planning.assemble import assemble_plan, make_assignment
from app.planning.context import PlanningContext
from app.planning.explain import blocking_reasons, explain_assignment, explain_unassigned
from app.planning.feasibility import (
    FeasibilityMatrix,
    MissionFeasibility,
    Option,
    SlotOption,
    build_matrix,
)
from app.planning.resources import ResourceLedger

Planner = Literal["greedy_priority", "fifo"]


def _candidates(
    feas: MissionFeasibility, planner: Planner
) -> list[tuple[Option, SlotOption]]:
    pairs = [(o, s) for o in feas.options for s in o.slots]
    if planner == "greedy_priority":
        pairs.sort(key=lambda p: (p[1].risk.total, p[1].takeoff_min, p[0].aircraft_id,
                                  p[0].loadout_id))
    return pairs  # fifo keeps matrix order: aircraft order, then loadout, then earliest slot


def _order(ctx: PlanningContext, matrix: FeasibilityMatrix, planner: Planner) -> list[Mission]:
    missions = [ctx.missions[mid] for mid in matrix.missions]  # scenario (request) order
    if planner == "greedy_priority":
        missions.sort(key=lambda m: (m.priority, m.window_start_min, m.id))
    return missions


def plan(
    ctx: PlanningContext, scenario_id: str, planner: Planner,
    matrix: FeasibilityMatrix | None = None,
) -> Plan:
    started = time.perf_counter()
    matrix = matrix or build_matrix(ctx)
    ledger = ResourceLedger(ctx)
    assignments: list[Assignment] = []
    unassigned: list[UnassignedMission] = []

    for mission in _order(ctx, matrix, planner):
        feas = matrix.missions[mission.id]
        placed, contention = [], Counter()
        if feas.coverable:
            placed, contention = _place_mission(ledger, mission, feas, planner)
        if len(placed) >= mission.aircraft_required:
            ranked = _candidates(feas, "greedy_priority")
            for seq, (p, opt, slot) in enumerate(placed, start=1):
                alt = next(
                    ((o.aircraft_id, s.risk.total) for o, s in ranked
                     if o.aircraft_id not in {q[0].aircraft_id for q in placed}), None,
                )
                assignments.append(make_assignment(
                    ctx, seq, mission.id, p.aircraft_id, p.loadout_id, p.takeoff,
                    opt.land_offset, list(p.crew_ids), slot.risk,
                    explain_assignment(
                        ctx, mission, p.aircraft_id, p.loadout_id, p.takeoff, p.land,
                        opt.transit_min, slot.risk, list(p.crew_ids), planner, alt,
                    ),
                ))
        else:
            for p, _, _ in placed:  # all-or-nothing
                ledger.remove(p)
            reasons = blocking_reasons(feas, contention)
            unassigned.append(UnassignedMission(
                mission_id=mission.id, blocking_reasons=reasons,
                explanation=explain_unassigned(mission, feas, reasons, feas.n_combos),
            ))
    unassigned.sort(key=lambda u: u.mission_id)
    wall_ms = int((time.perf_counter() - started) * 1000)
    return assemble_plan(ctx, scenario_id, planner, assignments, unassigned, wall_ms, "HEURISTIC")


def _place_mission(
    ledger: ResourceLedger, mission: Mission, feas: MissionFeasibility, planner: Planner,
    need: int | None = None, already: set[str] | None = None,
) -> tuple[list[tuple], Counter[ReasonCode]]:
    """Place `need` more sorties (default: all the mission needs), never reusing an aircraft in
    `already` (those flying this mission in kept sorties)."""
    need = mission.aircraft_required if need is None else need
    placed: list[tuple] = []
    lost: dict[tuple[str, str], Counter[ReasonCode]] = defaultdict(Counter)
    used_aircraft: set[str] = set(already or ())
    for opt, slot in _candidates(feas, planner):
        if opt.aircraft_id in used_aircraft:
            continue
        p, why = ledger.try_place(mission, opt, slot)
        if p is None:
            lost[(opt.aircraft_id, opt.loadout_id)][why or ReasonCode.NO_QUALIFIED_CREW] += 1
            continue
        placed.append((p, opt, slot))
        used_aircraft.add(opt.aircraft_id)
        if len(placed) == need:
            break
    contention: Counter[ReasonCode] = Counter()
    for combo, counts in lost.items():
        if combo[0] not in used_aircraft:
            contention[counts.most_common(1)[0][0]] += 1
    return placed, contention
