"""Seeded synthetic scenario generator (DATA_MODEL §5, INDIA_CONTEXT §3 and §6).

Real geography/climate (bases sit on real terrain with real elevation; alternates are real public
civil airports) but FICTIONAL bases, fleet, crews, missions and threats, all labelled SYNTHETIC.

Determinism: every section draws from its own `random.Random(f"airpower:{seed}:{section}")`
(string seeds are hashed with SHA-512, independent of PYTHONHASHSEED), no sets are serialised, and
floats are rounded at creation. Same params => byte-identical canonical JSON.

CLI:  python -m app.sim.generate --seed 42 --out ../scenarios/demo.json
"""

from __future__ import annotations

import argparse
import math
import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.physics import available_payload_kg, density_altitude_ft, range_factor
from app.models.entities import (
    AOI,
    Aircraft,
    AircraftType,
    Airfield,
    AirspaceZone,
    Base,
    CrewMember,
    Event,
    GeoJSONPolygon,
    GeoPoint,
    Loadout,
    MaintenanceRecord,
    Mission,
    Provenance,
    Threat,
    WeaponStock,
    WeatherMinima,
    WeatherRecord,
)
from app.models.enums import (
    AircraftStatus,
    AirspaceKind,
    Capability,
    ClimateZone,
    CrewStatus,
    EventOrigin,
    EventType,
    MissionStatus,
    ReasonCode,
    Region,
    Role,
    ThreatType,
    WeatherKind,
)
from app.models.scenario import DutyRules, GeneratorParams, HardCase, ScenarioFile, ScenarioMeta
from app.sim import catalog as cat
from app.sim.data_loader import load_airports, load_sites
from app.sim.geo import (
    destination_point,
    haversine_km,
    offset_km,
    strip_polygon,
)
from app.sim.hazard import simulate_history

NOTES = (
    "SYNTHETIC scenario. Bases, fleet, crews, missions, threats, maintenance history and weather "
    "are generated and fictional; all numeric performance values are illustrative placeholders. "
    "Only terrain elevation and the alternate-airfield list use real open data (see "
    "open_data_sources). Not validated on real operations. Advisory use only."
)
HARD_REASONS = [
    ReasonCode.OUT_OF_RANGE,
    ReasonCode.TIME_WINDOW_UNREACHABLE,
    ReasonCode.NO_CAPABLE_AIRCRAFT,
    ReasonCode.THREAT_RISK_EXCEEDS_LIMIT,
]
IST_OFFSET_MIN = 330


def _rng(seed: int, section: str) -> random.Random:
    return random.Random(f"airpower:{seed}:{section}")


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _static_prov(t0: datetime) -> Provenance:
    return Provenance(
        source="SYNTHETIC", observed_at=t0, ingested_at=t0, confidence=1.0, data_label="synthetic"
    )


def _prov(rng: random.Random, t0: datetime, max_age_min: int = 20) -> Provenance:
    return Provenance(
        source="SYNTHETIC",
        observed_at=t0 - timedelta(minutes=rng.randint(0, max_age_min)),
        ingested_at=t0,
        confidence=round(rng.uniform(0.8, 0.99), 2),
        data_label="synthetic",
    )


def _largest_remainder(total: int, weights: dict[str, float]) -> dict[str, int]:
    norm = sum(weights.values())
    raw = {k: total * w / norm for k, w in weights.items()}
    out = {k: int(v) for k, v in raw.items()}
    leftover = total - sum(out.values())
    for k in sorted(raw, key=lambda key: (-(raw[key] - out[key]), key))[:leftover]:
        out[k] += 1
    return out


# --------------------------------------------------------------------------- catalogue entities
def _build_types(t0: datetime) -> list[AircraftType]:
    prov = _static_prov(t0)
    return [
        AircraftType(
            id=s.id, role=sorted(s.capabilities, key=str), cruise_kmh=s.cruise_kmh,
            max_range_km=s.max_range_km, combat_radius_km=s.combat_radius_km,
            endurance_min=s.endurance_min, min_crew=len(s.crew_roles),
            crew_roles=list(s.crew_roles), hardpoints=s.hardpoints,
            compatible_loadouts=list(s.loadouts), turnaround_min=s.turnaround_min,
            flight_hours_between_maintenance=s.maint_interval_h,
            weather_minima=WeatherMinima(
                min_visibility_km=s.min_visibility_km, min_ceiling_ft=s.min_ceiling_ft,
                max_wind_kmh=s.max_wind_kmh,
            ),
            provenance=prov,
        )
        for s in cat.TYPES
    ]


def _build_loadouts(t0: datetime) -> list[Loadout]:
    prov = _static_prov(t0)
    return [
        Loadout(
            id=item.id, name=item.name, category=item.category, items=dict(item.items),
            mass_kg=item.mass_kg, compatible_aircraft_types=list(item.compatible), provenance=prov,
        )
        for item in cat.LOADOUTS
    ]


# --------------------------------------------------------------------------------------- bases
def _build_bases(
    params: GeneratorParams, season: cat.SeasonProfile, regions: list[Region], t0: datetime
) -> list[Base]:
    rng = _rng(params.seed, "bases")
    sites = [s for s in load_sites()["sites"] if s["elevation_m"] <= cat.MAX_BASE_ELEVATION_M]
    chosen: list[dict[str, Any]] = []
    for i in range(params.n_bases):
        order = [regions[(i + j) % len(regions)] for j in range(len(regions))]
        for region in order:
            pool = [
                s for s in sites
                if s["region"] == region.value and s not in chosen and all(
                    haversine_km(s["lat"], s["lon"], c["lat"], c["lon"])
                    >= cat.MIN_BASE_SEPARATION_KM
                    for c in chosen
                )
            ]
            if pool:
                chosen.append(rng.choice(pool))
                break
        else:
            raise ValueError("not enough eligible base sites for the requested regions")
    bases = []
    for site in chosen:
        region = Region(site["region"])
        temp = (
            season.sea_level_temp_c[region]
            - 6.5 * site["elevation_m"] / 1000.0
            + rng.gauss(0, 1.5)
        )
        bases.append(
            Base(
                id=site["code"], name=site["code"], region=region,
                elevation_m=site["elevation_m"], climate_zone=ClimateZone(site["climate_zone"]),
                ref_temperature_c=round(temp, 1), lat=site["lat"], lon=site["lon"],
                runways=rng.randint(1, 3),
                turnaround_min_by_type={
                    s.id: s.turnaround_min + rng.randint(-5, 10) for s in cat.TYPES
                },
                fuel_stock_kg=rng.randint(200, 800) * 1000,
                weather_station_id=f"WX-{site['code']}", provenance=_prov(rng, t0),
            )
        )
    return bases


def _build_stocks(params: GeneratorParams, bases: list[Base], t0: datetime) -> list[WeaponStock]:
    rng = _rng(params.seed, "stocks")
    return [
        WeaponStock(
            base_id=b.id, item_type=item, qty_available=rng.randint(*cat.STOCK_RANGES[item]),
            provenance=_prov(rng, t0),
        )
        for b in bases
        for item in cat.BASE_ITEM_TYPES
    ]


# ------------------------------------------------------------------------------------- aircraft
def _build_aircraft(
    params: GeneratorParams, bases: list[Base], t0: datetime
) -> tuple[list[Aircraft], list[MaintenanceRecord]]:
    rng = _rng(params.seed, "aircraft")
    counts = _largest_remainder(params.n_aircraft, cat.AIRCRAFT_MIX)
    type_ids = [tid for tid, n in counts.items() for _ in range(n)]
    rng.shuffle(type_ids)
    n_non = params.n_aircraft - round(params.serviceable_fraction * params.n_aircraft)
    non_serviceable = set(rng.sample(range(params.n_aircraft), n_non))
    cycle = [AircraftStatus.DEGRADED, AircraftStatus.IN_MAINTENANCE, AircraftStatus.UNSERVICEABLE]
    aircraft: list[Aircraft] = []
    history: list[MaintenanceRecord] = []
    k = 0
    for i, tid in enumerate(type_ids):
        spec = cat.TYPE_BY_ID[tid]
        aid = f"A-{i + 1:03d}"
        records, hours_now = simulate_history(
            _rng(params.seed, f"history:{aid}"), spec.maint_interval_h, params.history_days
        )
        if i in non_serviceable:
            status = cycle[k % len(cycle)]
            k += 1
        else:
            status = AircraftStatus.SERVICEABLE
        down = status in (AircraftStatus.UNSERVICEABLE, AircraftStatus.IN_MAINTENANCE)
        loadout = None
        if rng.random() < 0.5:
            loadout = rng.choice(list(spec.loadouts))
        aircraft.append(
            Aircraft(
                id=aid, tail=f"SYN-{i + 1:03d}", type_id=tid, base_id=rng.choice(bases).id,
                status=status, available_from_min=rng.randint(60, 720) if down else 0,
                hours_since_maintenance=hours_now, fuel_state_pct=round(rng.uniform(60, 100), 1),
                current_loadout_id=loadout, provenance=_prov(rng, t0),
            )
        )
        for r in records:
            history.append(
                MaintenanceRecord(
                    id=f"MH-{aid}-D{abs(r.day_offset):03d}", aircraft_id=aid, type_id=tid,
                    day_offset=r.day_offset, hours_since_maintenance=r.hours_since_maintenance,
                    flight_hours=r.flight_hours, recent_fault_count=r.recent_fault_count,
                    failure=r.failure, event=r.event,  # type: ignore[arg-type]
                    provenance=_static_prov(t0),
                )
            )
    return aircraft, history


# ----------------------------------------------------------------------------------------- crew
def _build_crew(
    params: GeneratorParams, aircraft: list[Aircraft], rules: DutyRules, t0: datetime
) -> list[CrewMember]:
    rng = _rng(params.seed, "crew")
    fleet = Counter(a.type_id for a in aircraft)
    role_slots: Counter[str] = Counter()
    for tid, n in fleet.items():
        for role in cat.TYPE_BY_ID[tid].crew_roles:
            role_slots[role.value] += n
    role_counts = _largest_remainder(params.n_crew, dict(sorted(role_slots.items())))
    entries: list[tuple[Role, list[str], str]] = []  # role, qualifications, base
    for role_name, count in role_counts.items():
        role = Role(role_name)
        eligible = [t.id for t in cat.TYPES if role in t.crew_roles and fleet[t.id] > 0]
        primaries = _largest_remainder(count, {t: float(fleet[t]) for t in eligible})
        for tid, n in primaries.items():
            for _ in range(n):
                quals = [tid]
                others = [t for t in eligible if t != tid]
                if others and rng.random() < 0.3:
                    quals.append(rng.choice(others))
                home = rng.choice([a for a in aircraft if a.type_id == tid])
                entries.append((role, sorted(quals), home.base_id))
    n = len(entries)
    n_unavail = n - round(params.crew_available_fraction * n)
    unavailable = set(rng.sample(range(n), n_unavail))
    cycle = [CrewStatus.ON_REST, CrewStatus.ON_DUTY, CrewStatus.SICK, CrewStatus.ON_REST,
             CrewStatus.ON_DUTY]
    crew: list[CrewMember] = []
    j = 0
    for i, (role, quals, base_id) in enumerate(entries):
        if i in unavailable:
            status = cycle[j % len(cycle)]
            j += 1
        else:
            status = CrewStatus.AVAILABLE
        cap = rules.max_duty_min_24h
        if status is CrewStatus.AVAILABLE:
            duty, last_end = rng.randint(0, int(0.7 * cap)), -rng.randint(660, 1800)
        elif status is CrewStatus.ON_REST:
            duty, last_end = rng.randint(int(0.6 * cap), int(0.95 * cap)), -rng.randint(10, 500)
        elif status is CrewStatus.ON_DUTY:
            duty, last_end = rng.randint(int(0.3 * cap), int(0.8 * cap)), rng.randint(30, 240)
        else:
            duty, last_end = 0, -rng.randint(660, 1800)
        crew.append(
            CrewMember(
                id=f"C-{i + 1:03d}", name=f"CREW-{i + 1:03d}", role=role, qualifications=quals,
                base_id=base_id, status=status, duty_minutes_last_24h=duty,
                last_duty_end_min=last_end, provenance=_prov(rng, t0),
            )
        )
    return crew


# ------------------------------------------------------------------------------------ missions
@dataclass
class World:
    params: GeneratorParams
    season: cat.SeasonProfile
    t0: datetime
    bases: list[Base]
    aircraft: list[Aircraft]
    candidates: dict[Capability, list[tuple[Base, cat.TypeSpec]]]
    capable_fleet: dict[Capability, int]


def _leg_limit_km(spec: cat.TypeSpec, base: Base, duration_min: float) -> float:
    """Max AOI distance for a round trip + on-station time, with density-altitude derating."""
    rf = range_factor(spec.id, density_altitude_ft(base.elevation_m, base.ref_temperature_c))
    usable_min = spec.endurance_min * rf * (1 - cat.RESERVE_FRACTION) - duration_min
    if usable_min <= 0:
        return 0.0
    by_endurance = usable_min / 60.0 * spec.cruise_kmh / 2.0
    return min(spec.combat_radius_km * rf, by_endurance, cat.AOI_DISTANCE_CAP_KM)


def _loadout_ok(spec: cat.TypeSpec, base: Base, profile: cat.MissionProfile) -> bool:
    if profile.loadout_category is None:
        return True
    payload = available_payload_kg(spec.id, base.elevation_m, base.ref_temperature_c)
    return any(
        item.category == profile.loadout_category and spec.id in item.compatible
        and item.mass_kg <= payload
        for item in cat.LOADOUTS
    )


def _build_world(
    params: GeneratorParams, season: cat.SeasonProfile, bases: list[Base], aircraft: list[Aircraft]
) -> World:
    hosted = {(a.base_id, a.type_id) for a in aircraft}
    candidates: dict[Capability, list[tuple[Base, cat.TypeSpec]]] = {}
    capable_fleet: dict[Capability, int] = {}
    for cap in Capability:
        profile = cat.PROFILES[cap]
        capable_fleet[cap] = sum(
            1 for a in aircraft if cap in cat.TYPE_BY_ID[a.type_id].capabilities
        )
        pairs = [
            (b, s)
            for b in bases
            for s in cat.TYPES
            if cap in s.capabilities and (b.id, s.id) in hosted
            and _leg_limit_km(s, b, profile.duration[1]) >= 30.0 and _loadout_ok(s, b, profile)
        ]
        if pairs:
            candidates[cap] = pairs
    return World(params, season, season.t0, bases, aircraft, candidates, capable_fleet)


def _weighted(rng: random.Random, weights: dict[int, float]) -> int:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _build_mission(
    world: World, rng: random.Random, number: int, cap: Capability, *,
    min_start: int = 0, disaster_event: str | None = None, priority: int | None = None,
) -> Mission:
    profile = cat.PROFILES[cap]
    base, spec = rng.choice(world.candidates[cap])
    duration = rng.randint(*profile.duration)
    dist = rng.uniform(0.2, 0.95) * _leg_limit_km(spec, base, duration)
    lat, lon = destination_point(base.lat, base.lon, rng.uniform(0, 360), dist)
    transit = math.ceil(dist / spec.cruise_kmh * 60)
    first = max(min_start, transit + 15)
    latest = max(first, world.params.horizon_min - duration - 150)
    start = rng.randint(first, latest)
    end = max(min(start + duration + rng.randint(90, 300), world.params.horizon_min),
              start + duration)
    counts = [c for c, _ in profile.aircraft_required]
    required = rng.choices(counts, weights=[p for _, p in profile.aircraft_required])[0]
    prio = priority or _weighted(rng, cat.PRIORITY_WEIGHTS.get(cap, cat.DEFAULT_PRIORITY_WEIGHTS)
                                 if cap in cat.PRIORITY_WEIGHTS else cat.DEFAULT_PRIORITY_WEIGHTS)
    return Mission(
        id=f"M-{number:03d}", name=f"{cat.CAPABILITY_LABEL[cap]} tasking {number:03d}",
        capability_required=cap, priority=prio, weight=cat.PRIORITY_WEIGHT[prio],
        window_start_min=start, window_end_min=end, duration_min=duration,
        aoi=AOI(center=GeoPoint(lat=round(lat, 4), lon=round(lon, 4)),
                radius_km=round(rng.uniform(10, 60), 1)),
        aircraft_required=min(required, world.capable_fleet[cap]),
        loadout_category_required=profile.loadout_category,
        min_crew_roles=list(profile.crew_roles),
        max_acceptable_risk=round(rng.uniform(0.3, 0.6), 2), status=MissionStatus.PENDING,
        disaster_event=disaster_event, provenance=_prov(rng, world.t0),
    )


def _disaster_ref(world: World, cap: Capability, counter: int) -> str | None:
    if cap is not Capability.HADR:
        return None
    kinds = world.season.disaster_kinds
    return f"DE-{kinds[counter % len(kinds)]}-{counter // len(kinds) + 1:02d}"


def _make_hard(
    world: World, rng: random.Random, mission: Mission, reason: ReasonCode
) -> tuple[Mission, Threat | None]:
    """Turn a feasible-by-design mission into an intentionally infeasible one."""
    threat = None
    if reason is ReasonCode.OUT_OF_RANGE:
        cap = mission.capability_required
        max_radius = max(
            s.combat_radius_km for s in cat.TYPES if cap in s.capabilities
        )
        anchor = rng.choice(world.bases)
        for attempt in range(400):
            dist = max_radius * (1.25 + 0.002 * attempt)
            lat, lon = destination_point(anchor.lat, anchor.lon, rng.uniform(0, 360), dist)
            if all(
                haversine_km(lat, lon, b.lat, b.lon) > 1.15 * max_radius for b in world.bases
            ):
                break
        else:
            raise RuntimeError("could not place an out-of-range AOI")
        mission = mission.model_copy(update={
            "aoi": AOI(center=GeoPoint(lat=round(lat, 4), lon=round(lon, 4)),
                       radius_km=mission.aoi.radius_km),
        })
    elif reason is ReasonCode.TIME_WINDOW_UNREACHABLE:
        mission = mission.model_copy(update={
            "window_end_min": mission.window_start_min + mission.duration_min - rng.randint(5, 20),
        })
    elif reason is ReasonCode.NO_CAPABLE_AIRCRAFT:
        mission = mission.model_copy(update={
            "aircraft_required": world.capable_fleet[mission.capability_required] + 1,
        })
    else:  # THREAT_RISK_EXCEEDS_LIMIT
        c = mission.aoi.center
        threat = Threat(
            id="", type=rng.choice(list(ThreatType)), center=GeoPoint(lat=c.lat, lon=c.lon),
            radius_km=round(mission.aoi.radius_km + 25, 1), severity=0.95,
            active_from_min=0, active_to_min=world.params.horizon_min, confidence=0.9,
            provenance=_prov(rng, world.t0),
        )
        mission = mission.model_copy(update={"max_acceptable_risk": 0.05})
    return mission, threat


def _build_missions(
    world: World,
) -> tuple[list[Mission], list[HardCase], list[Threat]]:
    params = world.params
    rng = _rng(params.seed, "missions")
    caps = [c for c in Capability if c in world.candidates]
    weights = [world.season.mission_weights[c] for c in caps]
    n = params.n_missions
    n_hard = 0
    if params.infeasible_fraction > 0:
        n_hard = min(n, max(4, round(params.infeasible_fraction * n)))
    hard_idx = sorted(rng.sample(range(n), n_hard))
    smallest = min(caps, key=lambda c: (world.capable_fleet[c], c.value))
    missions: list[Mission] = []
    hard_cases: list[HardCase] = []
    hard_threats: list[Threat] = []
    hadr_counter = 0
    for i in range(n):
        reason = HARD_REASONS[hard_idx.index(i) % len(HARD_REASONS)] if i in hard_idx else None
        cap = (
            smallest if reason is ReasonCode.NO_CAPABLE_AIRCRAFT
            else rng.choices(caps, weights=weights)[0]
        )
        ref = _disaster_ref(world, cap, hadr_counter)
        hadr_counter += 1 if ref else 0
        mission = _build_mission(world, rng, i + 1, cap, disaster_event=ref)
        if reason is not None:
            mission, threat = _make_hard(world, rng, mission, reason)
            hard_cases.append(HardCase(mission_id=mission.id, intended_reason=reason))
            if threat is not None:
                hard_threats.append(threat)
        missions.append(mission)
    return missions, hard_cases, hard_threats


# ------------------------------------------------------------------ threats, airspace, alternates
def _region_point(rng: random.Random, region: Region) -> tuple[float, float]:
    lat0, lat1, lon0, lon1 = cat.REGION_BOXES[region]
    return rng.uniform(lat0, lat1), rng.uniform(lon0, lon1)


def _build_threats(
    params: GeneratorParams, regions: list[Region], t0: datetime
) -> list[Threat]:
    rng = _rng(params.seed, "threats")
    count = round(3 + 5 * params.threat_density)
    threats = []
    for i in range(count):
        lat, lon = _region_point(rng, rng.choice(regions))
        start = rng.randint(0, int(params.horizon_min * 0.7))
        end = min(params.horizon_min, start + rng.randint(180, 900))
        threats.append(
            Threat(
                id=f"T-{i + 1:02d}", type=rng.choice(list(ThreatType)),
                center=GeoPoint(lat=round(lat, 4), lon=round(lon, 4)),
                radius_km=round(rng.uniform(30, 150), 1), severity=round(rng.uniform(0.2, 0.9), 2),
                active_from_min=start, active_to_min=end,
                confidence=round(rng.uniform(0.5, 0.95), 2), provenance=_prov(rng, t0),
            )
        )
    return threats


def _build_alternates(bases: list[Base], t0: datetime) -> list[Airfield]:
    data = load_airports()
    airports = data["airports"]
    fetched = datetime.fromisoformat(data["fetched_on"]).replace(tzinfo=t0.tzinfo)
    picked: dict[str, dict[str, Any]] = {}
    for b in bases:
        near = sorted(
            airports, key=lambda a: (haversine_km(b.lat, b.lon, a["lat"], a["lon"]), a["id"])
        )[:4]
        for a in near:
            if haversine_km(b.lat, b.lon, a["lat"], a["lon"]) <= 600:
                picked[a["id"]] = a
    prov = Provenance(
        source="OURAIRPORTS", observed_at=fetched, ingested_at=fetched, confidence=1.0,
        data_label="open",
    )
    return [
        Airfield(
            id=a["id"], name=a["name"], iata=a["iata"], type=a["type"], lat=a["lat"], lon=a["lon"],
            elevation_m=a["elevation_m"], provenance=prov,
        )
        for _, a in sorted(picked.items())
    ]


def _blob(rng: random.Random, lat: float, lon: float, radius_km: float) -> list[list[float]]:
    n = rng.randint(5, 8)
    ring = []
    for k in range(n):
        ang = math.radians((k + rng.uniform(-0.25, 0.25)) * 360 / n)
        rad = radius_km * rng.uniform(0.7, 1.0)
        la, lo = offset_km(lat, lon, rad * math.sin(ang), rad * math.cos(ang))
        ring.append([round(lo, 4), round(la, 4)])
    ring.append(ring[0])
    return ring


def _zone(
    zid: str, kind: AirspaceKind, ring: list[list[float]], floor: int, ceiling: int,
    start: int, end: int, prov: Provenance,
) -> AirspaceZone:
    return AirspaceZone(
        id=zid, kind=kind, polygon=GeoJSONPolygon(coordinates=[ring]), floor_ft=floor,
        ceiling_ft=ceiling, active_from_min=start, active_to_min=end, provenance=prov,
    )


def _build_airspace(
    params: GeneratorParams, bases: list[Base], alternates: list[Airfield], t0: datetime
) -> list[AirspaceZone]:
    rng = _rng(params.seed, "airspace")
    horizon = params.horizon_min
    zones: list[AirspaceZone] = []
    kinds = [AirspaceKind.RESTRICTED, AirspaceKind.DANGER, AirspaceKind.NO_FLY]
    for i in range(rng.randint(2, 4)):  # generic synthetic zones near bases
        b = rng.choice(bases)
        lat, lon = offset_km(b.lat, b.lon, rng.uniform(-150, 150), rng.uniform(-150, 150))
        always = rng.random() < 0.5
        start = 0 if always else rng.randint(0, horizon // 2)
        end = horizon if always else min(horizon, start + rng.randint(180, 720))
        zones.append(_zone(
            f"Z-{i + 1:02d}", rng.choice(kinds),
            _blob(rng, lat, lon, rng.uniform(40, 120)), 0, rng.choice([18000, 35000, 60000]),
            start, end, _prov(rng, t0),
        ))
    for i in range(len(bases) - 1):  # synthetic military transit corridors between bases
        a, b = bases[i], bases[i + 1]
        zones.append(_zone(
            f"Z-MIL-{i + 1:02d}", AirspaceKind.CORRIDOR,
            strip_polygon(a.lat, a.lon, b.lat, b.lon, 20), 0, 25000, 0, horizon, _prov(rng, t0),
        ))
    pairs = [
        (x, y) for i, x in enumerate(alternates) for y in alternates[i + 1:]
        if 150 <= haversine_km(x.lat, x.lon, y.lat, y.lon) <= 800
    ]
    for i, (x, y) in enumerate(rng.sample(pairs, min(3, len(pairs)))):
        # civil routes: real civil airport endpoints, SYNTHETIC geometry and timing (D-20)
        zones.append(_zone(
            f"Z-CIV-{i + 1:02d}", AirspaceKind.DANGER,
            strip_polygon(x.lat, x.lon, y.lat, y.lon, 25), 0, 40000, 0, min(900, horizon),
            _prov(rng, t0),
        ))
    return zones


# -------------------------------------------------------------------------------------- weather
def _build_weather(
    params: GeneratorParams, season: cat.SeasonProfile, bases: list[Base], t0: datetime
) -> list[WeatherRecord]:
    records: list[WeatherRecord] = []
    for base in bases:
        rng = _rng(params.seed, f"weather:{base.id}")
        mean = _clamp(season.mean_badness[base.climate_zone] + 0.25 * params.weather_severity,
                      0.0, 0.9)
        badness = _clamp(mean + rng.gauss(0, 0.1))
        front_t = rng.randint(0, params.horizon_min)
        has_front = rng.random() < 0.5 + 0.4 * params.weather_severity
        front_amp = (0.2 + 0.3 * params.weather_severity) if has_front else 0.0
        wind_dir = rng.uniform(0, 360)
        for t in range(0, params.horizon_min, 60):
            badness = _clamp(
                mean + 0.85 * (badness - mean) + rng.gauss(0, 0.07 + 0.1 * params.weather_severity)
            )
            local_hour = ((t0.hour * 60 + t0.minute + t + IST_OFFSET_MIN) // 60) % 24
            fog = season.fog_diurnal * max(0.0, math.cos(2 * math.pi * (local_hour - 6) / 24))
            front = front_amp * math.exp(-(((t - front_t) / 180.0) ** 2))
            b = _clamp(badness + fog + front)
            wind_dir = (wind_dir + rng.gauss(0, 15)) % 360
            rec = dict(
                visibility_km=round(max(0.1, 10 - 9.5 * b * season.w_vis), 1),
                ceiling_ft=round(max(100.0, 10000 - 9500 * b * season.w_ceil), -1),
                wind_kmh=round(max(0.0, season.base_wind_kmh + 70 * b * season.w_wind
                                   + rng.gauss(0, 2)), 1),
                wind_dir_deg=float(int(round(wind_dir)) % 360),
                precip_mm_h=round(max(0.0, b - 0.45) * 30 * season.w_precip, 1),
                thunderstorm_prob=round(_clamp((b - 0.35) * 1.6 * season.w_tstorm), 2),
            )
            records.append(_weather(WeatherKind.FORECAST, base, t, rec, t0, 60, 0.7))
            if t == 0:
                records.append(_weather(WeatherKind.OBSERVATION, base, 0, rec, t0, 10, 0.9))
    return records


def _weather(
    kind: WeatherKind, base: Base, t: int, rec: dict[str, float], t0: datetime,
    age_min: int, confidence: float,
) -> WeatherRecord:
    return WeatherRecord(
        kind=kind, base_id=base.id, lat=base.lat, lon=base.lon, time_min=t, **rec,
        provenance=Provenance(
            source="SYNTHETIC", observed_at=t0 - timedelta(minutes=age_min), ingested_at=t0,
            confidence=confidence, data_label="synthetic",
        ),
    )


# ---------------------------------------------------------------------------------------- events
def _build_events(
    world: World, missions: list[Mission], threats: list[Threat]
) -> list[Event]:
    params = world.params
    rng = _rng(params.seed, "events")
    horizon = params.horizon_min
    n = round(params.disruption_rate * horizon / 60)
    hadr_season = world.season.disaster_kinds[0] in ("FLOOD", "CYCLONE")
    if n == 0 and hadr_season and params.disruption_rate > 0:
        n = 1
    if n == 0:
        return []
    serviceable = [a for a in world.aircraft if a.status is AircraftStatus.SERVICEABLE]
    types = [
        (EventType.AIRCRAFT_UNSERVICEABLE, 0.30), (EventType.CREW_UNAVAILABLE, 0.15),
        (EventType.WEATHER_CHANGE, 0.15), (EventType.NEW_THREAT, 0.10),
        (EventType.PRIORITY_CHANGE, 0.10), (EventType.MISSION_CANCELLED, 0.05),
        (EventType.AIRSPACE_CHANGE, 0.05),
    ]
    if Capability.HADR in world.candidates:
        types.append((EventType.NEW_MISSION, 0.10))
    crew_ids = [f"C-{i + 1:03d}" for i in range(params.n_crew)]
    raw: list[tuple[int, EventType, dict[str, Any]]] = []
    next_mission = len(missions) + 1
    next_threat = len(threats) + 1
    hadr_counter = sum(1 for m in missions if m.disaster_event)
    for k in range(n):
        etype = (
            EventType.NEW_MISSION if k == 0 and hadr_season and Capability.HADR in world.candidates
            else rng.choices([t for t, _ in types], weights=[w for _, w in types])[0]
        )
        t = rng.randint(60, max(60, horizon - 60))
        if etype is EventType.AIRCRAFT_UNSERVICEABLE:
            payload: dict[str, Any] = {
                "aircraft_id": rng.choice(serviceable).id,
                "until_min": None if rng.random() < 0.3 else t + rng.randint(120, 720),
            }
        elif etype is EventType.CREW_UNAVAILABLE:
            payload = {"crew_id": rng.choice(crew_ids), "until_min": t + rng.randint(120, 600)}
        elif etype is EventType.WEATHER_CHANGE:
            base = rng.choice(world.bases)
            payload = {"base_id": base.id, "new_forecast_ref": f"{base.id}:FORECAST:{t // 60 * 60}"}
        elif etype is EventType.NEW_THREAT:
            regions = list(dict.fromkeys(b.region for b in world.bases))  # ordered, no set
            lat, lon = _region_point(rng, rng.choice(regions))
            payload = {"threat": Threat(
                id=f"T-{next_threat:02d}", type=rng.choice(list(ThreatType)),
                center=GeoPoint(lat=round(lat, 4), lon=round(lon, 4)),
                radius_km=round(rng.uniform(30, 120), 1), severity=round(rng.uniform(0.3, 0.9), 2),
                active_from_min=t, active_to_min=min(horizon, t + rng.randint(180, 600)),
                confidence=round(rng.uniform(0.5, 0.9), 2), provenance=_prov(rng, world.t0),
            ).model_dump(mode="json")}
            next_threat += 1
        elif etype is EventType.PRIORITY_CHANGE:
            m = rng.choice(missions)
            payload = {"mission_id": m.id,
                       "new_priority": rng.choice([p for p in (1, 2, 3) if p != m.priority])}
        elif etype is EventType.MISSION_CANCELLED:
            payload = {"mission_id": rng.choice(missions).id}
        elif etype is EventType.AIRSPACE_CHANGE:
            b = rng.choice(world.bases)
            lat, lon = offset_km(b.lat, b.lon, rng.uniform(-100, 100), rng.uniform(-100, 100))
            zone = _zone(
                f"Z-EV-{k + 1:02d}", AirspaceKind.RESTRICTED, _blob(rng, lat, lon, 60), 0, 30000,
                t, min(horizon, t + rng.randint(180, 600)), _prov(rng, world.t0),
            )
            payload = {"zone": zone.model_dump(mode="json")}
        else:  # NEW_MISSION: an urgent HADR request appearing mid-scenario
            ref = _disaster_ref(world, Capability.HADR, hadr_counter)
            hadr_counter += 1
            mission = _build_mission(
                world, rng, next_mission, Capability.HADR, min_start=t + 30,
                disaster_event=ref, priority=rng.choice([1, 1, 2]),
            )
            next_mission += 1
            payload = {"mission": mission.model_dump(mode="json")}
        raw.append((t, etype, payload))
    raw.sort(key=lambda item: (item[0], item[1].value))
    return [
        Event(
            id=f"E-{i + 1:03d}", type=etype, time_min=t, payload=payload, source="SYNTHETIC",
            created_by=EventOrigin.SIM, provenance=_prov(rng, world.t0),
        )
        for i, (t, etype, payload) in enumerate(raw)
    ]


# -------------------------------------------------------------------------------------- entry
def generate_scenario(params: GeneratorParams) -> ScenarioFile:
    season = cat.SEASONS[params.season_preset]
    t0 = season.t0
    regions = list(params.regions) if params.regions else list(season.default_regions)
    bases = _build_bases(params, season, regions, t0)
    aircraft, history = _build_aircraft(params, bases, t0)
    rules = DutyRules()
    crew = _build_crew(params, aircraft, rules, t0)
    alternates = _build_alternates(bases, t0)
    world = _build_world(params, season, bases, aircraft)
    missions, hard_cases, hard_threats = _build_missions(world)
    threats = _build_threats(params, list(dict.fromkeys(b.region for b in bases)), t0)
    start = len(threats)
    threats += [
        t.model_copy(update={"id": f"T-{start + i + 1:02d}"}) for i, t in enumerate(hard_threats)
    ]
    events = _build_events(world, missions, threats)
    region_mix = dict(sorted(Counter(b.region.value for b in bases).items()))
    sites, airports = load_sites(), load_airports()
    meta = ScenarioMeta(
        name=f"{params.season_preset.value} seed {params.seed}", seed=params.seed, t0=t0,
        horizon_min=params.horizon_min, data_label="mixed" if alternates else "synthetic",
        season_preset=params.season_preset, region_mix=region_mix, notes=NOTES,
        open_data_sources=[
            "OurAirports (public domain), https://ourairports.com/data/, "
            f"fetched {airports['fetched_on']}",
            "Open-Meteo elevation API (CC BY 4.0), https://open-meteo.com/, "
            f"fetched {sites['fetched_on']}",
        ],
        params=params.model_dump(mode="json"), duty_rules=rules, hard_cases=hard_cases,
    )
    return ScenarioFile(
        scenario=meta, bases=bases, aircraft_types=_build_types(t0), aircraft=aircraft, crew=crew,
        loadouts=_build_loadouts(t0), weapon_stocks=_build_stocks(params, bases, t0),
        missions=missions, threats=threats,
        airspace=_build_airspace(params, bases, alternates, t0),
        weather=_build_weather(params, season, bases, t0), alternate_airfields=alternates,
        maintenance_history=history, events=events,
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate a seeded SYNTHETIC AirPower scenario.")
    p.add_argument("--out", type=Path, required=True)
    for name, field in GeneratorParams.model_fields.items():
        flag = "--" + name.replace("_", "-")
        if name == "seed":
            p.add_argument(flag, type=int, required=True)
        elif name == "season_preset":
            p.add_argument(
                flag, choices=[s.value for s in cat.SEASONS], default=field.default.value
            )
        elif name == "regions":
            p.add_argument(flag, nargs="+", choices=[r.value for r in Region], default=None)
        else:
            p.add_argument(flag, type=type(field.default), default=field.default)
    return p


def main(argv: list[str] | None = None) -> None:
    from app.sim.scenario_io import save_scenario

    args = vars(_parser().parse_args(argv))
    out = args.pop("out")
    scenario = generate_scenario(GeneratorParams(**args))
    digest = save_scenario(scenario, out)
    print(f"wrote {out} sha256={digest}")
    print("counts:", scenario.counts())


if __name__ == "__main__":
    main()
