"""Baseline planners (Task 3.13) and the independent validator (Task 3.12).

Includes the Phase 3 Definition of Done: greedy plans on 20 seeded scenarios all pass `validate`
with zero violations, and the validator is shown to catch deliberately broken plans."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from planning_world import (
    PROV,
    aircraft,
    base,
    crew,
    mission,
    threat,
    weather,
    world,
    zone,
)

from app.models.entities import WeaponStock
from app.models.enums import AirspaceKind, ReasonCode
from app.models.plans import Assignment, Plan
from app.models.scenario import GeneratorParams, ScenarioFile
from app.planning.assemble import assemble_plan, make_assignment
from app.planning.config import PlanningConfig
from app.planning.context import PlanningContext
from app.planning.feasibility import build_matrix
from app.planning.greedy import plan
from app.planning.validate import validate_plan
from app.sim.generate import generate_scenario

R = ReasonCode


def run(scn: ScenarioFile, planner: str = "greedy_priority") -> tuple[PlanningContext, Plan]:
    ctx = PlanningContext(scn)
    return ctx, plan(ctx, "sc_test", planner)  # type: ignore[arg-type]


def kinds(violations) -> set[str]:
    return {v.code for v in violations}


def manual(ctx: PlanningContext, plan_: Plan, **replace) -> Plan:
    return plan_.model_copy(update=replace)


def sortie(ctx, mid="M-1", aid="A-1", cid=("C-1",), takeoff=100, loadout="L-AA", seq=1,
           land_offset=86) -> Assignment:
    from app.models.plans import RiskBreakdown

    return make_assignment(ctx, seq, mid, aid, loadout, takeoff, land_offset, list(cid),
                           RiskBreakdown(threat=0, weather=0, service=0, total=0), "manual")


def plan_of(ctx: PlanningContext, assignments: list[Assignment]) -> Plan:
    return assemble_plan(ctx, "sc_test", "manual", assignments, [], 0, "MANUAL")


# --------------------------------------------------------------------------- baselines, tiny
def test_single_mission_is_assigned_and_validates() -> None:
    scn = world()
    ctx, p = run(scn)
    (a,) = p.assignments
    assert (a.mission_id, a.aircraft_id, a.crew_ids, a.loadout_id) == ("M-1", "A-1", ["C-1"], "L-AA")
    assert a.takeoff_min == 90 and a.land_min == 90 + 86 and a.base_from == a.base_to == "B1"
    assert [r.value for r in a.reasons] == ["ASSIGNED_BEST_SCORE"] and "A-1" in a.explanation
    assert len(a.route) == 3 and p.status.value == "draft" and p.data_label == "synthetic"
    assert p.kpis.missions_covered == 1 and p.kpis.priority_weighted_coverage == 1.0
    assert p.kpis.total_flight_minutes == 86 and p.kpis.aircraft_utilisation == 1.0
    assert validate_plan(scn, p) == []


def test_priority_planner_prefers_the_higher_priority_and_fifo_follows_request_order() -> None:
    # One aircraft and one crew, two overlapping missions: only one can fly.
    low, high = mission("M-1", priority=3, weight=35), mission("M-2", priority=1, weight=100)
    scn = world(missions=[low, high])
    _, greedy = run(scn, "greedy_priority")
    _, fifo = run(scn, "fifo")
    assert [a.mission_id for a in greedy.assignments] == ["M-2"]
    assert [a.mission_id for a in fifo.assignments] == ["M-1"]
    assert greedy.kpis.priority_weighted_coverage == pytest.approx(100 / 135, abs=1e-4)
    assert fifo.kpis.priority_weighted_coverage == pytest.approx(35 / 135, abs=1e-4)
    assert validate_plan(scn, greedy) == [] and validate_plan(scn, fifo) == []


def test_the_loser_is_unassigned_with_a_resource_contention_reason() -> None:
    scn = world(missions=[mission("M-1", priority=3), mission("M-2", priority=1)])
    _, p = run(scn)
    (u,) = p.unassigned
    assert u.mission_id == "M-1"
    codes = {b.code for b in u.blocking_reasons}
    assert codes & {R.TURNAROUND_CONFLICT, R.CREW_REST_VIOLATION}
    assert "M-1" in u.explanation and "not assigned" in u.explanation


def test_a_second_aircraft_and_crew_lets_both_fly() -> None:
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1"), crew("C-2")],
                missions=[mission("M-1"), mission("M-2")])
    _, p = run(scn)
    assert {a.mission_id for a in p.assignments} == {"M-1", "M-2"}
    assert {a.aircraft_id for a in p.assignments} == {"A-1", "A-2"}
    assert {c for a in p.assignments for c in a.crew_ids} == {"C-1", "C-2"}
    assert validate_plan(scn, p) == []


def test_multi_aircraft_mission_is_all_or_nothing() -> None:
    both = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1")],  # one crew only
                 missions=[mission(aircraft_required=2)])
    _, p = run(both)
    assert p.assignments == [] and p.unassigned[0].mission_id == "M-1"  # no half-assignment
    ok = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1"), crew("C-2")],
               missions=[mission(aircraft_required=2)])
    _, q = run(ok)
    assert len(q.assignments) == 2 and q.kpis.missions_covered == 1
    assert validate_plan(ok, q) == []


def test_stock_is_shared_across_sorties() -> None:
    # stock for exactly one sortie (4 items); two aircraft, two crew, two missions
    scn = world(
        aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1"), crew("C-2")],
        missions=[mission("M-1"), mission("M-2")],
        weapon_stocks=[WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=4,
                                   provenance=PROV)],
    )
    _, p = run(scn)
    assert len(p.assignments) == 1
    assert R.NO_LOADOUT_STOCK in {b.code for b in p.unassigned[0].blocking_reasons}


def test_runway_capacity_spreads_takeoffs_across_slots() -> None:
    # runways=1, 2 ops per slot: three missions with the same single slot can't all leave at once
    window = dict(window_start_min=100, window_end_min=100 + 13 + 60 + 15)
    scn = world(
        bases=[base(runways=1)], aircraft=[aircraft(f"A-{i}") for i in (1, 2, 3)],
        crew=[crew(f"C-{i}") for i in (1, 2, 3)],
        missions=[mission(f"M-{i}", **window) for i in (1, 2, 3)],
        weapon_stocks=[WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=99,
                                   provenance=PROV)],
    )
    _, p = run(scn)
    assert validate_plan(scn, p) == []
    per_slot = Counter(a.takeoff_min // 15 for a in p.assignments)
    assert len(p.assignments) == 3 and max(per_slot.values()) == 2  # capacity 2 ops per slot
    assert sorted(a.takeoff_min for a in p.assignments) == [90, 90, 105]  # the third waits a slot


def test_infeasible_mission_is_unassigned_with_dominant_reasons_and_counts() -> None:
    scn = world(crew=[], weather=weather(visibility_km=0.5))
    _, p = run(scn)
    (u,) = p.unassigned
    assert {b.code for b in u.blocking_reasons} >= {R.NO_QUALIFIED_CREW}
    assert u.blocking_reasons[0].count >= 1 and "Dominant blockers" in u.explanation


def test_planners_are_deterministic() -> None:
    scn = generate_scenario(GeneratorParams(seed=4))
    _, a = run(scn)
    _, b = run(scn)
    key = lambda p: [(x.id, x.aircraft_id, tuple(x.crew_ids), x.takeoff_min, x.loadout_id)  # noqa: E731
                     for x in p.assignments]
    assert key(a) == key(b)


# ----------------------------------------------------- Definition of Done: 20 seeded scenarios
@pytest.mark.parametrize("seed", range(1, 21))
@pytest.mark.parametrize("planner", ["greedy_priority", "fifo"])
def test_greedy_plans_on_seeded_scenarios_have_zero_violations(seed: int, planner: str) -> None:
    scn = generate_scenario(GeneratorParams(seed=seed))
    ctx = PlanningContext(scn)
    matrix = build_matrix(ctx)
    p = plan(ctx, "sc_test", planner, matrix)  # type: ignore[arg-type]
    assert validate_plan(scn, p) == [], (seed, planner)
    covered = p.kpis.missions_covered
    assert covered == len({a.mission_id for a in p.assignments if
                           sum(b.mission_id == a.mission_id for b in p.assignments)
                           >= ctx.missions[a.mission_id].aircraft_required})
    assigned = {a.mission_id for a in p.assignments}
    assert assigned.isdisjoint({u.mission_id for u in p.unassigned})
    assert assigned | {u.mission_id for u in p.unassigned} == set(matrix.missions)


def test_plans_on_fused_snapshots_also_validate() -> None:
    from datetime import timedelta

    from app.ingest.adapters import SecondarySyntheticAdapter, SyntheticAdapter
    from app.ingest.fusion import fuse

    scn = generate_scenario(GeneratorParams(seed=2))
    now = scn.scenario.t0 + timedelta(minutes=0)
    state = fuse([SyntheticAdapter(scn).fetch(), SecondarySyntheticAdapter(scn).fetch()], now)
    fused = scn.model_copy(update=dict(state.entities))
    ctx = PlanningContext(fused, fusion_meta=state.meta)
    p = plan(ctx, "sc_f", "greedy_priority")
    assert validate_plan(fused, p, fusion_meta=state.meta) == []


@pytest.mark.parametrize("seed", range(1, 21))
def test_every_intentionally_infeasible_mission_is_flagged_with_its_intended_reason(seed: int) -> None:
    scn = generate_scenario(GeneratorParams(seed=seed))
    matrix = build_matrix(PlanningContext(scn))
    for hard in scn.scenario.hard_cases:
        feas = matrix.missions[hard.mission_id]
        found = {f.code for f in feas.mission_level} | set(feas.tally)
        assert hard.intended_reason in found, (seed, hard.mission_id, hard.intended_reason)
        assert not feas.coverable


# ------------------------------------------------------------- the validator catches breakage
def test_validator_accepts_a_correct_manual_plan() -> None:
    scn = world()
    ctx = PlanningContext(scn)
    assert validate_plan(scn, plan_of(ctx, [sortie(ctx)])) == []


def test_validator_flags_each_class_of_violation() -> None:
    scn = world()
    ctx = PlanningContext(scn)

    def check(assignments, expected: str, scenario=scn, **kw) -> None:
        got = kinds(validate_plan(scenario, plan_of(PlanningContext(scenario), assignments), **kw))
        assert expected in got, (expected, got)

    check([sortie(ctx, takeoff=10, land_offset=86)], "TIME_WINDOW_UNREACHABLE")  # on station early
    check([sortie(ctx, takeoff=100, land_offset=90)], "TIMING_INCONSISTENT")
    check([sortie(ctx, loadout="NONE")], "LOADOUT_INCOMPATIBLE")
    check([sortie(ctx, cid=())], "NO_QUALIFIED_CREW")
    check([sortie(ctx, cid=("C-1", "C-1"))], "NO_QUALIFIED_CREW")
    check([sortie(ctx, takeoff=100), sortie(ctx, mid="M-1", takeoff=120, seq=2)], "TURNAROUND_CONFLICT")
    check([sortie(ctx, takeoff=100), sortie(ctx, takeoff=300, seq=2)], "CREW_REST_VIOLATION")
    check([sortie(ctx)], "PARTIAL_MISSION", scenario=world(missions=[mission(aircraft_required=2)]))


def test_validator_flags_unknown_references_and_bad_status() -> None:
    scn = world()
    ctx = PlanningContext(scn)
    bad = sortie(ctx).model_copy(update={"aircraft_id": "A-404"})
    assert "UNKNOWN_REFERENCE" in kinds(validate_plan(scn, plan_of(ctx, [bad])))
    down = world(aircraft=[aircraft(status="UNSERVICEABLE")])
    assert "AIRCRAFT_UNSERVICEABLE" in kinds(validate_plan(down, plan_of(ctx, [sortie(ctx)])))
    worn = world(aircraft=[aircraft(hours_since_maintenance=99.5)])
    assert "MAINTENANCE_DUE" in kinds(validate_plan(worn, plan_of(ctx, [sortie(ctx)])))
    early = validate_plan(scn, plan_of(ctx, [sortie(ctx, takeoff=100)]), now_min=200)
    assert "TAKEOFF_IN_PAST" in kinds(early)


def test_validator_flags_range_weather_airspace_threat_and_crew_problems() -> None:
    ctx = PlanningContext(world())

    def v(**over):
        scn = world(**over)
        return kinds(validate_plan(scn, plan_of(ctx, [sortie(ctx)])))

    assert "WEATHER_BELOW_MINIMA_BASE" in v(weather=weather(visibility_km=0.5))
    assert "WEATHER_BELOW_MINIMA_TARGET" in v(
        bases=[base(), base("B2", lat=21.45, lon=78.0)], weather=weather() + weather("B2", visibility_km=0.5))
    assert "AIRSPACE_CONFLICT" in v(airspace=[zone(AirspaceKind.NO_FLY, 20.75, 78.0, 0.2)])
    assert "AIRSPACE_CONFLICT" not in v(airspace=[
        zone(AirspaceKind.DANGER, 20.75, 78.0, 0.2, id_="Z-D"),
        zone(AirspaceKind.CORRIDOR, 20.75, 78.0, 0.4, id_="Z-C")])
    assert "THREAT_RISK_EXCEEDS_LIMIT" in v(threats=[threat()])
    assert "NO_QUALIFIED_CREW" in v(crew=[crew(status="SICK")])
    assert "NO_QUALIFIED_CREW" in v(crew=[crew(qualifications=["TPT-B"])])
    assert "CREW_REST_VIOLATION" in v(crew=[crew(last_duty_end_min=-300)])  # takeoff 100 < 300
    assert "CREW_DUTY_LIMIT" in v(crew=[crew(duty_minutes_last_24h=700)])
    assert "OUT_OF_RANGE" in v(aircraft_types=[__import__("planning_world").ftr(combat_radius_km=100)])
    assert "INSUFFICIENT_FUEL_ENDURANCE" in v(
        aircraft_types=[__import__("planning_world").ftr(endurance_min=100)])


def test_validator_flags_stock_and_runway_overflow() -> None:
    scn = world(
        bases=[base(runways=1)], aircraft=[aircraft(f"A-{i}") for i in (1, 2, 3)],
        crew=[crew(f"C-{i}") for i in (1, 2, 3)], missions=[mission(f"M-{i}") for i in (1, 2, 3)],
        weapon_stocks=[WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=8,
                                   provenance=PROV)],
    )
    ctx = PlanningContext(scn)
    rows = [sortie(ctx, mid=f"M-{i}", aid=f"A-{i}", cid=(f"C-{i}",), takeoff=105, seq=1)
            for i in (1, 2, 3)]
    got = kinds(validate_plan(scn, plan_of(ctx, rows)))
    assert "NO_LOADOUT_STOCK" in got  # 12 items used, 8 in stock
    assert "BASE_RUNWAY_CAPACITY" in got  # 3 takeoffs in one slot, capacity 2


def test_validator_flags_a_changed_frozen_assignment() -> None:
    scn = world()
    ctx = PlanningContext(scn)
    airborne = sortie(ctx).model_copy(update={"frozen": True})
    parent = plan_of(ctx, [airborne])
    moved = sortie(ctx, takeoff=120)
    assert validate_plan(scn, plan_of(ctx, [moved]), parent=parent)
    assert "FROZEN_AIRBORNE" in kinds(validate_plan(scn, plan_of(ctx, [moved]), parent=parent))
    kept = plan_of(ctx, [airborne])
    assert "FROZEN_AIRBORNE" not in kinds(validate_plan(scn, kept, parent=parent))
    gone = plan_of(ctx, [])
    assert "FROZEN_AIRBORNE" in kinds(validate_plan(scn, gone, parent=parent))


def test_validator_flags_inconsistent_plans_and_duplicate_ids() -> None:
    scn = world()
    ctx = PlanningContext(scn)
    p = plan_of(ctx, [sortie(ctx), sortie(ctx)])
    assert "DUPLICATE_ASSIGNMENT_ID" in kinds(validate_plan(scn, p))
    from app.models.plans import UnassignedMission

    both = plan_of(ctx, [sortie(ctx)]).model_copy(
        update={"unassigned": [UnassignedMission(mission_id="M-1", blocking_reasons=[])]})
    assert "INCONSISTENT_PLAN" in kinds(validate_plan(scn, both))


def test_validator_does_not_import_the_planner_modules() -> None:
    src = (Path(__file__).resolve().parents[1] / "app" / "planning" / "validate.py").read_text()
    for forbidden in ("planning.feasibility", "planning.resources", "planning.greedy",
                      "planning.risk"):
        assert forbidden not in src


def test_a_plan_from_a_stricter_config_may_fail_a_looser_validation_but_not_vice_versa() -> None:
    scn = world(aircraft=[aircraft(status="DEGRADED")])
    ctx = PlanningContext(scn)
    p = plan_of(ctx, [sortie(ctx)])
    assert validate_plan(scn, p) == []
    strict = validate_plan(scn, p, cfg=PlanningConfig(allow_degraded=False))
    assert "AIRCRAFT_UNSERVICEABLE" in kinds(strict)


# ------------------------------------------------------------------- determinism across processes
HASH = (
    "import hashlib;"
    "from app.sim.generate import generate_scenario;"
    "from app.models.scenario import GeneratorParams;"
    "from app.planning.context import PlanningContext;"
    "from app.planning.greedy import plan;"
    "s = generate_scenario(GeneratorParams(seed=6));"
    "p = plan(PlanningContext(s), 'sc', 'greedy_priority');"
    "rows = [(a.id, a.aircraft_id, tuple(a.crew_ids), a.takeoff_min, a.loadout_id) for a in p.assignments];"
    "u = [(x.mission_id, [(b.code.value, b.count) for b in x.blocking_reasons]) for x in p.unassigned];"
    "print(hashlib.sha256(repr((rows, u)).encode()).hexdigest())"
)


def test_plans_are_identical_across_processes_and_hash_seeds() -> None:
    backend = Path(__file__).resolve().parents[1]
    outs = {
        subprocess.run([sys.executable, "-c", HASH], cwd=backend,
                       env={**os.environ, "PYTHONHASHSEED": hs}, capture_output=True, text=True,
                       check=True).stdout.strip()
        for hs in ("0", "7", "99")
    }
    assert len(outs) == 1
