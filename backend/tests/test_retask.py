"""Retasking (Tasks 5.2-5.6, 5.10): frozen set, affected set, repair, stability, variants, ranking.

The world: aircraft A-1, A-2, crew C-1..C-3 (all at B1), missions
  M-1 priority 2, window T+100..400   M-2 priority 2, window T+600..900   M-3 priority 3, same.
The greedy parent plan (worked out by hand) is  M-1: A-1@90 (C-1)  M-2: A-1@600 (C-2)
M-3: A-2@600 (C-3).  If A-1 fails at T+300, M-1 (taken off at T+90) is frozen, M-2 is the only
affected sortie, and the cheapest repair is M-2 on A-2 at T+750 (after M-3 lands and turns round).
"""

from __future__ import annotations

import pytest
from planning_world import (
    PROV,
    aircraft,
    crew,
    mission,
    weather,
    world,
)

from app.models.entities import Event, WeaponStock
from app.models.enums import EventOrigin, EventType, PlanStatus
from app.models.enums import ReasonCode as R
from app.models.plans import Plan
from app.models.scenario import ScenarioFile
from app.planning import retask as rt
from app.planning.context import PlanningContext
from app.planning.feasibility import build_matrix
from app.planning.greedy import plan as greedy_plan
from app.planning.retask import RetaskParams, propose
from app.planning.validate import validate_plan
from app.sim.events import apply_event

WINDOW = {"window_start_min": 600, "window_end_min": 900}


def base_world() -> ScenarioFile:
    return world(
        aircraft=[aircraft("A-1"), aircraft("A-2")],
        crew=[crew("C-1"), crew("C-2"), crew("C-3")],
        missions=[
            mission("M-1", priority=2, weight=60),
            mission("M-2", priority=2, weight=60, **WINDOW),
            mission("M-3", priority=3, weight=35, **WINDOW),
        ],
        weapon_stocks=[WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=99,
                                   provenance=PROV)],
    )


def parent_plan(scn: ScenarioFile) -> Plan:
    p = greedy_plan(PlanningContext(scn), "sc_t", "greedy_priority")
    return p.model_copy(update={"status": PlanStatus.APPROVED})


def event(type_: EventType, payload: dict, time_min: int) -> Event:
    return Event(id="EV-001", type=type_, time_min=time_min, payload=payload, source="USER",
                 created_by=EventOrigin.USER, provenance=PROV)


def run(scn: ScenarioFile, parent: Plan, ev: Event, **kw):
    after = apply_event(scn, ev)
    ctx = PlanningContext(after, now_min=ev.time_min)
    params = RetaskParams(time_budget_s=kw.pop("budget", 12), num_workers=1, **kw)
    return ctx, after, propose(ctx, "sc_t", parent, ev, params)


A1_DOWN = (EventType.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-1", "until_min": None})


def by_mission(plan: Plan) -> dict[str, list]:
    out: dict[str, list] = {}
    for a in plan.assignments:
        out.setdefault(a.mission_id, []).append(a)
    return out


# ---------------------------------------------------------------------------- the parent
def test_parent_plan_is_what_the_hand_computation_says() -> None:
    scn = base_world()
    p = parent_plan(scn)
    got = {a.mission_id: (a.aircraft_id, a.takeoff_min, a.crew_ids) for a in p.assignments}
    assert got == {"M-1": ("A-1", 90, ["C-1"]), "M-2": ("A-1", 600, ["C-2"]),
                   "M-3": ("A-2", 600, ["C-3"])}


# ------------------------------------------------------------------------ freeze + affected
def test_freeze_marks_sorties_that_have_taken_off() -> None:
    p = parent_plan(base_world())
    frozen = rt.freeze(p, 90)  # takeoff <= now is frozen (inclusive)
    assert {a.mission_id for a in frozen.assignments if a.frozen} == {"M-1"}
    assert all(a.reasons == [R.FROZEN_AIRBORNE] for a in frozen.assignments if a.frozen)
    assert not any(a.frozen for a in rt.freeze(p, 89).assignments)
    assert all(a.frozen for a in rt.freeze(p, 5000).assignments)
    assert not any(a.frozen for a in p.assignments)  # the input is not modified


def test_affected_set_is_exactly_the_invalidated_sortie() -> None:
    scn = base_world()
    p = parent_plan(scn)
    ev = event(*A1_DOWN, 300)
    ctx = PlanningContext(apply_event(scn, ev), now_min=300)
    aff = rt.find_affected(ctx, rt.freeze(p, 300), ev)
    assert aff.ids == {"S-M-2-1"}  # M-1 is frozen history; M-3 does not use A-1
    assert {v.code for v in aff.violations["S-M-2-1"]} == {"AIRCRAFT_UNSERVICEABLE"}


def test_a_priority_change_marks_that_missions_sorties_affected_without_a_violation() -> None:
    scn = base_world()
    ev = event(EventType.PRIORITY_CHANGE, {"mission_id": "M-3", "new_priority": 1}, 300)
    ctx = PlanningContext(apply_event(scn, ev), now_min=300)
    aff = rt.find_affected(ctx, rt.freeze(parent_plan(scn), 300), ev)
    assert aff.violations == {} and aff.priority_changed == {"S-M-3-1"}


def test_explanation_does_not_present_a_violation_code_as_the_events_cause() -> None:
    scn = base_world()
    parent = parent_plan(scn)
    ev = event(EventType.PRIORITY_CHANGE, {"mission_id": "M-3", "new_priority": 1}, 300)
    aff = rt.Affected(violations={"S-M-2-1": [rt.Violation(
        code="AIRCRAFT_UNSERVICEABLE", message="x", assignment_id="S-M-2-1", mission_id="M-2")]},
        priority_changed={"S-M-3-1"})
    from app.planning.diff import diff_plans
    text = rt.explain_proposal(ev, parent, parent, diff_plans(parent, parent), aff, "p", False)
    assert "priority changed" in text
    assert "violations found in the current plan: AIRCRAFT_UNSERVICEABLE" in text
    assert "affected (AIRCRAFT_UNSERVICEABLE)" not in text


# --------------------------------------------------------------------------- greedy repair
def test_greedy_repair_keeps_everything_unaffected_and_re_places_the_rest() -> None:
    scn = base_world()
    p = parent_plan(scn)
    ev = event(*A1_DOWN, 300)
    after = apply_event(scn, ev)
    ctx = PlanningContext(after, now_min=300)
    frozen = rt.freeze(p, 300)
    aff = rt.find_affected(ctx, frozen, ev)
    repair = rt.greedy_repair(ctx, "sc_t", frozen, aff, build_matrix(ctx))
    rows = {a.mission_id: a for a in repair.assignments}
    assert rows["M-1"].frozen and (rows["M-1"].aircraft_id, rows["M-1"].takeoff_min) == ("A-1", 90)
    assert (rows["M-3"].aircraft_id, rows["M-3"].takeoff_min) == ("A-2", 600)  # untouched
    assert (rows["M-2"].aircraft_id, rows["M-2"].takeoff_min) == ("A-2", 750)  # re-placed
    assert validate_plan(after, repair, now_min=300, parent=frozen) == []


# ------------------------------------------------------------------------ the full proposal
def test_proposals_keep_frozen_sorties_unchanged_and_all_pass_validate() -> None:
    scn = base_world()
    p = parent_plan(scn)
    ev = event(*A1_DOWN, 300)
    ctx, after, (drafts, affected) = run(scn, p, ev)
    assert drafts and affected.ids == {"S-M-2-1"}
    parent_m1 = by_mission(p)["M-1"][0]
    frozen_parent = rt.freeze(p, 300)
    for d in drafts:
        m1 = by_mission(d.plan)["M-1"][0]
        assert m1.frozen and m1.id == parent_m1.id and m1.reasons == [R.FROZEN_AIRBORNE]
        assert (m1.aircraft_id, m1.takeoff_min, m1.crew_ids, m1.loadout_id) == (
            parent_m1.aircraft_id, parent_m1.takeoff_min, parent_m1.crew_ids, parent_m1.loadout_id)
        assert validate_plan(after, d.plan, now_min=300, parent=frozen_parent) == []
        assert d.plan.status is PlanStatus.PROPOSED and d.plan.parent_plan_id == p.id
        assert d.plan.version == p.version + 1
        # nobody flies A-1 after it failed (apart from the frozen sortie)
        assert all(a.aircraft_id != "A-1" for a in d.plan.assignments if not a.frozen)


def test_stability_preset_changes_only_what_the_event_forces() -> None:
    scn = base_world()
    p = parent_plan(scn)
    ctx, after, (drafts, affected) = run(scn, p, event(*A1_DOWN, 300))
    stable = next(d for d in drafts if d.preset == "stability_first")
    assert stable.diff.n_changes == 1 and len(affected.ids) == 1  # changes <= affected
    changed = {c.assignment_id for c in stable.diff.changed}
    assert changed == {"S-M-2-1"} and stable.diff.added == [] and stable.diff.removed == []
    rows = {a.mission_id: a for a in stable.plan.assignments}
    assert (rows["M-2"].aircraft_id, rows["M-2"].takeoff_min) == ("A-2", 750)
    assert rows["M-3"].reasons == [R.PRESERVED_EXISTING]  # unaffected: same sortie, same crew
    assert rows["M-3"].crew_ids == ["C-3"] and rows["M-3"].takeoff_min == 600
    assert rows["M-2"].reasons == [R.CHANGED_DUE_TO_EVENT]
    assert "became unserviceable at T+300" in rows["M-2"].explanation
    assert "was A-1 at T+600" in rows["M-2"].explanation
    assert stable.diff.coverage_delta == 0 and not stable.fallback


def test_proposals_are_ranked_by_a_score_whose_components_are_shown() -> None:
    scn = base_world()
    ctx, after, (drafts, _) = run(scn, parent_plan(scn), event(*A1_DOWN, 300))
    totals = [d.score_breakdown["total"] for d in drafts]
    assert totals == sorted(totals, reverse=True)
    for d in drafts:
        b = d.score_breakdown
        assert set(b) == {"coverage", "risk", "stability", "total"}
        assert b["coverage"] == pytest.approx(100 * d.diff.coverage_delta, abs=1e-3)
        assert b["risk"] == pytest.approx(-20 * d.diff.risk_delta, abs=1e-3)
        assert b["stability"] == -d.diff.n_changes
        assert b["total"] == pytest.approx(b["coverage"] + b["risk"] + b["stability"], abs=1e-3)
        assert d.explanation.startswith("A-1 became unserviceable at T+300")
        assert "sortie(s) already under way are unchanged" in d.explanation


def test_identical_plans_from_different_presets_are_merged() -> None:
    scn = base_world()
    ctx, after, (drafts, _) = run(scn, parent_plan(scn), event(*A1_DOWN, 300))
    sigs = [frozenset((a.mission_id, a.aircraft_id, a.takeoff_min, tuple(a.crew_ids),
                       a.loadout_id) for a in d.plan.assignments) for d in drafts]
    assert len(sigs) == len(set(sigs))
    assert len(drafts) <= 3


def test_retasking_is_deterministic_with_fixed_workers_and_seed() -> None:
    scn = base_world()
    p = parent_plan(scn)
    ev = event(*A1_DOWN, 300)
    key = lambda ds: [(d.preset, d.diff.n_changes, d.score_breakdown["total"],  # noqa: E731
                       [(a.id, a.aircraft_id, a.takeoff_min) for a in d.plan.assignments])
                      for d in ds[0]]
    assert key(run(scn, p, ev)[2]) == key(run(scn, p, ev)[2])


# ------------------------------------------------------------------------ other event types
def test_cancelled_mission_is_dropped_but_a_cancelled_airborne_sortie_stays() -> None:
    scn = base_world()
    p = parent_plan(scn)
    ctx, after, (drafts, affected) = run(
        scn, p, event(EventType.MISSION_CANCELLED, {"mission_id": "M-2"}, 300))
    assert affected.ids == {"S-M-2-1"}
    for d in drafts:
        assert "M-2" not in by_mission(d.plan)
        assert d.diff.removed == ["S-M-2-1"]
    ctx2, after2, (drafts2, aff2) = run(
        scn, p, event(EventType.MISSION_CANCELLED, {"mission_id": "M-1"}, 300))
    assert aff2.ids == set()  # M-1 already took off: its sortie is history, not affected
    for d in drafts2:
        assert by_mission(d.plan)["M-1"][0].frozen
        assert validate_plan(after2, d.plan, now_min=300, parent=rt.freeze(p, 300)) == []


def test_a_new_urgent_mission_gets_a_sortie_in_at_least_one_proposal() -> None:
    scn = base_world()
    p = parent_plan(scn)
    new = mission("M-9", priority=1, weight=100, **WINDOW)
    ctx, after, (drafts, affected) = run(
        scn, p, event(EventType.NEW_MISSION, {"mission": new.model_dump(mode="json")}, 300))
    assert any("M-9" in by_mission(d.plan) for d in drafts)
    best = max((d for d in drafts if "M-9" in by_mission(d.plan)),
               key=lambda d: d.plan.kpis.priority_weighted_coverage)
    assert best.diff.coverage_delta != 0 or best.diff.n_changes > 0
    for d in drafts:
        assert validate_plan(after, d.plan, now_min=300, parent=rt.freeze(p, 300)) == []


def test_priority_change_can_displace_a_lower_priority_sortie_in_the_coverage_variant() -> None:
    scn = world(
        aircraft=[aircraft("A-1")], crew=[crew("C-1")],
        missions=[mission("M-1", priority=3, weight=35), mission("M-2", priority=4, weight=20)],
    )  # one aircraft, overlapping windows: only one mission can fly
    p = parent_plan(scn)
    assert [a.mission_id for a in p.assignments] == ["M-1"]
    ctx, after, (drafts, affected) = run(
        scn, p, event(EventType.PRIORITY_CHANGE, {"mission_id": "M-2", "new_priority": 1}, 10))
    # the swap gains 65000 points (priority 1 vs 3), more than any preset's stability penalty, so
    # every preset proposes it and the identical plans are merged into one
    assert len(drafts) == 1
    cov = drafts[0]
    assert [a.mission_id for a in cov.plan.assignments] == ["M-2"]
    assert cov.plan.kpis.priority_weighted_coverage > p.kpis.priority_weighted_coverage
    assert R.DROPPED_LOWER_PRIORITY in {b.code for u in cov.plan.unassigned
                                        for b in u.blocking_reasons}


def test_weather_closing_the_base_unassigns_future_sorties_with_reasons() -> None:
    scn = base_world()
    ev = event(EventType.WEATHER_CHANGE, {"base_id": "B1", "new_forecast_ref": "x",
                                          "visibility_km": 0.5, "until_min": 1400}, 300)
    ctx, after, (drafts, affected) = run(scn, parent_plan(scn), ev)
    assert affected.ids == {"S-M-2-1", "S-M-3-1"}
    for d in drafts:
        assert {a.mission_id for a in d.plan.assignments} == {"M-1"}
        assert {u.mission_id for u in d.plan.unassigned} == {"M-2", "M-3"}
        assert all(R.WEATHER_BELOW_MINIMA_BASE in {b.code for b in u.blocking_reasons}
                   for u in d.plan.unassigned)


def test_an_event_after_every_sortie_has_taken_off_changes_nothing() -> None:
    scn = base_world()
    p = parent_plan(scn)
    ctx, after, (drafts, affected) = run(scn, p, event(*A1_DOWN, 1000))
    assert affected.ids == set() and len(drafts) == 1
    assert drafts[0].diff.n_changes == 0 and all(a.frozen for a in drafts[0].plan.assignments)


# --------------------------------------------------------------------------------- fallback
def test_when_the_optimiser_finds_nothing_the_repair_is_proposed_and_marked_fallback(
    monkeypatch,
) -> None:
    scn = base_world()
    p = parent_plan(scn)

    def fake_solve(ctx, scenario_id, params, matrix, *, seed_plan, frozen, parent):
        out = seed_plan.model_copy(update={"created_by": "cpsat"})
        out.solver = out.solver.model_copy(update={"name": "cpsat",
                                                   "status": "FALLBACK_GREEDY (UNKNOWN)"})
        return out

    monkeypatch.setattr(rt, "solve", fake_solve)
    ctx, after, (drafts, affected) = run(scn, p, event(*A1_DOWN, 300))
    assert len(drafts) == 1 and drafts[0].fallback and drafts[0].preset == "greedy_repair"
    assert "Greedy repair" in drafts[0].explanation
    assert validate_plan(after, drafts[0].plan, now_min=300, parent=rt.freeze(p, 300)) == []
    rows = {a.mission_id: a for a in drafts[0].plan.assignments}
    assert (rows["M-2"].aircraft_id, rows["M-2"].takeoff_min) == ("A-2", 750)


# ----------------------------------------------------------------------------------- relabel
def test_relabel_keeps_ids_for_identical_and_same_mission_sorties() -> None:
    scn = base_world()
    p = parent_plan(scn)
    moved = [a.model_copy(update={"aircraft_id": "A-2", "takeoff_min": 750}) if a.mission_id == "M-2"
             else a for a in p.assignments]
    renamed = [a.model_copy(update={"id": "S-X-9"}) for a in moved]
    out = rt.relabel(p, renamed)
    assert [a.id for a in out] == [a.id for a in p.assignments]  # same ids as the parent's
    extra = renamed + [renamed[0].model_copy(update={"takeoff_min": 700, "aircraft_id": "A-2"})]
    ids = [a.id for a in rt.relabel(p, extra)]
    assert len(ids) == len(set(ids)) == 4 and ids[3] == "S-M-1-2"


def test_describe_event_covers_every_type() -> None:
    for et, payload in [
        (EventType.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-1", "until_min": 400}),
        (EventType.CREW_UNAVAILABLE, {"crew_id": "C-1", "until_min": 400}),
        (EventType.WEATHER_CHANGE, {"base_id": "B1", "new_forecast_ref": "x"}),
        (EventType.NEW_THREAT, {"threat": {"id": "T-1", "severity": 0.5}}),
        (EventType.THREAT_UPDATE, {"threat_id": "T-1"}),
        (EventType.AIRSPACE_CHANGE, {"zone": {"id": "Z-1", "kind": "NO_FLY"}}),
        (EventType.PRIORITY_CHANGE, {"mission_id": "M-1", "new_priority": 2}),
        (EventType.NEW_MISSION, {"mission": {"id": "M-9", "priority": 1}}),
        (EventType.MISSION_CANCELLED, {"mission_id": "M-1"}),
    ]:
        assert "T+" in rt.describe_event(event(et, payload, 120))


# --------------------------------------------------------------- validator and frozen sorties
def test_validator_treats_frozen_sorties_as_history() -> None:
    scn = world(weather=weather(visibility_km=0.5))  # base closed all day
    ctx = PlanningContext(scn)
    from app.models.plans import RiskBreakdown
    from app.planning.assemble import assemble_plan, make_assignment

    a = make_assignment(ctx, 1, "M-1", "A-1", "L-AA", 100, 86, ["C-1"],
                        RiskBreakdown(threat=0, weather=0, service=0, total=0), "x")
    live = assemble_plan(ctx, "sc", "m", [a], [], 0, "M")
    assert "WEATHER_BELOW_MINIMA_BASE" in {v.code for v in validate_plan(scn, live)}
    history = assemble_plan(ctx, "sc", "m", [a.model_copy(update={"frozen": True})], [], 0, "M")
    assert validate_plan(scn, history, now_min=500) == []


def test_a_mission_with_a_frozen_sortie_may_be_partial() -> None:
    scn = world(aircraft=[aircraft("A-1"), aircraft("A-2")], crew=[crew("C-1"), crew("C-2")],
                missions=[mission(aircraft_required=2)])
    ctx = PlanningContext(scn)
    from app.models.plans import RiskBreakdown
    from app.planning.assemble import assemble_plan, make_assignment

    zero = RiskBreakdown(threat=0, weather=0, service=0, total=0)
    one = make_assignment(ctx, 1, "M-1", "A-1", "L-AA", 100, 86, ["C-1"], zero, "x")
    partial = assemble_plan(ctx, "sc", "m", [one], [], 0, "M")
    assert "PARTIAL_MISSION" in {v.code for v in validate_plan(scn, partial)}
    frozen = assemble_plan(ctx, "sc", "m", [one.model_copy(update={"frozen": True})], [], 0, "M")
    assert "PARTIAL_MISSION" not in {v.code for v in validate_plan(scn, frozen, now_min=500)}


# ------------------------------------------------- property: seeded scenarios + simulated events
@pytest.mark.parametrize("seed", range(1, 6))
def test_proposals_on_seeded_scenarios_keep_frozen_sorties_and_pass_validate(seed: int) -> None:
    from app.models.scenario import GeneratorParams
    from app.sim.events import simulate_events
    from app.sim.generate import generate_scenario

    scn = generate_scenario(GeneratorParams(seed=seed))
    parent = parent_plan(scn)
    (t, ty, payload), = simulate_events(scn, seed=seed, count=1, from_min=200, to_min=900)
    ev = event(ty, payload, t)
    ctx, after, (drafts, affected) = run(scn, parent, ev, budget=3)
    frozen_parent = rt.freeze(parent, t)
    assert drafts, (seed, ty)
    old_frozen = {a.id: a for a in frozen_parent.assignments if a.frozen}
    for d in drafts:
        assert validate_plan(after, d.plan, now_min=t, parent=frozen_parent) == [], (seed, d.preset)
        new = {a.id: a for a in d.plan.assignments}
        for aid, a in old_frozen.items():  # sorties already under way never change
            b = new[aid]
            assert b.frozen and (b.aircraft_id, b.takeoff_min, b.crew_ids, b.loadout_id) == (
                a.aircraft_id, a.takeoff_min, a.crew_ids, a.loadout_id)
        assert set(d.score_breakdown) == {"coverage", "risk", "stability", "total"}
        assert d.plan.parent_plan_id == parent.id and d.explanation
