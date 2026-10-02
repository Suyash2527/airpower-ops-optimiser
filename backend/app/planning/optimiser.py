"""CP-SAT optimiser (ALGORITHMS §3).

Stage A (feasibility.py) already decided which (mission, aircraft, loadout, takeoff slot) options
are feasible, with their risk. Stage B (here) chooses among them:

Variables  x[o] sortie chosen, z[m] mission covered (all-or-nothing: sum x = required * z),
           y[o,c] crew member c flies sortie o.
Constraints  one sortie per aircraft per mission; aircraft NoOverlap over [takeoff, land +
           turnaround); crew NoOverlap over [takeoff, land + min_rest); crew duty (total over the
           horizon, conservative); base stock; runway operations per slot; crew per required role.
Objective  maximise sum coverage_points*z - risk_points*x - cost_points*x - early_points*x
           (weights from config/weights.yaml, integer-scaled).

Size control (ALGORITHMS §3.5, DECISIONS D-52): per mission only the best
`max_aircraft_per_mission` (aircraft, loadout) options are modelled, each with at most
`slots_per_option` takeoff slots spread over its feasible range (plus its lowest-risk slot). The
greedy plan's choices are always added, so the optimum of the restricted model is never worse
than greedy. "Optimal" therefore means optimal over this candidate set.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app.models.plans import Assignment, Plan, UnassignedMission
from app.planning.assemble import assemble_plan, make_assignment
from app.planning.config import NO_LOADOUT
from app.planning.context import PlanningContext
from app.planning.explain import (
    explain_assignment,
    explain_unassigned_after_planning,
)
from app.planning.feasibility import (
    FeasibilityMatrix,
    Option,
    SlotOption,
    build_matrix,
    eligible_crew,
    required_roles,
)
from app.planning.greedy import plan as greedy_plan
from app.planning.weights import Weights, get_weights


@dataclass(frozen=True)
class SolveParams:
    time_limit_s: float = 20.0
    num_workers: int = 4
    seed: int = 0
    weight_preset: str = "coverage_first"
    max_aircraft_per_mission: int = 12
    slots_per_option: int = 4
    crew_per_role: int = 4  # candidate crew per role and sortie (least duty first)
    use_greedy_hint: bool = True


Key = tuple[str, str, str, int]  # mission, aircraft, loadout, takeoff


def _spread(slots: tuple[SlotOption, ...], k: int) -> list[SlotOption]:
    """Up to k slots spread over the feasible range, plus the lowest-risk one."""
    if len(slots) <= k:
        return list(slots)
    idx = {round(i * (len(slots) - 1) / (k - 1)) for i in range(k)} if k > 1 else {0}
    chosen = {slots[i].takeoff_min: slots[i] for i in idx}
    best = min(slots, key=lambda s: (s.risk.total, s.takeoff_min))
    chosen[best.takeoff_min] = best
    return [chosen[t] for t in sorted(chosen)]


def _candidates(
    options: list[Option], params: SolveParams, forced: set[Key]
) -> list[tuple[Option, list[SlotOption]]]:
    ranked = sorted(options, key=lambda o: (o.best.risk.total, o.aircraft_id, o.loadout_id))
    keep = ranked[: params.max_aircraft_per_mission]
    keep_ids = {id(o) for o in keep}
    keep += [o for o in ranked[params.max_aircraft_per_mission:]
             if any((o.mission_id, o.aircraft_id, o.loadout_id, s.takeoff_min) in forced
                    for s in o.slots) and id(o) not in keep_ids]
    out = []
    for o in keep:
        slots = {s.takeoff_min: s for s in _spread(o.slots, params.slots_per_option)}
        for s in o.slots:
            if (o.mission_id, o.aircraft_id, o.loadout_id, s.takeoff_min) in forced:
                slots[s.takeoff_min] = s
        out.append((o, [slots[t] for t in sorted(slots)]))
    return out


def plan_objective(ctx: PlanningContext, plan: Plan, weights: Weights) -> int:
    """The optimiser's objective evaluated on any plan (used to compare planners)."""
    per: dict[str, int] = defaultdict(int)
    total = 0
    for a in plan.assignments:
        per[a.mission_id] += 1
        total -= weights.risk_points(a.risk.total)
        total -= weights.cost_points(a.land_min - a.takeoff_min)
        total -= weights.early_points(a.takeoff_min // ctx.cfg.slot_min)
    for mid, n in per.items():
        m = ctx.missions[mid]
        if n >= m.aircraft_required:
            total += weights.coverage_points(m.weight)
    return total


def solve(
    ctx: PlanningContext,
    scenario_id: str,
    params: SolveParams | None = None,
    matrix: FeasibilityMatrix | None = None,
    *,
    seed_plan: Plan | None = None,
    frozen: list[Assignment] | None = None,
    parent: Plan | None = None,
) -> Plan:
    """Solve for a plan.

    seed_plan  warm start and fallback (default: the greedy plan). Its non-frozen sorties are
               always modelled and given as the hint.
    frozen     sorties already under way: fixed, they use up aircraft, crew, stock and runway
               capacity and count towards their mission, but are not decisions (Phase 5).
    parent     plan being replaced: any sortie not identical to one of the parent's pays the
               preset's stability penalty (a different crew for a kept sortie pays it too).
    """
    params = params or SolveParams()
    weights = get_weights(params.weight_preset)
    started = time.perf_counter()
    matrix = matrix or build_matrix(ctx)
    frozen = frozen or []
    seed = seed_plan or greedy_plan(ctx, scenario_id, "greedy_priority", matrix)
    seed_rows = [a for a in seed.assignments if not a.frozen]
    parent_rows = [a for a in (parent.assignments if parent else []) if not a.frozen]
    parent_keys = {(a.mission_id, a.aircraft_id, a.loadout_id, a.takeoff_min) for a in parent_rows}
    parent_crew = {(a.mission_id, a.aircraft_id, a.takeoff_min): set(a.crew_ids)
                   for a in parent_rows}
    forced: set[Key] = (
        {(a.mission_id, a.aircraft_id, a.loadout_id, a.takeoff_min) for a in seed_rows}
        if params.use_greedy_hint else set()
    ) | parent_keys
    hint_keys = {(a.mission_id, a.aircraft_id, a.loadout_id, a.takeoff_min) for a in seed_rows}
    hint_crew = {(a.mission_id, a.aircraft_id, a.takeoff_min): set(a.crew_ids) for a in seed_rows}
    keep_crew = {k: v | parent_crew.get(k, set()) for k, v in hint_crew.items()}
    for k, v in parent_crew.items():
        keep_crew.setdefault(k, v)

    model = cp_model.CpModel()
    z: dict[str, cp_model.IntVar] = {}
    x: dict[Key, cp_model.IntVar] = {}
    info: dict[Key, tuple[Option, SlotOption]] = {}
    y: dict[tuple[Key, str], cp_model.IntVar] = {}
    aircraft_iv: dict[str, list] = defaultdict(list)
    crew_iv: dict[str, list] = defaultdict(list)
    crew_duty: dict[str, list] = defaultdict(list)
    stock: dict[tuple[str, str], list] = defaultdict(list)
    runway: dict[tuple[str, int], dict[cp_model.IntVar, int]] = defaultdict(dict)
    objective: list = []
    rest = ctx.rules.min_rest_min
    slot_min = ctx.cfg.slot_min
    stab = weights.stability_points() if parent is not None else 0
    frozen_count: dict[str, int] = defaultdict(int)
    for f in frozen:
        frozen_count[f.mission_id] += 1

    for mid, feas in matrix.missions.items():
        if not feas.coverable:
            continue
        mission = ctx.missions[mid]
        z[mid] = model.NewBoolVar(f"z_{mid}")
        objective.append(weights.coverage_points(mission.weight) * z[mid])
        mine: list[cp_model.IntVar] = []
        per_aircraft: dict[str, list[cp_model.IntVar]] = defaultdict(list)
        for opt, slots in _candidates(feas.options, params, forced):
            ac = ctx.aircraft[opt.aircraft_id]
            type_ = ctx.types[ac.type_id]
            turn = ctx.turnaround_min(ac.base_id, ac.type_id)
            for s in slots:
                t = s.takeoff_min
                key: Key = (mid, opt.aircraft_id, opt.loadout_id, t)
                var = model.NewBoolVar(f"x_{mid}_{opt.aircraft_id}_{opt.loadout_id}_{t}")
                x[key], info[key] = var, (opt, s)
                mine.append(var)
                per_aircraft[opt.aircraft_id].append(var)
                aircraft_iv[opt.aircraft_id].append(model.NewOptionalFixedSizeIntervalVar(
                    t, opt.land_offset + turn, var, f"a_{key}"))
                objective.append(-(
                    weights.risk_points(s.risk.total) + weights.cost_points(opt.land_offset)
                    + weights.early_points(t // slot_min)
                    + (0 if key in parent_keys else stab)
                ) * var)
                if opt.loadout_id != NO_LOADOUT:
                    for item, qty in ctx.loadouts[opt.loadout_id].items.items():
                        stock[(opt.base_id, item)].append((var, qty))
                for b in (t // slot_min, (t + opt.land_offset) // slot_min):
                    runway[(opt.base_id, b)][var] = runway[(opt.base_id, b)].get(var, 0) + 1
                _crew(model, ctx, mission, opt, s, key, var, type_, y, crew_iv, crew_duty, rest,
                      params.crew_per_role, keep_crew.get((mid, opt.aircraft_id, t), set()))
                if stab and key in parent_keys:  # a kept sortie with a different crew is a change
                    for (k2, cid), yv in y.items():
                        if k2 == key and cid not in parent_crew.get((mid, opt.aircraft_id, t), ()):
                            objective.append(-stab * yv)
        fc = frozen_count.get(mid, 0)
        if fc:
            model.Add(sum(mine) + fc == mission.aircraft_required * z[mid]).OnlyEnforceIf(z[mid])
            model.Add(sum(mine) == 0).OnlyEnforceIf(z[mid].Not())
        else:
            model.Add(sum(mine) == mission.aircraft_required * z[mid])
        for vars_ in per_aircraft.values():
            model.AddAtMostOne(vars_)

    _add_frozen(model, ctx, frozen, aircraft_iv, crew_iv, crew_duty, stock, runway)
    for ivs in aircraft_iv.values():
        model.AddNoOverlap(ivs)
    for ivs in crew_iv.values():
        model.AddNoOverlap(ivs)
    for cid, items in crew_duty.items():
        _duty(model, ctx, cid, items)
    for (base_id, item), terms in stock.items():
        model.Add(sum(v * q for v, q in terms) <= ctx.stock.get((base_id, item), 0))
    for (base_id, _), coefs in runway.items():
        cap = ctx.bases[base_id].runways * ctx.cfg.runway_ops_per_runway_per_slot
        model.Add(sum(v * c for v, c in coefs.items()) <= cap)
    model.Maximize(sum(objective))

    if params.use_greedy_hint:
        for key, var in x.items():
            model.AddHint(var, 1 if key in hint_keys else 0)
        for (key, cid), var in y.items():
            hinted = hint_crew.get((key[0], key[1], key[3]), set())
            model.AddHint(var, 1 if key in hint_keys and cid in hinted else 0)
        covered = {a.mission_id for a in seed.assignments}
        for mid, var in z.items():
            model.AddHint(var, 1 if mid in covered else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = params.time_limit_s
    solver.parameters.num_workers = params.num_workers
    solver.parameters.random_seed = params.seed
    solver.parameters.cp_model_probing_level = 0  # probing costs ~1.5 s here and did not pay off
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    wall_ms = int((time.perf_counter() - started) * 1000)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        fallback = seed.model_copy(update={"created_by": "cpsat"})
        fallback.solver = fallback.solver.model_copy(update={
            "name": "cpsat", "status": f"FALLBACK_GREEDY ({status_name})", "wall_ms": wall_ms,
            "objective": None, "gap": None,
        })
        return fallback

    new_rows, _ = _extract(ctx, solver, matrix, x, y, info, taken_ids={a.id for a in frozen})
    assignments = [*frozen, *new_rows]
    unassigned = _unassigned(ctx, matrix, assignments)
    objective_value = int(round(solver.ObjectiveValue()))
    bound = solver.BestObjectiveBound()
    plan = assemble_plan(
        ctx, scenario_id, "cpsat", assignments, unassigned, wall_ms, status_name,
        objective=float(objective_value),
    )
    plan.solver.gap = round(abs(bound - objective_value) / max(1.0, abs(objective_value)), 6)
    return plan


def _add_frozen(model, ctx, frozen, aircraft_iv, crew_iv, crew_duty, stock, runway) -> None:
    """Sorties already under way are constants: they occupy resources but are not decisions."""
    one = model.NewConstant(1)
    slot_min, rest = ctx.cfg.slot_min, ctx.rules.min_rest_min
    for f in frozen:
        ac = ctx.aircraft[f.aircraft_id]
        turn = ctx.turnaround_min(ac.base_id, ac.type_id)
        aircraft_iv[f.aircraft_id].append(model.NewFixedSizeIntervalVar(
            f.takeoff_min, f.land_min - f.takeoff_min + turn, f"fa_{f.id}"))
        for cid in f.crew_ids:
            crew_iv[cid].append(model.NewFixedSizeIntervalVar(
                f.takeoff_min, f.land_min - f.takeoff_min + rest, f"fc_{f.id}_{cid}"))
            crew_duty[cid].append((one, f.takeoff_min, f.land_min, True))
        if f.loadout_id != NO_LOADOUT:
            for item, qty in ctx.loadouts[f.loadout_id].items.items():
                stock[(ac.base_id, item)].append((one, qty))
        for b in (f.takeoff_min // slot_min, f.land_min // slot_min):
            runway[(ac.base_id, b)][one] = runway[(ac.base_id, b)].get(one, 0) + 1


def _duty(model, ctx, cid: str, items: list) -> None:
    """Crew duty exactly as the validator states it: the carried `duty_minutes_last_24h` counts in
    every window that reaches back before t0, i.e. for sorties landing before T+1440 (so all of
    those together must fit the remaining budget); a sortie landing later is checked against the
    rolling 24 h window that ends at its landing."""
    cap = ctx.rules.max_duty_min_24h
    day = 1440
    early = [(y, land - take) for y, take, land, _ in items if land < day]
    if early:
        model.Add(sum(y * d for y, d in early) <= cap - ctx.crew[cid].duty_minutes_last_24h)
    for yi, _, end, is_frozen in items:
        if end < day or is_frozen:
            continue
        window = [y * (land - take) for y, take, land, _ in items
                  if take <= end and land > end - day]
        model.Add(sum(window) <= cap).OnlyEnforceIf(yi)


def _crew(model, ctx, mission, opt, s, key, var, type_, y, crew_iv, crew_duty, rest, cap,
          must_keep) -> None:
    ac = ctx.aircraft[opt.aircraft_id]
    for role, need in sorted(required_roles(mission, type_).items(), key=lambda kv: kv[0].value):
        _, _, pool = eligible_crew(
            ctx, ac.base_id, ac.type_id, role, opt.land_offset, s.takeoff_min
        )
        pool = sorted(
            pool, key=lambda c: (c.id not in must_keep, c.duty_minutes_last_24h, c.id)
        )[:cap]
        role_vars = []
        for c in pool:
            yv = model.NewBoolVar(f"y_{key}_{c.id}")
            y[(key, c.id)] = yv
            role_vars.append(yv)
            crew_iv[c.id].append(model.NewOptionalFixedSizeIntervalVar(
                s.takeoff_min, opt.land_offset + rest, yv, f"c_{key}_{c.id}"))
            crew_duty[c.id].append(
                (yv, s.takeoff_min, s.takeoff_min + opt.land_offset, False)
            )
        model.Add(sum(role_vars) == need * var)


def _extract(ctx, solver, matrix, x, y, info, taken_ids=frozenset()):
    assignments: list[Assignment] = []
    placed_by_mission: dict[str, int] = defaultdict(int)
    chosen_keys = sorted(k for k, v in x.items() if solver.Value(v))
    ranked: dict[str, list] = {}
    for key in chosen_keys:
        mid, aid, lid, t = key
        opt, slot = info[key]
        crew = sorted(
            (cid for (k, cid), v in y.items() if k == key and solver.Value(v)),
            key=lambda cid: (ctx.crew[cid].role.value, cid),
        )
        if mid not in ranked:
            ranked[mid] = sorted(
                ((o, s) for o in matrix.missions[mid].options for s in o.slots),
                key=lambda p: (p[1].risk.total, p[1].takeoff_min, p[0].aircraft_id),
            )
        taken = {k[1] for k in chosen_keys if k[0] == mid}
        alt = next(((o.aircraft_id, s.risk.total) for o, s in ranked[mid]
                    if o.aircraft_id not in taken), None)
        placed_by_mission[mid] += 1
        while f"S-{mid}-{placed_by_mission[mid]}" in taken_ids:
            placed_by_mission[mid] += 1
        assignments.append(make_assignment(
            ctx, placed_by_mission[mid], mid, aid, lid, t, opt.land_offset, crew, slot.risk,
            explain_assignment(
                ctx, ctx.missions[mid], aid, lid, t, t + opt.land_offset, opt.transit_min,
                slot.risk, crew, "the CP-SAT optimiser", alt,
            ),
        ))
    return assignments, placed_by_mission


def _unassigned(ctx, matrix, assignments) -> list[UnassignedMission]:
    covered: dict[str, int] = defaultdict(int)
    for a in assignments:
        covered[a.mission_id] += 1
    out = []
    for mid, feas in matrix.missions.items():
        m = ctx.missions[mid]
        if covered[mid] >= m.aircraft_required:
            continue
        reasons, text = explain_unassigned_after_planning(ctx, m, feas, assignments)
        out.append(UnassignedMission(mission_id=mid, blocking_reasons=reasons, explanation=text))
    out.sort(key=lambda u: u.mission_id)
    return out

