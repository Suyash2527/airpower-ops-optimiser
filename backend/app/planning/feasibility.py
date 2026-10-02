"""Feasibility engine (ALGORITHMS §2): for a mission, aircraft, loadout, base and takeoff slot,
decide feasible / infeasible with machine-readable reason codes.

Each hard constraint is a small pure function returning `Failure`s (empty = pass) so it can be
unit-tested alone. `build_matrix` then evaluates every (mission x aircraft x loadout x slot):
everything that does not depend on the specific aircraft is computed once per
(mission, base, type, loadout) *group* and shared (ARCHITECTURE decision 3, stage A).

Time of a sortie: takeoff t, on station [t+transit, t+transit+duration], landing
t+2*transit+duration (transit rounded up to whole minutes). Takeoffs are multiples of
`cfg.slot_min`.

Interpretations (logged in DECISIONS.md): a DEGRADED aircraft may fly but carries extra service
risk; an UNSERVICEABLE / IN_MAINTENANCE aircraft returns to service at `available_from_min` only
if that is after `now_min`, otherwise it is unserviceable indefinitely; `fuel_state_pct` is not
used (assumed refuelled during turnaround); the reserve fraction covers diversion; the threat
limit applies to the threat-exposure component only.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import NamedTuple

from app.core.physics import available_payload_kg, density_altitude_ft, range_factor
from app.models.entities import (
    Aircraft,
    AircraftType,
    Base,
    CrewMember,
    Loadout,
    Mission,
    WeatherRecord,
)
from app.models.enums import AircraftStatus, AirspaceKind, MissionStatus, ReasonCode, Role
from app.models.plans import RiskBreakdown
from app.planning import risk
from app.planning.config import NO_LOADOUT
from app.planning.context import PlanningContext
from app.planning.geometry import RouteProfile, inside_zone

PLANNABLE = (MissionStatus.PENDING, MissionStatus.PLANNED)
BLOCKING_AIRSPACE = (AirspaceKind.NO_FLY, AirspaceKind.RESTRICTED, AirspaceKind.DANGER)
DOWN = (AircraftStatus.UNSERVICEABLE, AircraftStatus.IN_MAINTENANCE)


class Failure(NamedTuple):
    code: ReasonCode
    detail: str


@dataclass(frozen=True)
class SlotOption:
    takeoff_min: int
    risk: RiskBreakdown


@dataclass
class Option:
    """One aircraft + loadout that can fly the mission, with every feasible takeoff slot."""

    mission_id: str
    aircraft_id: str
    loadout_id: str
    base_id: str
    transit_min: int
    land_offset: int
    slots: tuple[SlotOption, ...]

    @property
    def best(self) -> SlotOption:
        return min(self.slots, key=lambda s: (s.risk.total, s.takeoff_min))


@dataclass
class BlockedCombo:
    aircraft_id: str
    loadout_id: str | None
    base_id: str
    reasons: list[Failure]


@dataclass
class MissionFeasibility:
    mission_id: str
    required: int
    options: list[Option] = field(default_factory=list)
    blocked: list[BlockedCombo] = field(default_factory=list)
    mission_level: list[Failure] = field(default_factory=list)
    n_capable: int = 0
    tally: Counter[ReasonCode] = field(default_factory=Counter)  # combos blocked per code
    examples: dict[ReasonCode, str] = field(default_factory=dict)

    @property
    def n_combos(self) -> int:
        return len(self.options) + len(self.blocked)

    @property
    def feasible_aircraft(self) -> set[str]:
        return {o.aircraft_id for o in self.options}

    @property
    def coverable(self) -> bool:
        return not self.mission_level and len(self.feasible_aircraft) >= self.required


@dataclass
class FeasibilityMatrix:
    missions: dict[str, MissionFeasibility]


# ------------------------------------------------------------------------------- small helpers
def required_roles(mission: Mission, type_: AircraftType) -> Counter[Role]:
    """Seats of the type, plus any extra role the mission asks for (largest count per role)."""
    need: Counter[Role] = Counter(type_.crew_roles)
    for role, n in Counter(mission.min_crew_roles).items():
        need[role] = max(need[role], n)
    return need


def slot_floor(t: float, slot: int) -> int:
    return int(math.floor(t / slot)) * slot


def slot_ceil(t: float, slot: int) -> int:
    return int(math.ceil(t / slot)) * slot


# -------------------------------------------------------------------- the nine hard constraints
def check_capability(mission: Mission, type_: AircraftType) -> Failure | None:
    """1. The aircraft type lists the mission's capability."""
    if mission.capability_required in type_.role:
        return None
    return Failure(
        ReasonCode.NO_CAPABLE_AIRCRAFT,
        f"{type_.id} cannot do {mission.capability_required.value}",
    )


def earliest_takeoff(ctx: PlanningContext, aircraft: Aircraft) -> int | None:
    """Earliest scenario minute the aircraft can take off, or None if it never can."""
    status = ctx.effective_status(aircraft)
    if status is AircraftStatus.DEGRADED and not ctx.cfg.allow_degraded:
        return None
    if status in DOWN:
        return aircraft.available_from_min if aircraft.available_from_min > ctx.now_min else None
    return max(ctx.now_min, aircraft.available_from_min)


def check_serviceability(
    ctx: PlanningContext, aircraft: Aircraft, type_: AircraftType, flight_min: float
) -> Failure | None:
    """2. Usable status, and enough maintenance margin for this sortie."""
    if earliest_takeoff(ctx, aircraft) is None:
        status = ctx.effective_status(aircraft)
        return Failure(
            ReasonCode.AIRCRAFT_UNSERVICEABLE,
            f"{aircraft.id} is {status.value} with no return time",
        )
    left = type_.flight_hours_between_maintenance - aircraft.hours_since_maintenance
    if flight_min / 60.0 > left:
        return Failure(
            ReasonCode.MAINTENANCE_DUE,
            f"{aircraft.id} has {max(left, 0):.1f} h to maintenance, sortie needs "
            f"{flight_min / 60:.1f} h",
        )
    return None


def check_range_endurance(
    ctx: PlanningContext, mission: Mission, base: Base, type_: AircraftType,
    dist_km: float, transit_min: int,
) -> list[Failure]:
    """3. Combat radius and endurance, derated for density altitude at the base."""
    da = density_altitude_ft(base.elevation_m, base.ref_temperature_c)
    rf = range_factor(type_.id, da)
    out: list[Failure] = []
    radius = type_.combat_radius_km * rf
    if dist_km > radius:
        out.append(Failure(
            ReasonCode.OUT_OF_RANGE,
            f"AOI is {dist_km:.0f} km from {base.id}; {type_.id} reaches {radius:.0f} km there",
        ))
    flight = 2 * transit_min + mission.duration_min
    usable = type_.endurance_min * rf * (1 - ctx.cfg.reserve_fraction)
    if flight > usable:
        out.append(Failure(
            ReasonCode.INSUFFICIENT_FUEL_ENDURANCE,
            f"sortie needs {flight} min, {type_.id} has {usable:.0f} min usable at {base.id}",
        ))
    return out


def candidate_loadouts(
    ctx: PlanningContext, mission: Mission, type_: AircraftType
) -> list[Loadout]:
    """Loadouts of the required category that the type can carry (before payload and stock)."""
    cat = mission.loadout_category_required
    if cat is None:
        return []
    return [
        ld for ld in ctx.scenario.loadouts
        if ld.category is cat and type_.id in ld.compatible_aircraft_types
        and ld.id in type_.compatible_loadouts
    ]


def check_loadout(
    ctx: PlanningContext, mission: Mission, base: Base, type_: AircraftType,
    loadout: Loadout | None,
) -> Failure | None:
    """4. Category and compatibility, payload at the base's density altitude, and stock."""
    if mission.loadout_category_required is None:
        return None
    if loadout is None:
        return Failure(
            ReasonCode.LOADOUT_INCOMPATIBLE,
            f"{type_.id} has no {mission.loadout_category_required.value} loadout",
        )
    if (
        loadout.category is not mission.loadout_category_required
        or type_.id not in loadout.compatible_aircraft_types
        or loadout.id not in type_.compatible_loadouts
    ):
        return Failure(ReasonCode.LOADOUT_INCOMPATIBLE, f"{loadout.id} does not fit {type_.id}")
    payload = available_payload_kg(type_.id, base.elevation_m, base.ref_temperature_c)
    if loadout.mass_kg > payload:
        return Failure(
            ReasonCode.LOADOUT_INCOMPATIBLE,
            f"{loadout.id} weighs {loadout.mass_kg:.0f} kg, {type_.id} can lift {payload:.0f} kg "
            f"at {base.id} (elevation {base.elevation_m:.0f} m)",
        )
    for item, qty in loadout.items.items():
        have = ctx.stock.get((base.id, item), 0)
        if have < qty:
            return Failure(
                ReasonCode.NO_LOADOUT_STOCK,
                f"{base.id} has {have} x {item}, {loadout.id} needs {qty}",
            )
    return None


def eligible_crew(
    ctx: PlanningContext, base_id: str, type_id: str, role: Role, sortie_min: int,
    takeoff_min: int | None = None,
) -> tuple[list[CrewMember], list[CrewMember], list[CrewMember]]:
    """Crew at the base for one role, filtered in three stages: qualified and AVAILABLE; within the
    duty limit for this sortie; rested by `takeoff_min` (skipped when None)."""
    stage1 = [
        c for c in ctx.crew_at_base.get(base_id, [])
        if c.role is role and type_id in c.qualifications and c.status.value == "AVAILABLE"
    ]
    stage2 = [
        c for c in stage1 if c.duty_minutes_last_24h + sortie_min <= ctx.rules.max_duty_min_24h
    ]
    stage3 = (
        stage2 if takeoff_min is None
        else [c for c in stage2 if takeoff_min - c.last_duty_end_min >= ctx.rules.min_rest_min]
    )
    return stage1, stage2, stage3


def check_crew(
    ctx: PlanningContext, mission: Mission, base: Base, type_: AircraftType, sortie_min: int,
    takeoff_min: int | None = None,
) -> Failure | None:
    """5. Each required role has enough qualified, AVAILABLE, within-duty, rested crew."""
    for role, need in sorted(required_roles(mission, type_).items(), key=lambda kv: kv[0].value):
        s1, s2, s3 = eligible_crew(ctx, base.id, type_.id, role, sortie_min, takeoff_min)
        if len(s1) < need:
            return Failure(
                ReasonCode.NO_QUALIFIED_CREW,
                f"{base.id} has {len(s1)} AVAILABLE {role.value} qualified on {type_.id}, "
                f"needs {need}",
            )
        if len(s2) < need:
            return Failure(
                ReasonCode.CREW_DUTY_LIMIT,
                f"only {len(s2)} {role.value} at {base.id} stay within "
                f"{ctx.rules.max_duty_min_24h} duty minutes for a {sortie_min} min sortie",
            )
        if len(s3) < need:
            return Failure(
                ReasonCode.CREW_REST_VIOLATION,
                f"only {len(s3)} {role.value} at {base.id} have {ctx.rules.min_rest_min} min "
                f"rest by T+{takeoff_min}",
            )
    return None


def window_slots(
    ctx: PlanningContext, mission: Mission, transit_min: int
) -> tuple[list[int], Failure | None]:
    """6. Takeoff slots that put the aircraft on station inside the window."""
    slot = ctx.cfg.slot_min
    lo = slot_ceil(max(mission.window_start_min - transit_min, ctx.now_min, 0), slot)
    hi = slot_floor(mission.window_end_min - mission.duration_min - transit_min, slot)
    if hi < lo:
        return [], Failure(
            ReasonCode.TIME_WINDOW_UNREACHABLE,
            f"window T+{mission.window_start_min}..T+{mission.window_end_min} cannot hold "
            f"{mission.duration_min} min on station after {transit_min} min transit",
        )
    return list(range(lo, hi + 1, slot)), None


def check_airspace(
    ctx: PlanningContext, profile: RouteProfile, takeoff_min: int
) -> Failure | None:
    """7. No sample of the route is inside a NO_FLY / RESTRICTED / DANGER zone while it is active,
    unless that sample is inside an active CORRIDOR."""
    times = takeoff_min + profile.offset
    covered = None
    for z in ctx.scenario.airspace:
        if z.kind is not AirspaceKind.CORRIDOR:
            continue
        hit = inside_zone(profile, z) & (times >= z.active_from_min) & (times <= z.active_to_min)
        covered = hit if covered is None else (covered | hit)
    for z in ctx.scenario.airspace:
        if z.kind not in BLOCKING_AIRSPACE:
            continue
        bad = inside_zone(profile, z) & (times >= z.active_from_min) & (times <= z.active_to_min)
        if covered is not None:
            bad = bad & ~covered
        if bad.any():
            return Failure(
                ReasonCode.AIRSPACE_CONFLICT,
                f"route crosses {z.kind.value} zone {z.id} (active T+{z.active_from_min}.."
                f"T+{z.active_to_min}) at takeoff T+{takeoff_min}",
            )
    return None


def sortie_weather(
    ctx: PlanningContext, mission: Mission, base: Base, profile: RouteProfile, takeoff_min: int
) -> tuple[list[WeatherRecord], list[WeatherRecord], list[WeatherRecord]]:
    """Forecast records that matter: at the base for takeoff, at the base for landing, and near
    the AOI (nearest base's forecast, an approximation) from arrival to departure."""
    arrive = takeoff_min + profile.transit_min
    depart = arrive + profile.duration_min
    land = takeoff_min + profile.land_offset
    aoi = mission.aoi.center
    near = ctx.nearest_base(aoi.lat, aoi.lon).id
    marks = sorted({arrive, depart, *range(slot_ceil(arrive, 60), depart, 60)})
    take = ctx.weather_at(base.id, takeoff_min)
    landing = ctx.weather_at(base.id, land)
    target = [w for w in (ctx.weather_at(near, m) for m in marks) if w is not None]
    return ([take] if take else []), ([landing] if landing else []), target


def check_weather(
    ctx: PlanningContext, type_: AircraftType, base: Base,
    records: tuple[list[WeatherRecord], list[WeatherRecord], list[WeatherRecord]],
) -> list[Failure]:
    """8. Forecast at base (takeoff, landing) and target meets the type's minima. No forecast at
    all for a place means that place is not checked."""
    minima = type_.weather_minima
    out: list[Failure] = []
    take, landing, target = records
    for rec in [*take, *landing]:
        if risk.weather_margin(rec, minima) < 1.0:
            out.append(Failure(
                ReasonCode.WEATHER_BELOW_MINIMA_BASE,
                f"{base.id} at T+{rec.time_min}: vis {rec.visibility_km} km, ceiling "
                f"{rec.ceiling_ft:.0f} ft, wind {rec.wind_kmh} km/h",
            ))
            break
    for rec in target:
        if risk.weather_margin(rec, minima) < 1.0:
            out.append(Failure(
                ReasonCode.WEATHER_BELOW_MINIMA_TARGET,
                f"target area ({rec.base_id} forecast) at T+{rec.time_min}: vis "
                f"{rec.visibility_km} km, ceiling {rec.ceiling_ft:.0f} ft, "
                f"wind {rec.wind_kmh} km/h",
            ))
            break
    return out


def check_threat(mission: Mission, exposure: float) -> Failure | None:
    """9. Threat exposure along route and at the AOI stays within the mission's limit."""
    if exposure <= mission.max_acceptable_risk:
        return None
    return Failure(
        ReasonCode.THREAT_RISK_EXCEEDS_LIMIT,
        f"threat exposure {exposure:.2f} exceeds the mission limit "
        f"{mission.max_acceptable_risk:.2f}",
    )


# ------------------------------------------------------------------------- group evaluation
@dataclass
class _Group:
    """Aircraft-independent result for one (mission, base, type, loadout)."""

    slots: list[SlotOption]
    failures: list[Failure]
    transit_min: int
    land_offset: int


def _evaluate_group(
    ctx: PlanningContext, mission: Mission, base: Base, type_: AircraftType,
    loadout: Loadout | None,
) -> _Group:
    profile = ctx.profile(mission, base, type_)
    flight = profile.land_offset
    static: list[Failure] = list(check_range_endurance(
        ctx, mission, base, type_, profile.dist_km, profile.transit_min
    ))
    crew_static = check_crew(ctx, mission, base, type_, flight)
    for f in (check_loadout(ctx, mission, base, type_, loadout), crew_static):
        if f is not None:
            static.append(f)
    candidates, window_failure = window_slots(ctx, mission, profile.transit_min)
    if window_failure is not None:
        return _Group([], [*static, window_failure], profile.transit_min, flight)

    # Time-dependent checks run even when a static check already failed, so the failure list is
    # complete (the explanation shows every reason, not only the first).
    ok: list[SlotOption] = []
    counts: Counter[ReasonCode] = Counter()
    first: dict[ReasonCode, str] = {}
    for t in candidates:
        fails: list[Failure] = []
        if crew_static is None:
            rest = check_crew(ctx, mission, base, type_, flight, t)
            if rest is not None:
                fails.append(rest)
        air = check_airspace(ctx, profile, t)
        if air is not None:
            fails.append(air)
        records = sortie_weather(ctx, mission, base, profile, t)
        fails.extend(check_weather(ctx, type_, base, records))
        exposure = risk.threat_exposure(ctx, profile, t)
        thr = check_threat(mission, exposure)
        if thr is not None:
            fails.append(thr)
        if fails:
            for f in fails:
                counts[f.code] += 1
                first.setdefault(f.code, f.detail)
            continue
        weather = risk.weather_risk(
            ctx.cfg, [*records[0], *records[1], *records[2]], type_.weather_minima
        )
        ok.append(SlotOption(t, risk.combine(exposure, weather, 0.0)))
    if static or not ok:
        failures = [*static, *(Failure(code, first[code]) for code, _ in counts.most_common())]
        return _Group([] if static else ok, failures, profile.transit_min, flight)
    return _Group(ok, [], profile.transit_min, flight)


# --------------------------------------------------------------------------- matrix builder
def build_mission(ctx: PlanningContext, mission: Mission) -> MissionFeasibility:
    result = MissionFeasibility(mission_id=mission.id, required=mission.aircraft_required)
    groups: dict[tuple[str, str, str | None], _Group] = {}
    capable = [
        a for a in ctx.scenario.aircraft
        if check_capability(mission, ctx.types[a.type_id]) is None
    ]
    result.n_capable = len(capable)
    if len(capable) < mission.aircraft_required:
        result.mission_level.append(Failure(
            ReasonCode.NO_CAPABLE_AIRCRAFT,
            f"needs {mission.aircraft_required} aircraft able to do "
            f"{mission.capability_required.value}; the fleet has {len(capable)}",
        ))

    for a in capable:
        type_, base = ctx.types[a.type_id], ctx.bases[a.base_id]
        loadouts: list[Loadout | None] = list(candidate_loadouts(ctx, mission, type_)) or [None]
        profile = ctx.profile(mission, base, type_)
        own = check_serviceability(ctx, a, type_, profile.land_offset)
        earliest = earliest_takeoff(ctx, a)
        for ld in loadouts:
            combo_reasons: list[Failure] = [own] if own is not None else []
            if not combo_reasons:
                gkey = (base.id, type_.id, ld.id if ld else None)
                if gkey not in groups:
                    groups[gkey] = _evaluate_group(ctx, mission, base, type_, ld)
                g = groups[gkey]
                usable = [s for s in g.slots if earliest is not None and s.takeoff_min >= earliest]
                if usable:
                    status = ctx.effective_status(a)
                    svc = risk.service_risk(ctx.cfg, a, type_, status)
                    slots = tuple(
                        SlotOption(s.takeoff_min, risk.combine(
                            s.risk.threat, s.risk.weather, svc))
                        for s in usable
                    )
                    result.options.append(Option(
                        mission.id, a.id, ld.id if ld else NO_LOADOUT, base.id,
                        g.transit_min, g.land_offset, slots,
                    ))
                    continue
                if g.slots:  # slots exist but the aircraft is not back in time
                    combo_reasons = [Failure(
                        ReasonCode.AIRCRAFT_UNSERVICEABLE,
                        f"{a.id} is not available before T+{earliest}",
                    )]
                else:
                    combo_reasons = list(g.failures)
            result.blocked.append(BlockedCombo(a.id, ld.id if ld else None, base.id, combo_reasons))
            for code in {f.code for f in combo_reasons}:
                result.tally[code] += 1
            for f in combo_reasons:
                result.examples.setdefault(f.code, f.detail)
    return result


def build_matrix(
    ctx: PlanningContext, mission_ids: list[str] | None = None
) -> FeasibilityMatrix:
    chosen = [
        m for m in ctx.scenario.missions
        if m.status in PLANNABLE and (mission_ids is None or m.id in mission_ids)
    ]
    return FeasibilityMatrix({m.id: build_mission(ctx, m) for m in chosen})


def group_by_aircraft(options: list[Option]) -> dict[str, list[Option]]:
    out: dict[str, list[Option]] = defaultdict(list)
    for o in options:
        out[o.aircraft_id].append(o)
    return out
