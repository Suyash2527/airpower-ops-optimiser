"""Generator: determinism, provenance, referential integrity, India realism, hard cases."""

import math
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from app.models.enums import (
    AircraftStatus,
    Capability,
    EventType,
    ReasonCode,
    Region,
    SeasonPreset,
)
from app.models.scenario import GROUPS, GeneratorParams, ScenarioFile
from app.sim import catalog as cat
from app.sim.generate import generate_scenario
from app.sim.geo import haversine_km

BACKEND = Path(__file__).resolve().parents[1]


def _records(s: ScenarioFile):
    for group in GROUPS:
        yield from ((group, rec) for rec in getattr(s, group))


# ---------------------------------------------------------------- determinism (DoD)
def test_same_seed_gives_identical_json() -> None:
    a = generate_scenario(GeneratorParams(seed=7)).to_canonical_json()
    b = generate_scenario(GeneratorParams(seed=7)).to_canonical_json()
    assert a == b


def test_different_seed_gives_different_json() -> None:
    a = generate_scenario(GeneratorParams(seed=1)).to_canonical_json()
    b = generate_scenario(GeneratorParams(seed=2)).to_canonical_json()
    assert a != b


_DIGEST_SCRIPT = """
import hashlib
from app.models.enums import SeasonPreset
from app.models.scenario import GeneratorParams
from app.sim.generate import generate_scenario
for preset in SeasonPreset:
    for seed in (1, 2, 3, 42):
        # high disruption rate so every event type is exercised
        p = GeneratorParams(seed=seed, season_preset=preset, disruption_rate=1.5, n_missions=20)
        text = generate_scenario(p).to_canonical_json()
        print(preset.value, seed, hashlib.sha256(text.encode()).hexdigest())
"""


def test_output_is_byte_identical_across_processes_and_hash_seeds() -> None:
    """Different PYTHONHASHSEEDs must not change any output (guards set/dict-order bugs)."""
    runs = []
    for hash_seed in ("0", "12345", "987"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        out = subprocess.run(
            [sys.executable, "-c", _DIGEST_SCRIPT],
            cwd=BACKEND, env=env, check=True, capture_output=True, text=True,
        ).stdout
        runs.append(out)
    assert runs[0] == runs[1] == runs[2] and len(runs[0].splitlines()) == 16


def test_saved_json_uses_lf_and_ends_with_newline(scenario42: ScenarioFile) -> None:
    text = scenario42.to_canonical_json()
    assert chr(13) not in text
    assert text.endswith(chr(10))


# ------------------------------------------------------------ provenance and integrity
def test_every_record_carries_provenance_and_honest_source(scenario42: ScenarioFile) -> None:
    seen = Counter()
    for _, rec in _records(scenario42):
        p = rec.provenance
        assert 0 <= p.confidence <= 1 and p.ingested_at >= p.observed_at
        if p.source == "OURAIRPORTS":
            assert p.data_label == "open"
        else:
            assert (p.source, p.data_label) == ("SYNTHETIC", "synthetic")
        seen[p.source] += 1
    assert seen["SYNTHETIC"] > 0 and seen["OURAIRPORTS"] > 0
    assert scenario42.scenario.data_label == "mixed"
    assert len(scenario42.scenario.open_data_sources) == 2


def test_default_counts_follow_params(scenario42: ScenarioFile) -> None:
    c = scenario42.counts()
    assert (c["bases"], c["aircraft"], c["crew"], c["missions"]) == (3, 40, 60, 50)
    mix = Counter(a.type_id for a in scenario42.aircraft)
    assert mix == {"FTR-A": 18, "TPT-B": 8, "HEL-C": 6, "ISR-D": 4, "TKR-E": 4}
    serviceable = sum(a.status is AircraftStatus.SERVICEABLE for a in scenario42.aircraft)
    assert serviceable == 34  # round(0.85 * 40)
    assert c["maintenance_history"] == 40 * 30


def test_ids_unique_and_references_valid(scenario42: ScenarioFile) -> None:
    s = scenario42
    for group in ("bases", "aircraft", "crew", "missions", "threats", "airspace", "events"):
        ids = [r.id for r in getattr(s, group)]
        assert len(ids) == len(set(ids)), group
    base_ids = {b.id for b in s.bases}
    type_ids = {t.id for t in s.aircraft_types}
    loadout_ids = {item.id for item in s.loadouts}
    assert all(a.base_id in base_ids and a.type_id in type_ids for a in s.aircraft)
    assert all(
        a.current_loadout_id is None or a.current_loadout_id in loadout_ids for a in s.aircraft
    )
    assert all(c.base_id in base_ids and set(c.qualifications) <= type_ids for c in s.crew)
    assert all(w.base_id in base_ids for w in s.weather)
    assert all(st.base_id in base_ids for st in s.weapon_stocks)
    aircraft_ids = {a.id for a in s.aircraft}
    assert all(r.aircraft_id in aircraft_ids for r in s.maintenance_history)
    for t in s.aircraft_types:  # loadout compatibility is mirrored both ways
        for item in s.loadouts:
            assert (item.id in t.compatible_loadouts) == (t.id in item.compatible_aircraft_types)


def test_crew_are_within_duty_rules_and_cover_every_needed_role(scenario42: ScenarioFile) -> None:
    rules = scenario42.scenario.duty_rules
    assert all(c.duty_minutes_last_24h <= rules.max_duty_min_24h for c in scenario42.crew)
    roles = {
        c.role for t in scenario42.aircraft_types for c in scenario42.crew
        if t.id in c.qualifications
    }
    needed = {r for t in scenario42.aircraft_types for r in t.crew_roles}
    assert needed <= roles


def test_windows_inside_horizon_and_priorities_valid(scenario42: ScenarioFile) -> None:
    h = scenario42.scenario.horizon_min
    for m in scenario42.missions:
        assert 0 <= m.window_start_min and m.window_end_min <= h
        assert m.weight == cat.PRIORITY_WEIGHT[m.priority]
    assert Counter(m.priority for m in scenario42.missions).most_common(1)[0][0] in (3, 4, 2)


# ------------------------------------------------------------------------ India realism
def test_bases_are_fictional_codenames_inside_region_boxes_and_elevation_capped(
    scenario42: ScenarioFile,
) -> None:
    for b in scenario42.bases:
        assert b.name.startswith("BASE-")
        lat0, lat1, lon0, lon1 = cat.REGION_BOXES[b.region]
        assert lat0 <= b.lat <= lat1 and lon0 <= b.lon <= lon1
        assert b.elevation_m <= cat.MAX_BASE_ELEVATION_M
    pairs = [
        haversine_km(a.lat, a.lon, b.lat, b.lon)
        for i, a in enumerate(scenario42.bases) for b in scenario42.bases[i + 1:]
    ]
    assert min(pairs) >= cat.MIN_BASE_SEPARATION_KM


def test_alternates_are_real_civil_airports_near_bases(scenario42: ScenarioFile) -> None:
    assert scenario42.alternate_airfields
    for a in scenario42.alternate_airfields:
        assert a.provenance.source == "OURAIRPORTS"
        near = min(haversine_km(b.lat, b.lon, a.lat, a.lon) for b in scenario42.bases)
        assert near <= 600


def test_no_alternate_airfield_is_a_military_installation() -> None:
    """INDIA_CONTEXT: no real units or sensitive installations; only civil airports."""
    import json
    import re

    from app.sim.data_loader import DATA_DIR

    military = re.compile(
        r"air force|\bafs\b|air base|air station|military|naval|\bnavy\b|\barmy\b|\bins\b",
        re.IGNORECASE,
    )
    airports = json.loads((DATA_DIR / "india_airports.json").read_text(encoding="utf-8"))
    assert airports["airports"]
    assert not [a["name"] for a in airports["airports"] if military.search(a["name"])]


def test_season_presets_set_t0_and_default_regions() -> None:
    for preset, prof in cat.SEASONS.items():
        s = generate_scenario(GeneratorParams(seed=3, season_preset=preset, n_missions=20))
        assert s.scenario.t0 == prof.t0
        assert {Region(r) for r in s.scenario.region_mix} <= set(prof.default_regions)


def test_winter_fog_is_foggier_than_monsoon_for_the_same_northern_sites() -> None:
    regions = [Region.NORTH, Region.WEST, Region.CENTRAL]

    def mean_vis(preset: SeasonPreset) -> float:
        s = generate_scenario(
            GeneratorParams(seed=11, season_preset=preset, regions=regions, n_missions=8)
        )
        north = {b.id for b in s.bases if b.region is Region.NORTH}
        vis = [w.visibility_km for w in s.weather if w.base_id in north]
        return sum(vis) / len(vis)

    assert mean_vis(SeasonPreset.WINTER_FOG_NORTH) < mean_vis(SeasonPreset.MONSOON)


def test_base_temperature_follows_season_and_lapse_rate() -> None:
    regions = [Region.NORTH, Region.WEST, Region.CENTRAL]
    hot = generate_scenario(GeneratorParams(
        seed=11, season_preset=SeasonPreset.PRE_MONSOON_HEAT_DUST, regions=regions, n_missions=8))
    cold = generate_scenario(GeneratorParams(
        seed=11, season_preset=SeasonPreset.WINTER_FOG_NORTH, regions=regions, n_missions=8))
    for h, c in zip(hot.bases, cold.bases, strict=True):
        assert h.id == c.id and h.ref_temperature_c > c.ref_temperature_c


def test_hadr_missions_reference_a_disaster_event_and_are_high_priority(
    scenario42: ScenarioFile,
) -> None:
    hadr = [m for m in scenario42.missions if m.capability_required is Capability.HADR]
    assert hadr
    assert all(m.disaster_event and m.disaster_event.startswith("DE-") for m in hadr)
    assert all(m.disaster_event is None for m in scenario42.missions if m not in hadr)
    assert all(m.priority <= 3 for m in hadr)


@pytest.mark.parametrize("preset", [SeasonPreset.MONSOON, SeasonPreset.POST_MONSOON_CYCLONE])
def test_disaster_seasons_schedule_an_urgent_hadr_new_mission(preset: SeasonPreset) -> None:
    s = generate_scenario(GeneratorParams(seed=42, season_preset=preset))
    new = [e for e in s.events if e.type is EventType.NEW_MISSION]
    assert new
    mission = new[0].payload["mission"]
    assert mission["capability_required"] == "HADR" and mission["priority"] <= 2
    assert mission["window_start_min"] >= new[0].time_min


def test_civil_routes_and_military_corridors_use_documented_ids(scenario42: ScenarioFile) -> None:
    kinds = {z.id: z.kind.value for z in scenario42.airspace}
    assert any(i.startswith("Z-CIV-") and k == "DANGER" for i, k in kinds.items())
    assert any(i.startswith("Z-MIL-") and k == "CORRIDOR" for i, k in kinds.items())
    for z in scenario42.airspace:
        ring = z.polygon.coordinates[0]
        assert ring[0] == ring[-1] and len(ring) >= 4


def test_events_are_sorted_and_payload_valid(scenario42: ScenarioFile) -> None:
    times = [e.time_min for e in scenario42.events]
    assert times == sorted(times) and times
    assert all(e.source == "SYNTHETIC" for e in scenario42.events)


# --------------------------------------------------------- intentionally infeasible missions
def test_hard_cases_exist_and_are_independently_infeasible(scenario42: ScenarioFile) -> None:
    s = scenario42
    hard = {h.mission_id: h.intended_reason for h in s.scenario.hard_cases}
    assert len(hard) >= 4
    assert set(hard.values()) == {
        ReasonCode.OUT_OF_RANGE, ReasonCode.TIME_WINDOW_UNREACHABLE,
        ReasonCode.NO_CAPABLE_AIRCRAFT, ReasonCode.THREAT_RISK_EXCEEDS_LIMIT,
    }
    fleet = Counter(a.type_id for a in s.aircraft)
    types = {t.id: t for t in s.aircraft_types}
    for m in s.missions:
        reason = hard.get(m.id)
        if reason is ReasonCode.OUT_OF_RANGE:
            best = max(
                t.combat_radius_km for t in types.values() if m.capability_required in t.role
            )
            nearest = min(
                haversine_km(b.lat, b.lon, m.aoi.center.lat, m.aoi.center.lon) for b in s.bases
            )
            assert nearest > best
        elif reason is ReasonCode.TIME_WINDOW_UNREACHABLE:
            assert m.window_end_min - m.window_start_min < m.duration_min
        elif reason is ReasonCode.NO_CAPABLE_AIRCRAFT:
            capable = sum(n for tid, n in fleet.items() if m.capability_required in types[tid].role)
            assert m.aircraft_required > capable
        elif reason is ReasonCode.THREAT_RISK_EXCEEDS_LIMIT:
            covering = [
                t for t in s.threats
                if haversine_km(t.center.lat, t.center.lon, m.aoi.center.lat, m.aoi.center.lon)
                <= t.radius_km
                and t.active_from_min <= m.window_start_min and t.active_to_min >= m.window_end_min
            ]
            assert any(t.severity * t.confidence > m.max_acceptable_risk for t in covering)


def test_all_other_missions_are_feasible_by_design(scenario42: ScenarioFile) -> None:
    """Re-derives the physics (density altitude, endurance, loadout mass, window) per mission."""
    from app.core import physics

    s = scenario42
    hard = {h.mission_id for h in s.scenario.hard_cases}
    aircraft_at = {(a.base_id, a.type_id) for a in s.aircraft}
    types = {t.id: t for t in s.aircraft_types}
    for m in s.missions:
        if m.id in hard:
            continue
        ok = False
        for b in s.bases:
            dist = haversine_km(b.lat, b.lon, m.aoi.center.lat, m.aoi.center.lon)
            for t in types.values():
                if m.capability_required not in t.role or (b.id, t.id) not in aircraft_at:
                    continue
                da = physics.density_altitude_ft(b.elevation_m, b.ref_temperature_c)
                rf = physics.range_factor(t.id, da)
                endurance_ok = (
                    2 * dist / t.cruise_kmh * 60 + m.duration_min
                    <= t.endurance_min * rf * (1 - cat.RESERVE_FRACTION) + 1e-6
                )
                payload = physics.available_payload_kg(t.id, b.elevation_m, b.ref_temperature_c)
                load_ok = m.loadout_category_required is None or any(
                    item.category == m.loadout_category_required
                    and t.id in item.compatible_aircraft_types and item.mass_kg <= payload
                    for item in s.loadouts
                )
                transit = dist / t.cruise_kmh * 60
                if (
                    dist <= t.combat_radius_km * rf + 1e-6 and endurance_ok and load_ok
                    and m.window_start_min >= math.floor(transit)
                ):
                    ok = True
        assert ok, m.id


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_generator_works_for_other_seeds_and_sizes(seed: int) -> None:
    s = generate_scenario(GeneratorParams(
        seed=seed, n_bases=4, n_aircraft=12, n_crew=20, n_missions=15, horizon_min=720,
    ))
    assert len(s.bases) == 4 and len(s.missions) == 15 and s.scenario.hard_cases


def test_infeasible_fraction_zero_creates_no_hard_cases() -> None:
    s = generate_scenario(GeneratorParams(seed=4, infeasible_fraction=0))
    assert s.scenario.hard_cases == []


def test_east_coast_region_generates_bases_inside_its_box() -> None:
    s = generate_scenario(GeneratorParams(
        seed=5, regions=[Region.EAST_COAST], n_bases=4, n_missions=8))
    lat0, lat1, lon0, lon1 = cat.REGION_BOXES[Region.EAST_COAST]
    assert {b.region for b in s.bases} == {Region.EAST_COAST}
    assert all(lat0 <= b.lat <= lat1 and lon0 <= b.lon <= lon1 for b in s.bases)
    assert all(b.climate_zone.value == "tropical_coastal" for b in s.bases)
