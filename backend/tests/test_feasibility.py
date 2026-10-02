"""One pass and one fail case per hard constraint (Tasks 3.1-3.9), then the matrix (3.10).
All on the tiny world from planning_world.py, with numbers worked out by hand."""

from __future__ import annotations

import pytest
from planning_world import (
    BASE_LAT,
    BASE_LON,
    PROV,
    aircraft,
    base,
    crew,
    ftr,
    loadout,
    mission,
    threat,
    weather,
    world,
    zone,
)

from app.ingest.models import RecordFusion
from app.models.entities import AOI, GeoPoint, WeaponStock
from app.models.enums import (
    AircraftStatus,
    AirspaceKind,
    Capability,
    CrewStatus,
    LoadoutCategory,
    ReasonCode,
    Role,
)
from app.planning import feasibility as fz
from app.planning import risk
from app.planning.config import PlanningConfig
from app.planning.context import PlanningContext

R = ReasonCode


def build(**over):
    ctx = PlanningContext(world(**over))
    return ctx, fz.build_mission(ctx, ctx.missions["M-1"])


def codes(feas: fz.MissionFeasibility) -> set[ReasonCode]:
    return {f.code for b in feas.blocked for f in b.reasons} | {f.code for f in feas.mission_level}


# ------------------------------------------------------------------------ the baseline works
def test_baseline_world_is_feasible_with_the_hand_computed_slots() -> None:
    ctx, feas = build()
    (opt,) = feas.options
    assert feas.coverable and not feas.blocked and opt.loadout_id == "L-AA"
    assert opt.transit_min == 13 and opt.land_offset == 2 * 13 + 60
    assert [s.takeoff_min for s in opt.slots] == list(range(90, 316, 15))  # 16 slots
    # service risk 0.02 + 0.08 * 10/100 = 0.028; clear weather and no threats add nothing
    assert opt.slots[0].risk.service == pytest.approx(0.028)
    assert opt.slots[0].risk.total == pytest.approx(0.028)


# ------------------------------------------------------------------ 3.1 capability
def test_capability_pass_and_fail() -> None:
    t = ftr()
    assert fz.check_capability(mission(), t) is None
    fail = fz.check_capability(mission(capability_required=Capability.AIRLIFT), t)
    assert fail is not None and fail.code is R.NO_CAPABLE_AIRCRAFT


def test_mission_needing_more_capable_aircraft_than_the_fleet_has_is_blocked_at_mission_level() -> None:
    _, feas = build(missions=[mission(aircraft_required=2)])
    assert [f.code for f in feas.mission_level] == [R.NO_CAPABLE_AIRCRAFT]
    assert not feas.coverable and feas.n_capable == 1


# ------------------------------------------------------------------ 3.2 serviceability
def test_unserviceable_aircraft_is_blocked_and_a_returning_one_is_used_after_return() -> None:
    _, down = build(aircraft=[aircraft(status=AircraftStatus.UNSERVICEABLE)])
    assert R.AIRCRAFT_UNSERVICEABLE in codes(down) and not down.options
    _, later = build(aircraft=[aircraft(status=AircraftStatus.IN_MAINTENANCE,
                                        available_from_min=200)])
    assert later.options[0].slots[0].takeoff_min == 210  # first slot at/after T+200
    _, never = build(aircraft=[aircraft(status=AircraftStatus.IN_MAINTENANCE,
                                        available_from_min=500)])
    assert R.AIRCRAFT_UNSERVICEABLE in codes(never)  # not back before the window closes


def test_degraded_flies_with_extra_risk_unless_disallowed() -> None:
    ok = PlanningContext(world(aircraft=[aircraft(status=AircraftStatus.DEGRADED)]))
    feas = fz.build_mission(ok, ok.missions["M-1"])
    assert feas.coverable
    assert feas.options[0].slots[0].risk.service == pytest.approx(0.028 + 0.15)
    strict = PlanningContext(world(aircraft=[aircraft(status=AircraftStatus.DEGRADED)]),
                             cfg=PlanningConfig(allow_degraded=False))
    assert not fz.build_mission(strict, strict.missions["M-1"]).coverable


def test_stale_serviceable_status_is_treated_as_degraded() -> None:
    from datetime import timedelta

    meta = {"aircraft": {"A-1": RecordFusion(
        group="aircraft", entity_id="A-1", source="SYNTHETIC", sources=["SYNTHETIC"],
        observed_at=PROV.observed_at - timedelta(minutes=300), confidence=1.0,
        staleness_min=300, stale=True, stale_fields={"status": 300.0})}}
    ctx = PlanningContext(world(), fusion_meta=meta)
    feas = fz.build_mission(ctx, ctx.missions["M-1"])
    assert feas.options[0].slots[0].risk.service == pytest.approx(0.028 + 0.15)


def test_maintenance_due_pass_and_fail() -> None:
    _, ok = build(aircraft=[aircraft(hours_since_maintenance=98.0)])  # 100 - 98 = 2 h >= 1.43 h
    assert ok.coverable
    _, bad = build(aircraft=[aircraft(hours_since_maintenance=99.0)])  # 1 h < 86 min
    assert R.MAINTENANCE_DUE in codes(bad)


def test_nothing_may_take_off_before_now() -> None:
    ctx = PlanningContext(world(), now_min=200)
    feas = fz.build_mission(ctx, ctx.missions["M-1"])
    assert feas.options[0].slots[0].takeoff_min == 210


# ------------------------------------------------------------------ 3.3 range / endurance
def test_range_pass_and_fail() -> None:
    near = mission(aoi=AOI(center=GeoPoint(lat=BASE_LAT + 3.0, lon=BASE_LON), radius_km=20))
    _, ok = build(missions=[near])  # ~333 km vs 500 * range factor
    assert ok.coverable
    far = mission(aoi=AOI(center=GeoPoint(lat=BASE_LAT + 5.5, lon=BASE_LON), radius_km=20))
    _, bad = build(missions=[far])  # ~612 km > 500
    assert R.OUT_OF_RANGE in codes(bad)


def test_endurance_pass_and_fail() -> None:
    _, ok = build(missions=[mission(duration_min=90, window_end_min=500)])  # 116 <= 180*0.8=144
    assert ok.coverable
    _, bad = build(missions=[mission(duration_min=120, window_end_min=500)])  # 146 > 144
    assert R.INSUFFICIENT_FUEL_ENDURANCE in codes(bad)


def test_high_hot_base_derates_range() -> None:
    aoi = AOI(center=GeoPoint(lat=BASE_LAT + 4.0, lon=BASE_LON), radius_km=20)  # ~445 km
    _, sea = build(missions=[mission(aoi=aoi)])
    assert sea.coverable
    _, high = build(bases=[base(elevation_m=4500.0, temp_c=30.0)], missions=[mission(aoi=aoi)])
    assert R.OUT_OF_RANGE in codes(high)  # thin air shortens the usable radius


# ------------------------------------------------------------------ 3.4 loadout and stock
def test_loadout_pass_and_incompatible_fail() -> None:
    _, ok = build()
    assert ok.coverable
    no_load = loadout(compatible_aircraft_types=["TPT-B"])
    _, bad = build(loadouts=[no_load])
    assert R.LOADOUT_INCOMPATIBLE in codes(bad)
    _, wrong_cat = build(missions=[mission(loadout_category_required=LoadoutCategory.CARGO)])
    assert R.LOADOUT_INCOMPATIBLE in codes(wrong_cat)


def test_loadout_too_heavy_for_the_density_altitude_fails() -> None:
    _, bad = build(loadouts=[loadout(mass_kg=9000)])  # FTR-A lifts at most 6000 kg
    assert R.LOADOUT_INCOMPATIBLE in codes(bad)
    heavy = loadout(mass_kg=5000)
    _, sea_level = build(loadouts=[heavy])
    assert sea_level.coverable  # 5000 kg is fine at 200 m
    _, high = build(loadouts=[heavy], bases=[base(elevation_m=4500.0, temp_c=30.0)])
    assert R.LOADOUT_INCOMPATIBLE in codes(high)  # payload falls below 5000 kg at 4500 m, 30 C


def test_stock_pass_and_fail() -> None:
    enough = [WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=4, provenance=PROV)]
    _, ok = build(weapon_stocks=enough)
    assert ok.coverable
    short = [WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=3, provenance=PROV)]
    _, bad = build(weapon_stocks=short)
    assert R.NO_LOADOUT_STOCK in codes(bad)


def test_mission_without_a_loadout_requirement_uses_none() -> None:
    _, feas = build(missions=[mission(loadout_category_required=None)])
    assert feas.options[0].loadout_id == "NONE"


# ------------------------------------------------------------------ 3.5 crew
def test_crew_pass_and_missing_qualified_crew_fail() -> None:
    _, ok = build()
    assert ok.coverable
    _, none = build(crew=[])
    assert R.NO_QUALIFIED_CREW in codes(none)
    _, unqualified = build(crew=[crew(qualifications=["TPT-B"])])
    assert R.NO_QUALIFIED_CREW in codes(unqualified)
    _, sick = build(crew=[crew(status=CrewStatus.SICK)])
    assert R.NO_QUALIFIED_CREW in codes(sick)
    _, other_base = build(crew=[crew(base_id="B2")])
    assert R.NO_QUALIFIED_CREW in codes(other_base)


def test_missing_role_fails_even_if_a_pilot_exists() -> None:
    two_seat = ftr(crew_roles=[Role.PILOT, Role.WSO], min_crew=2)
    _, bad = build(aircraft_types=[two_seat], missions=[mission(min_crew_roles=[Role.PILOT, Role.WSO])])
    assert R.NO_QUALIFIED_CREW in codes(bad)
    wso = crew("C-2", role=Role.WSO)
    _, ok = build(aircraft_types=[two_seat], crew=[crew(), wso],
                  missions=[mission(min_crew_roles=[Role.PILOT, Role.WSO])])
    assert ok.coverable


def test_crew_duty_limit_pass_and_fail() -> None:
    _, ok = build(crew=[crew(duty_minutes_last_24h=634)])  # 634 + 86 = 720 = limit
    assert ok.coverable
    _, bad = build(crew=[crew(duty_minutes_last_24h=635)])  # 721 > 720
    assert R.CREW_DUTY_LIMIT in codes(bad)


def test_crew_rest_limits_which_slots_are_open_and_can_close_all_of_them() -> None:
    # rest needs takeoff - last_duty_end >= 600. last end -300 -> takeoff >= 300 -> slots 300, 315
    _, partial = build(crew=[crew(last_duty_end_min=-300)])
    assert [s.takeoff_min for s in partial.options[0].slots] == [300, 315]
    _, none = build(crew=[crew(last_duty_end_min=-100)])  # takeoff >= 500 > latest slot 315
    assert R.CREW_REST_VIOLATION in codes(none) and not none.options


# ------------------------------------------------------------------ 3.6 time window
def test_time_window_pass_and_fail() -> None:
    # exactly fits: on station T+113..T+173, window T+113..T+173 -> the single slot 105? lo=ceil(100/15)*15
    exact = mission(window_start_min=105, window_end_min=105 + 13 + 60 + 15)
    _, ok = build(missions=[exact])
    assert ok.coverable
    _, bad = build(missions=[mission(window_start_min=100, window_end_min=100 + 60 - 5)])
    assert R.TIME_WINDOW_UNREACHABLE in codes(bad) and not bad.options


def test_window_slots_boundaries() -> None:
    ctx = PlanningContext(world())
    transit = 13
    slots, failure = fz.window_slots(ctx, ctx.missions["M-1"], transit)
    assert failure is None and slots[0] == 90 and slots[-1] == 315
    late = mission(window_start_min=0, window_end_min=72)  # 60 + 13 = 73 > 72
    assert fz.window_slots(ctx, late, transit)[1] is not None


# ------------------------------------------------------------------ 3.7 airspace
def test_airspace_restricted_zone_on_the_route_blocks_while_active_and_not_after() -> None:
    on_route = zone(AirspaceKind.RESTRICTED, BASE_LAT + 0.75, BASE_LON, 0.2)
    _, always = build(airspace=[on_route])
    assert R.AIRSPACE_CONFLICT in codes(always) and not always.options
    brief = zone(AirspaceKind.NO_FLY, BASE_LAT + 0.75, BASE_LON, 0.2, start=0, end=100)
    _, partial = build(airspace=[brief])
    # the route is in the zone ~T+t+3..t+9 outbound and ~T+t+77..83 back; zone ends at T+100,
    # so takeoffs at or after T+105 clear it (takeoff 90 is still blocked)
    assert partial.options[0].slots[0].takeoff_min >= 105


def test_airspace_zone_off_the_route_and_corridor_cover() -> None:
    elsewhere = zone(AirspaceKind.NO_FLY, BASE_LAT + 0.75, BASE_LON + 3.0, 0.2)
    _, ok = build(airspace=[elsewhere])
    assert ok.coverable
    blocker = zone(AirspaceKind.DANGER, BASE_LAT + 0.75, BASE_LON, 0.2, id_="Z-DANGER")
    corridor = zone(AirspaceKind.CORRIDOR, BASE_LAT + 0.75, BASE_LON, 0.4, id_="Z-CORR")
    _, covered = build(airspace=[blocker, corridor])
    assert covered.coverable  # the blocked stretch lies inside an active corridor


def test_airspace_zone_over_the_aoi_blocks_during_loiter() -> None:
    over_aoi = zone(AirspaceKind.RESTRICTED, BASE_LAT + 1.5, BASE_LON, 0.1)
    _, feas = build(airspace=[over_aoi])
    assert R.AIRSPACE_CONFLICT in codes(feas)


# ------------------------------------------------------------------ 3.8 weather minima
def test_weather_at_base_pass_and_fail() -> None:
    _, ok = build()
    assert ok.coverable
    _, bad = build(weather=weather(visibility_km=1.0))  # minimum 1.5 km
    assert R.WEATHER_BELOW_MINIMA_BASE in codes(bad)
    _, windy = build(weather=weather(wind_kmh=61.0))  # maximum 60 km/h
    assert R.WEATHER_BELOW_MINIMA_BASE in codes(windy)
    _, low = build(weather=weather(ceiling_ft=400.0))  # minimum 500 ft
    assert R.WEATHER_BELOW_MINIMA_BASE in codes(low)


def test_weather_at_target_uses_the_nearest_base_forecast() -> None:
    # B2 sits right next to the AOI and has bad weather; B1 (take-off base) is clear.
    b2 = base("B2", lat=BASE_LAT + 1.45, lon=BASE_LON)
    stormy = weather("B2", visibility_km=0.5)
    _, feas = build(bases=[base(), b2], weather=weather() + stormy)
    assert R.WEATHER_BELOW_MINIMA_TARGET in codes(feas)
    assert R.WEATHER_BELOW_MINIMA_BASE not in codes(feas)


def test_a_front_that_passes_closes_only_some_slots() -> None:
    recs = [w.model_copy(update={"visibility_km": 0.5}) if 120 <= w.time_min <= 180 else w
            for w in weather()]
    _, feas = build(weather=recs)
    taken = {s.takeoff_min for s in feas.options[0].slots}
    # Takeoff 90: on station T+103..T+163, inside the front. Takeoffs up to 225 still see the
    # T+180 forecast (valid until T+240) at the base. The first clear slot is 240.
    assert min(taken) == 240 and 225 not in taken and 90 not in taken


# ------------------------------------------------------------------ 3.9 threat
def test_threat_exposure_is_time_weighted_and_can_exceed_the_limit() -> None:
    ctx = PlanningContext(world(threats=[threat()]))
    m = ctx.missions["M-1"]
    profile = ctx.profile(m, ctx.bases["B1"], ctx.types["FTR-A"])
    exposure = risk.threat_exposure(ctx, profile, 100)
    # 60 of 86 flight minutes are spent on station inside the zone (plus a little in transit)
    low, high = 0.95 * 0.9 * 60 / 86, 0.95 * 0.9 * (60 + 2 * 2) / 86
    assert low <= exposure <= high
    assert fz.check_threat(mission(max_acceptable_risk=0.5), exposure) is not None
    assert fz.check_threat(mission(max_acceptable_risk=0.9), exposure) is None
    _, feas = build(threats=[threat()])
    assert R.THREAT_RISK_EXCEEDS_LIMIT in codes(feas)


def test_threat_not_active_or_far_away_does_not_block() -> None:
    _, later = build(threats=[threat(active_from_min=1000)])
    assert later.coverable and later.options[0].slots[0].risk.threat == 0
    _, far = build(threats=[threat(center=GeoPoint(lat=BASE_LAT + 1.5, lon=BASE_LON + 5))])
    assert far.coverable


def test_threat_active_only_part_of_the_sortie_counts_only_that_part() -> None:
    # Active until T+120. A takeoff at 90 is on station T+103..T+163: half inside the window.
    ctx = PlanningContext(world(threats=[threat(active_to_min=120)]))
    m = ctx.missions["M-1"]
    profile = ctx.profile(m, ctx.bases["B1"], ctx.types["FTR-A"])
    early = risk.threat_exposure(ctx, profile, 90)
    late = risk.threat_exposure(ctx, profile, 200)
    assert 0 < early < 0.95 * 0.9 * 60 / 86 and late == 0


# ------------------------------------------------------------------ 3.10 matrix
def test_matrix_counts_reasons_per_blocked_option_and_keeps_examples() -> None:
    two = [aircraft("A-1"), aircraft("A-2", status=AircraftStatus.UNSERVICEABLE),
           aircraft("A-3", hours_since_maintenance=99.9)]
    _, feas = build(aircraft=two)
    assert [o.aircraft_id for o in feas.options] == ["A-1"]
    assert feas.tally[R.AIRCRAFT_UNSERVICEABLE] == 1 and feas.tally[R.MAINTENANCE_DUE] == 1
    assert "A-2" in feas.examples[R.AIRCRAFT_UNSERVICEABLE]
    assert feas.n_combos == 3


def test_incapable_aircraft_are_not_counted_as_blocked_options() -> None:
    tpt = ftr(id="TPT-B", role=[Capability.AIRLIFT], compatible_loadouts=[])
    _, feas = build(aircraft_types=[ftr(), tpt], aircraft=[aircraft(), aircraft("A-9", type_id="TPT-B")])
    assert feas.n_combos == 1 and feas.n_capable == 1


def test_a_reason_shows_even_when_a_static_check_already_failed() -> None:
    # No crew (static) AND a weather front: both should be reported, not just the first.
    _, feas = build(crew=[], weather=weather(visibility_km=0.5))
    assert {R.NO_QUALIFIED_CREW, R.WEATHER_BELOW_MINIMA_BASE} <= codes(feas)


def test_cancelled_missions_are_not_in_the_matrix() -> None:
    from app.models.enums import MissionStatus

    ctx = PlanningContext(world(missions=[mission(status=MissionStatus.CANCELLED), mission("M-2")]))
    assert list(fz.build_matrix(ctx).missions) == ["M-2"]


def test_matrix_is_deterministic() -> None:
    ctx = PlanningContext(world(threats=[threat(radius_km=300)]))
    one = fz.build_mission(ctx, ctx.missions["M-1"])
    two = fz.build_mission(PlanningContext(world(threats=[threat(radius_km=300)])), ctx.missions["M-1"])
    assert [(o.aircraft_id, [s.takeoff_min for s in o.slots]) for o in one.options] == [
        (o.aircraft_id, [s.takeoff_min for s in o.slots]) for o in two.options
    ]
    assert dict(one.tally) == dict(two.tally)
