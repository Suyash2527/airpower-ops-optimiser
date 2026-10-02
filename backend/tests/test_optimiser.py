"""CP-SAT optimiser tests (Tasks 4.1-4.7, 4.9, 4.10).

Objective arithmetic used in the hand-computed cases (preset coverage_first, integer-scaled x10):
  coverage points   = 10 * 100 * mission.weight        (weight 100 -> 100000, 60 -> 60000)
  risk points       = 10 * 1 * 1000 * total risk        (service risk 0.028 -> 280)
  cost points       = 10 * 0.1 * flight minutes         (86 min -> 86)
  early points      = 10 * 0.1 * (takeoff // 15)        (takeoff 90 -> 6)
"""

from __future__ import annotations

import pytest
from planning_world import (
    BASE_LAT,
    BASE_LON,
    PROV,
    aircraft,
    crew,
    ftr,
    loadout,
    mission,
    threat,
    world,
)

from app.models.entities import AOI, GeoPoint, WeaponStock
from app.models.enums import ReasonCode as R
from app.models.plans import Plan
from app.models.scenario import GeneratorParams, ScenarioFile
from app.planning.context import PlanningContext
from app.planning.diff import diff_plans
from app.planning.greedy import plan as greedy_plan
from app.planning.optimiser import SolveParams, plan_objective, solve
from app.planning.validate import validate_plan
from app.planning.weights import SCALE, get_weights, preset_names
from app.sim.generate import generate_scenario

FAST = SolveParams(time_limit_s=5, num_workers=1, seed=1)


def cp(scn: ScenarioFile, **kw) -> Plan:
    params = SolveParams(**{**FAST.__dict__, **kw})
    return solve(PlanningContext(scn), "sc_t", params)


def covered(p: Plan) -> list[str]:
    return sorted({a.mission_id for a in p.assignments})


# ------------------------------------------------------------------------ hand-computed optima
def test_single_mission_optimum_matches_the_hand_computed_objective() -> None:
    scn = world()
    p = cp(scn)
    # 100000 coverage - 280 risk - 86 cost - 6 early (earliest slot 90 -> index 6)
    assert p.solver.status == "OPTIMAL" and p.solver.objective == 100000 - 280 - 86 - 6
    (a,) = p.assignments
    assert (a.aircraft_id, a.takeoff_min, a.crew_ids) == ("A-1", 90, ["C-1"])
    assert p.solver.gap == 0 and validate_plan(scn, p) == []


def test_priority_tradeoff_covers_the_higher_value_mission() -> None:
    low, high = mission("M-1", priority=3, weight=35), mission("M-2", priority=1, weight=100)
    scn = world(missions=[low, high])  # one aircraft, one crew, overlapping windows
    p = cp(scn)
    assert covered(p) == ["M-2"] and p.solver.objective == 100000 - 280 - 86 - 6
    assert [u.mission_id for u in p.unassigned] == ["M-1"]
    u = p.unassigned[0]
    assert R.DROPPED_LOWER_PRIORITY in {b.code for b in u.blocking_reasons}
    assert "M-2 (priority 1)" in u.explanation  # names who holds the aircraft
    assert validate_plan(scn, p) == []


def test_optimiser_beats_greedy_when_greedy_takes_the_only_aircraft_that_can_fly_m2() -> None:
    """Greedy gives M-1 to its lowest-risk aircraft A-1, but only A-1 can reach M-2 (A-2 is a
    short-range type), and A-1 is then busy. Optimum: M-1 -> A-2, M-2 -> A-1, both covered."""
    short = ftr(id="ISR-D", combat_radius_km=300)
    long_loadout = loadout(compatible_aircraft_types=["FTR-A", "ISR-D"])
    m1 = mission("M-1", priority=2, weight=60, window_start_min=100, window_end_min=188)  # slots 90, 105
    m2 = mission(
        "M-2", priority=2, weight=60, window_start_min=130, window_end_min=239,
        aoi=AOI(center=GeoPoint(lat=BASE_LAT + 4.0, lon=BASE_LON), radius_km=20),
    )  # ~445 km: inside FTR-A's radius, outside ISR-D's; slots 105, 120, 135 only
    scn = world(
        aircraft_types=[ftr(compatible_loadouts=["L-AA"]), short.model_copy(
            update={"compatible_loadouts": ["L-AA"]})],
        loadouts=[long_loadout],
        aircraft=[aircraft("A-1", hours_since_maintenance=10),
                  aircraft("A-2", type_id="ISR-D", hours_since_maintenance=50)],
        crew=[crew("C-1", qualifications=["FTR-A", "ISR-D"]),
              crew("C-2", qualifications=["FTR-A", "ISR-D"])],
        missions=[m1, m2],
    )
    ctx = PlanningContext(scn)
    g = greedy_plan(ctx, "sc_t", "greedy_priority")
    assert covered(g) == ["M-1"] and g.kpis.priority_weighted_coverage == 0.5  # greedy is stuck
    p = solve(ctx, "sc_t", FAST)
    assert covered(p) == ["M-1", "M-2"] and p.kpis.priority_weighted_coverage == 1.0
    by = {a.mission_id: a for a in p.assignments}
    assert by["M-1"].aircraft_id == "A-2" and by["M-2"].aircraft_id == "A-1"
    # 120000 coverage; M-1 on A-2: risk 0.06 -> 600, cost 86, early 6; M-2 on A-1: risk 0.028 ->
    # 280, cost 2*34+60 = 128, earliest slot 105 -> early 7
    assert p.solver.status == "OPTIMAL"
    assert p.solver.objective == 120000 - (600 + 86 + 6) - (280 + 128 + 7)
    assert plan_objective(ctx, p, get_weights("coverage_first")) > plan_objective(
        ctx, g, get_weights("coverage_first"))
    assert validate_plan(scn, p) == []


def test_lower_risk_aircraft_is_chosen_when_both_can_fly() -> None:
    scn = world(aircraft=[aircraft("A-1", hours_since_maintenance=90),
                          aircraft("A-2", hours_since_maintenance=10)],
                crew=[crew("C-1"), crew("C-2")])
    p = cp(scn)
    (a,) = p.assignments
    assert a.aircraft_id == "A-2"  # service risk 0.028 vs 0.092
    assert p.solver.objective == 100000 - 280 - 86 - 6


def test_risk_averse_preset_declines_a_risky_low_value_mission() -> None:
    risky = world(missions=[mission(priority=5, weight=10, max_acceptable_risk=0.9)],
                  threats=[threat(severity=0.4, confidence=1.0)])
    assert covered(cp(risky, weight_preset="coverage_first")) == ["M-1"]
    p = cp(risky, weight_preset="risk_averse")
    assert p.assignments == [] and [u.mission_id for u in p.unassigned] == ["M-1"]
    assert R.DROPPED_LOWER_PRIORITY in {b.code for b in p.unassigned[0].blocking_reasons}


# --------------------------------------------------------------------- constraints (4.2, 4.3)
def test_crew_rest_forces_a_choice_even_with_spare_aircraft() -> None:
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1")],
                missions=[mission("M-1", priority=3, weight=35), mission("M-2", priority=1,
                                                                         weight=100)])
    p = cp(scn)
    assert covered(p) == ["M-2"] and validate_plan(scn, p) == []


def test_crew_duty_budget_limits_total_flying() -> None:
    # 720 - 600 carried = 120 left: one 86 min sortie fits, two do not (and rest forbids it anyway)
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2")],
                crew=[crew("C-1", duty_minutes_last_24h=600), crew("C-2", duty_minutes_last_24h=600)],
                missions=[mission("M-1"), mission("M-2")])
    p = cp(scn)
    assert covered(p) == ["M-1", "M-2"]  # two crews, one sortie each
    assert validate_plan(scn, p) == []


def test_stock_is_shared() -> None:
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1"), crew("C-2")],
                missions=[mission("M-1", priority=3, weight=35), mission("M-2")],
                weapon_stocks=[WeaponStock(base_id="B1", item_type="AA_STORE_T1",
                                           qty_available=4, provenance=PROV)])
    p = cp(scn)
    assert covered(p) == ["M-2"] and validate_plan(scn, p) == []


def test_runway_capacity_staggers_takeoffs() -> None:
    from planning_world import base

    window = dict(window_start_min=100, window_end_min=100 + 13 + 60 + 30)
    scn = world(
        bases=[base(runways=1)], aircraft=[aircraft(f"A-{i}") for i in (1, 2, 3)],
        crew=[crew(f"C-{i}") for i in (1, 2, 3)],
        missions=[mission(f"M-{i}", **window) for i in (1, 2, 3)],
        weapon_stocks=[WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=99,
                                   provenance=PROV)],
    )
    p = cp(scn)
    assert validate_plan(scn, p) == []
    from collections import Counter

    per_slot = Counter(a.takeoff_min // 15 for a in p.assignments)
    assert max(per_slot.values(), default=0) <= 2


def test_multi_aircraft_mission_is_all_or_nothing() -> None:
    two = mission("M-1", priority=1, weight=100, aircraft_required=2)
    one = mission("M-2", priority=3, weight=35)
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1")],
                missions=[two, one])  # only one crew: the 2-aircraft mission cannot be crewed
    p = cp(scn)
    assert covered(p) == ["M-2"] and len(p.assignments) == 1
    both = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1"), crew("C-2")],
                 missions=[two, one])
    q = cp(both)
    assert covered(q) == ["M-1"] and len(q.assignments) == 2  # 2 aircraft, 2 crews: M-1 only
    assert validate_plan(both, q) == []


def test_missions_the_matrix_rules_out_are_reported_with_matrix_reasons() -> None:
    scn = world(crew=[])
    p = cp(scn)
    assert p.assignments == []
    (u,) = p.unassigned
    assert R.NO_QUALIFIED_CREW in {b.code for b in u.blocking_reasons}
    assert R.DROPPED_LOWER_PRIORITY not in {b.code for b in u.blocking_reasons}


# --------------------------------------------------------------------- solver behaviour (4.5)
def test_assignments_are_explained() -> None:
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2", hours_since_maintenance=90)],
                crew=[crew("C-1"), crew("C-2")])
    p = cp(scn)
    (a,) = p.assignments
    assert a.reasons == [R.ASSIGNED_BEST_SCORE]
    assert "A-1" in a.explanation and "CP-SAT" in a.explanation and "A-2" in a.explanation
    assert "total" in a.explanation


def test_same_seed_and_workers_give_the_same_plan() -> None:
    scn = generate_scenario(GeneratorParams(seed=3))
    key = lambda p: [(a.id, a.aircraft_id, tuple(a.crew_ids), a.takeoff_min, a.loadout_id)  # noqa: E731
                     for a in p.assignments]
    one = cp(scn, time_limit_s=30)
    two = cp(scn, time_limit_s=30)
    assert one.solver.status == "OPTIMAL" and key(one) == key(two)
    assert one.solver.objective == two.solver.objective


def test_time_limit_is_respected_and_status_and_gap_are_reported() -> None:
    scn = generate_scenario(GeneratorParams(seed=1))
    p = cp(scn, time_limit_s=1.0)
    # 1 s can be too short to find any solution; then the greedy plan is returned and the status
    # says so explicitly (it is never passed off as an optimiser result).
    assert p.solver.status in ("OPTIMAL", "FEASIBLE") or p.solver.status.startswith("FALLBACK_GREEDY")
    assert p.solver.wall_ms < 1000 + 4000  # limit + matrix build + extraction slack
    assert validate_plan(scn, p) == []
    longer = cp(scn, time_limit_s=12.0, num_workers=4)
    assert longer.solver.status in ("OPTIMAL", "FEASIBLE") and longer.solver.gap is not None
    assert longer.solver.objective is not None and validate_plan(scn, longer) == []


def test_without_the_greedy_hint_the_plan_is_still_valid() -> None:
    scn = generate_scenario(GeneratorParams(seed=3, n_missions=25))
    p = cp(scn, use_greedy_hint=False, time_limit_s=3)
    assert validate_plan(scn, p) == []


def test_candidate_caps_shrink_the_model_but_keep_plans_valid() -> None:
    scn = generate_scenario(GeneratorParams(seed=3, n_missions=25))
    p = cp(scn, max_aircraft_per_mission=2, slots_per_option=1, time_limit_s=3)
    assert validate_plan(scn, p) == []


# ------------------------------------------------------- Phase 4 DoD: 20 seeds, zero violations
@pytest.mark.parametrize("seed", range(1, 21))
def test_cpsat_plans_on_seeded_scenarios_are_valid_and_not_worse_than_greedy(seed: int) -> None:
    scn = generate_scenario(GeneratorParams(seed=seed))
    ctx = PlanningContext(scn)
    greedy = greedy_plan(ctx, "sc", "greedy_priority")
    p = solve(ctx, "sc", SolveParams(time_limit_s=2.0, num_workers=1, seed=seed))
    assert validate_plan(scn, p) == [], seed
    # If the solver found nothing in time the greedy plan is returned (status says so); the
    # guarantee below holds either way, and the next test shows a real solve end to end.
    w = get_weights("coverage_first")
    assert plan_objective(ctx, p, w) >= plan_objective(ctx, greedy, w), seed
    assert p.kpis.priority_weighted_coverage >= greedy.kpis.priority_weighted_coverage - 1e-9
    assert {a.mission_id for a in p.assignments}.isdisjoint({u.mission_id for u in p.unassigned})


def test_a_mid_size_scenario_gets_a_real_solve_that_improves_on_greedy() -> None:
    scn = generate_scenario(GeneratorParams(seed=3))
    ctx = PlanningContext(scn)
    greedy = greedy_plan(ctx, "sc", "greedy_priority")
    p = solve(ctx, "sc", SolveParams(time_limit_s=40, num_workers=1, seed=3))
    assert p.solver.status == "OPTIMAL" and p.solver.gap == 0
    w = get_weights("coverage_first")
    assert plan_objective(ctx, p, w) > plan_objective(ctx, greedy, w)
    assert p.kpis.priority_weighted_coverage >= greedy.kpis.priority_weighted_coverage
    assert p.solver.objective == plan_objective(ctx, p, w)  # the reported objective is the plan's


# ------------------------------------------------------------------------ weights and diff
def test_weight_presets_load_and_scale() -> None:
    assert {"coverage_first", "risk_averse", "stability_first"} <= set(preset_names())
    w = get_weights("coverage_first")
    assert w.coverage_points(100) == 100000 and w.risk_points(0.028) == 280
    assert w.cost_points(86) == 86 and w.early_points(6) == 6 and SCALE == 10
    assert get_weights("risk_averse").risk_points(0.1) == 4 * w.risk_points(0.1)
    assert get_weights("stability_first").stability_points() > w.stability_points()
    with pytest.raises(KeyError, match="unknown weight preset"):
        get_weights("nope")


def test_diff_between_plans() -> None:
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1"), crew("C-2")])
    ctx = PlanningContext(scn)
    a = greedy_plan(ctx, "sc", "greedy_priority")
    assert diff_plans(a, a).n_changes == 0
    moved = a.model_copy(update={"assignments": [
        a.assignments[0].model_copy(update={"aircraft_id": "A-2", "takeoff_min": 105})]})
    d = diff_plans(a, moved)
    assert d.n_changes == 1 and {c.field for c in d.changed} == {"aircraft_id", "takeoff_min"}
    empty = a.model_copy(update={"assignments": []})
    assert diff_plans(a, empty).removed == [a.assignments[0].id]
    assert diff_plans(empty, a).added == [a.assignments[0].id]
