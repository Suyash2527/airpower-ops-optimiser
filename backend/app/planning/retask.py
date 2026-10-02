"""Retasking (ALGORITHMS §5, PRD R-1..R-5): after an event, propose alternative plans. It never
changes anything itself: the output is `ProposalDraft`s that a human approves or rejects.

1. The caller applies the event to a copy of the state and builds the context at `now = event time`.
2. Frozen set: parent assignments with takeoff <= now (airborne or finished) are fixed.
3. Affected set: the parent (frozen flags applied) is re-validated against the new state; every
   non-frozen assignment with a violation is affected, plus those of a mission whose priority
   changed.
4. Greedy repair: keep everything unaffected, re-place what is missing in priority order. It is the
   warm start for the optimiser and the fallback when the optimiser finds nothing in time.
5. Variants: one CP-SAT solve per weight preset (default stability_first, coverage_first,
   risk_averse) with frozen sorties fixed, the stability penalty against the parent, and the repair
   plan as hint. Identical plans are merged; every plan must pass `validate`.
6. Rank by a documented score whose components are always shown (never an opaque number):
       total = 100 * coverage_delta  -  20 * risk_delta  -  1 * n_changes     (placeholders)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from app.models.entities import Event
from app.models.enums import EventType, PlanStatus, ReasonCode
from app.models.plans import Assignment, Plan, PlanDiff, UnassignedMission
from app.planning.assemble import assemble_plan, compute_kpis, make_assignment
from app.planning.context import PlanningContext
from app.planning.diff import COMPARED, diff_plans
from app.planning.explain import explain_assignment, explain_unassigned_after_planning
from app.planning.feasibility import FeasibilityMatrix, build_matrix
from app.planning.greedy import _place_mission
from app.planning.optimiser import SolveParams, solve
from app.planning.resources import Placed, ResourceLedger
from app.planning.validate import Violation, validate_plan

DEFAULT_PRESETS = ("stability_first", "coverage_first", "risk_averse")


@dataclass(frozen=True)
class RetaskParams:
    presets: tuple[str, ...] = DEFAULT_PRESETS
    time_budget_s: float = 20.0  # shared by the variants
    num_workers: int = 4
    seed: int = 0
    coverage_weight: float = 100.0
    risk_weight: float = 20.0
    change_weight: float = 1.0


@dataclass
class ProposalDraft:
    plan: Plan
    diff: PlanDiff
    score_breakdown: dict[str, float]
    explanation: str
    fallback: bool
    preset: str


@dataclass
class Affected:
    violations: dict[str, list[Violation]] = field(default_factory=dict)  # assignment id ->
    priority_changed: set[str] = field(default_factory=set)  # assignment ids

    @property
    def ids(self) -> set[str]:
        return set(self.violations) | self.priority_changed


# ----------------------------------------------------------------------------- steps 2 and 3
def freeze(parent: Plan, now_min: int) -> Plan:
    """Copy of the plan where every sortie that has taken off by `now_min` is frozen."""
    rows = [
        a.model_copy(update={"frozen": True, "reasons": [ReasonCode.FROZEN_AIRBORNE]})
        if a.takeoff_min <= now_min else a
        for a in parent.assignments
    ]
    return parent.model_copy(update={"assignments": rows})


def find_affected(
    ctx: PlanningContext, parent_frozen: Plan, event: Event, fusion_meta=None
) -> Affected:
    found = validate_plan(
        ctx.scenario, parent_frozen, cfg=ctx.cfg, now_min=ctx.now_min, fusion_meta=fusion_meta
    )
    out = Affected()
    movable = {a.id for a in parent_frozen.assignments if not a.frozen}
    for v in found:
        if v.assignment_id in movable:
            out.violations.setdefault(v.assignment_id, []).append(v)  # type: ignore[arg-type]
    if event.type is EventType.PRIORITY_CHANGE:
        mid = event.payload["mission_id"]
        out.priority_changed = {a.id for a in parent_frozen.assignments
                                if a.mission_id == mid and not a.frozen}
    return out


# ------------------------------------------------------------------------------ step 4: repair
def greedy_repair(
    ctx: PlanningContext, scenario_id: str, parent_frozen: Plan, affected: Affected,
    matrix: FeasibilityMatrix,
) -> Plan:
    """Keep every unaffected sortie, then place what is missing, highest priority first."""
    started = time.perf_counter()
    drop = set(affected.violations)  # priority-changed sorties stay: they are still valid
    kept = [a for a in parent_frozen.assignments if a.id not in drop]
    ledger = ResourceLedger(ctx)
    placed_of: dict[str, Placed] = {}
    for a in kept:
        p = Placed(a.mission_id, a.aircraft_id, a.loadout_id, a.base_from, a.takeoff_min,
                   a.land_min, tuple(a.crew_ids))
        ledger.add(p)
        placed_of[a.id] = p

    by_mission: dict[str, list[Assignment]] = defaultdict(list)
    for a in kept:
        by_mission[a.mission_id].append(a)
    new_rows: list[Assignment] = []
    todo = sorted(
        (ctx.missions[mid] for mid in matrix.missions),
        key=lambda m: (m.priority, m.window_start_min, m.id),
    )
    for mission in todo:
        have = by_mission.get(mission.id, [])
        need = mission.aircraft_required - len(have)
        if need <= 0:
            continue
        feas = matrix.missions[mission.id]
        placed: list[tuple] = []
        if feas.coverable or have:
            placed, _ = _place_mission(
                ledger, mission, feas, "greedy_priority", need, {a.aircraft_id for a in have}
            )
        if len(placed) == need:
            for p, opt, slot in placed:
                new_rows.append(make_assignment(
                    ctx, 0, mission.id, p.aircraft_id, p.loadout_id, p.takeoff, opt.land_offset,
                    list(p.crew_ids), slot.risk,
                    explain_assignment(
                        ctx, mission, p.aircraft_id, p.loadout_id, p.takeoff, p.land,
                        opt.transit_min, slot.risk, list(p.crew_ids), "greedy repair", None),
                    [ReasonCode.CHANGED_DUE_TO_EVENT],
                ))
            continue
        for p, _, _ in placed:  # all-or-nothing: undo, and drop this mission's movable sorties
            ledger.remove(p)
        if not any(a.frozen for a in have):
            for a in have:
                ledger.remove(placed_of[a.id])
            by_mission[mission.id] = []
    rows = [a for rows_ in by_mission.values() for a in rows_] + new_rows
    rows = relabel(parent_frozen, rows)
    unassigned = _unassigned_for(ctx, matrix, rows)
    wall_ms = int((time.perf_counter() - started) * 1000)
    return assemble_plan(ctx, scenario_id, "greedy_repair", rows, unassigned, wall_ms, "HEURISTIC")


def _unassigned_for(
    ctx: PlanningContext, matrix: FeasibilityMatrix, rows: list[Assignment]
) -> list[UnassignedMission]:
    count: dict[str, int] = defaultdict(int)
    for a in rows:
        count[a.mission_id] += 1
    out = []
    for mid, feas in matrix.missions.items():
        m = ctx.missions[mid]
        if count[mid] >= m.aircraft_required:
            continue
        reasons, text = explain_unassigned_after_planning(ctx, m, feas, rows)
        out.append(UnassignedMission(mission_id=mid, blocking_reasons=reasons, explanation=text))
    return sorted(out, key=lambda u: u.mission_id)


# ----------------------------------------------------------------------------------- relabelling
def _sig(a: Assignment) -> tuple:
    return (a.mission_id, a.aircraft_id, a.loadout_id, a.takeoff_min, tuple(a.crew_ids))


def relabel(parent: Plan, rows: list[Assignment]) -> list[Assignment]:
    """Give sorties stable ids so a diff shows 'changed' rather than 'removed + added': an identical
    sortie keeps its parent id; otherwise a changed sortie of the same mission reuses an unmatched
    parent id of that mission; anything else gets a fresh id."""
    old = list(parent.assignments)
    used: set[str] = set()
    out: dict[int, str] = {}
    by_sig: dict[tuple, list[Assignment]] = defaultdict(list)
    for a in old:
        by_sig[_sig(a)].append(a)
    for i, a in enumerate(rows):
        if a.frozen and a.id in {o.id for o in old} and a.id not in used:
            out[i] = a.id
            used.add(a.id)
    for i, a in enumerate(rows):
        if i in out:
            continue
        for cand in by_sig.get(_sig(a), []):
            if cand.id not in used:
                out[i] = cand.id
                used.add(cand.id)
                break
    for i, a in enumerate(rows):
        if i in out:
            continue
        for cand in old:
            if cand.mission_id == a.mission_id and cand.id not in used:
                out[i] = cand.id
                used.add(cand.id)
                break
    taken = set(used)
    result: list[Assignment] = []
    for i, a in enumerate(rows):
        aid = out.get(i)
        if aid is None:
            n = 1
            while f"S-{a.mission_id}-{n}" in taken:
                n += 1
            aid = f"S-{a.mission_id}-{n}"
            taken.add(aid)
        result.append(a.model_copy(update={"id": aid}))
    return result


# ------------------------------------------------------------------------------- explanations
def describe_event(event: Event) -> str:
    p, t = event.payload, event.type
    when = f"T+{event.time_min}"
    if t is EventType.AIRCRAFT_UNSERVICEABLE:
        back = f"until T+{p['until_min']}" if p["until_min"] is not None else "with no return time"
        return f"{p['aircraft_id']} became unserviceable at {when}, {back}"
    if t is EventType.CREW_UNAVAILABLE:
        return f"crew {p['crew_id']} unavailable from {when} until T+{p['until_min']}"
    if t is EventType.WEATHER_CHANGE:
        return f"weather change at {p['base_id']} from {when}"
    if t is EventType.NEW_THREAT:
        th = p["threat"]
        return f"new threat zone {th['id']} (severity {th['severity']}) from {when}"
    if t is EventType.THREAT_UPDATE:
        return f"threat {p['threat_id']} updated at {when}"
    if t is EventType.AIRSPACE_CHANGE:
        return f"airspace change: zone {p['zone']['id']} ({p['zone']['kind']}) at {when}"
    if t is EventType.PRIORITY_CHANGE:
        return f"{p['mission_id']} priority changed to {p['new_priority']} at {when}"
    if t is EventType.NEW_MISSION:
        return f"new mission {p['mission']['id']} (priority {p['mission']['priority']}) at {when}"
    return f"{p['mission_id']} cancelled at {when}"


def annotate(plan: Plan, parent: Plan, event: Event) -> Plan:
    """Mark each sortie as frozen, preserved or changed-because-of-the-event, with a sentence."""
    old = {a.id: a for a in parent.assignments}
    rows = []
    for a in plan.assignments:
        before = old.get(a.id)
        if a.frozen:
            rows.append(a.model_copy(update={"reasons": [ReasonCode.FROZEN_AIRBORNE]}))
        elif before is not None and all(getattr(a, f) == getattr(before, f) for f in COMPARED):
            rows.append(a.model_copy(update={"reasons": [ReasonCode.PRESERVED_EXISTING],
                                             "explanation": before.explanation}))
        else:
            was = (f" (was {before.aircraft_id} at T+{before.takeoff_min})" if before else
                   " (a new sortie)")
            rows.append(a.model_copy(update={
                "reasons": [ReasonCode.CHANGED_DUE_TO_EVENT],
                "explanation": f"{a.explanation} Changed because: {describe_event(event)}{was}.",
            }))
    return plan.model_copy(update={"assignments": rows})


def _changes_text(diff: PlanDiff, plan: Plan, parent: Plan, limit: int = 4) -> str:
    old = {a.id: a for a in parent.assignments}
    new = {a.id: a for a in plan.assignments}
    parts = []
    for cid in sorted({c.assignment_id for c in diff.changed})[:limit]:
        a, b = old[cid], new[cid]
        parts.append(f"{b.mission_id}: {a.aircraft_id}@T+{a.takeoff_min} -> "
                     f"{b.aircraft_id}@T+{b.takeoff_min}")
    for aid in diff.removed[:limit]:
        parts.append(f"{old[aid].mission_id} dropped (was {old[aid].aircraft_id})")
    for aid in diff.added[:limit]:
        n = new[aid]
        parts.append(f"{n.mission_id} added ({n.aircraft_id}@T+{n.takeoff_min})")
    return "; ".join(parts[:limit * 2]) or "no sortie changes"


def explain_proposal(
    event: Event, parent: Plan, plan: Plan, diff: PlanDiff, affected: Affected, preset: str,
    fallback: bool,
) -> str:
    n_frozen = sum(a.frozen for a in plan.assignments)
    codes = sorted({v.code for vs in affected.violations.values() for v in vs})
    text = (
        f"{describe_event(event)}. {len(affected.ids)} assignment(s) affected"
        f"{' (' + ', '.join(codes) + ')' if codes else ''}. This plan ({preset}) changes "
        f"{diff.n_changes} assignment(s): {_changes_text(diff, plan, parent)}. Priority-weighted "
        f"coverage {parent.kpis.priority_weighted_coverage:.2f} -> "
        f"{plan.kpis.priority_weighted_coverage:.2f}; mean risk {parent.kpis.mean_risk:.3f} -> "
        f"{plan.kpis.mean_risk:.3f}. {n_frozen} sortie(s) already under way are unchanged."
    )
    if fallback:
        text += " Greedy repair: the optimiser found no solution within its time budget."
    return text


# --------------------------------------------------------------------------------- the entry point
def propose(
    ctx: PlanningContext,
    scenario_id: str,
    parent: Plan,
    event: Event,
    params: RetaskParams | None = None,
    fusion_meta=None,
    matrix: FeasibilityMatrix | None = None,
) -> tuple[list[ProposalDraft], Affected]:
    """`ctx` must be built from the state *after* the event, with `now_min = event.time_min`."""
    params = params or RetaskParams()
    matrix = matrix or build_matrix(ctx)
    parent_frozen = freeze(parent, ctx.now_min)
    affected = find_affected(ctx, parent_frozen, event, fusion_meta)
    frozen = [a for a in parent_frozen.assignments if a.frozen]
    repair = greedy_repair(ctx, scenario_id, parent_frozen, affected, matrix)

    candidates: list[tuple[str, Plan, bool]] = []
    per = params.time_budget_s / max(1, len(params.presets))
    for preset in params.presets:
        sp = SolveParams(time_limit_s=per, num_workers=params.num_workers, seed=params.seed,
                         weight_preset=preset)
        plan = solve(ctx, scenario_id, sp, matrix, seed_plan=repair, frozen=frozen,
                     parent=parent_frozen)
        fell_back = plan.solver.status.startswith("FALLBACK")
        candidates.append((preset, plan, fell_back))
    if all(c[2] for c in candidates):  # nothing from the optimiser: one honest fallback proposal
        candidates = [("greedy_repair", repair, True)]

    drafts: list[ProposalDraft] = []
    seen: set[frozenset] = set()
    for preset, plan, fell_back in candidates:
        rows = relabel(parent_frozen, plan.assignments)
        key = frozenset((_sig(a), a.frozen) for a in rows)
        if key in seen:
            continue
        seen.add(key)
        plan = plan.model_copy(update={"assignments": rows})
        plan.kpis = compute_kpis(ctx, rows, parent)
        plan = annotate(plan, parent, event)
        problems = validate_plan(
            ctx.scenario, plan, cfg=ctx.cfg, now_min=ctx.now_min, parent=parent_frozen,
            fusion_meta=fusion_meta,
        )
        if problems:  # a bug, never a proposal
            continue
        plan = plan.model_copy(update={
            "status": PlanStatus.PROPOSED, "parent_plan_id": parent.id,
            "version": parent.version + 1, "created_by": f"retask:{preset}",
        })
        diff = diff_plans(parent, plan)
        plan.kpis.changes_vs_parent = diff.n_changes
        breakdown = {
            "coverage": round(params.coverage_weight * diff.coverage_delta, 4),
            "risk": round(-params.risk_weight * diff.risk_delta, 4),
            "stability": round(-params.change_weight * diff.n_changes, 4),
        }
        breakdown["total"] = round(sum(breakdown.values()), 4)
        drafts.append(ProposalDraft(
            plan=plan, diff=diff, score_breakdown=breakdown, fallback=fell_back, preset=preset,
            explanation=explain_proposal(event, parent, plan, diff, affected, preset, fell_back),
        ))
    def order(d: ProposalDraft) -> tuple:
        pos = DEFAULT_PRESETS.index(d.preset) if d.preset in DEFAULT_PRESETS else 9
        return (-d.score_breakdown["total"], d.diff.n_changes, pos)

    drafts.sort(key=order)
    return drafts, affected

