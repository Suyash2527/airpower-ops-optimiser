"""Independent plan validator (ALGORITHMS §9, ARCHITECTURE decision 2).

Re-checks every hard constraint of a finished `Plan` straight from the scenario data. It does NOT
import `feasibility.py`, the feasibility matrix or the `ResourceLedger`, so a bug in the engine or
a planner cannot hide here. What it does share, on purpose, are low-level primitives that have
their own tests: `core.physics` (density altitude), `sim.geo.haversine_km` and
`planning.geometry.build_profile` (the route sampling that defines "the route"). Any plan from any
planner must produce an empty list.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
from shapely import Point, Polygon

from app.core.physics import available_payload_kg, density_altitude_ft, range_factor
from app.ingest.fusion import effective_aircraft_status
from app.ingest.models import RecordFusion
from app.models.entities import AirspaceZone, WeatherRecord
from app.models.enums import (
    AircraftStatus,
    AirspaceKind,
    MissionStatus,
    ReasonCode,
    WeatherKind,
)
from app.models.plans import Assignment, Plan
from app.models.scenario import ScenarioFile
from app.planning.config import NO_LOADOUT, PlanningConfig
from app.planning.geometry import build_profile, haversine_vec
from app.sim.geo import haversine_km

DAY = 1440


@dataclass(frozen=True)
class Violation:
    code: str  # a ReasonCode value, or a plan-integrity code such as PARTIAL_MISSION
    message: str
    assignment_id: str | None = None
    mission_id: str | None = None


def validate_plan(
    scenario: ScenarioFile,
    plan: Plan,
    *,
    cfg: PlanningConfig | None = None,
    now_min: int = 0,
    parent: Plan | None = None,
    fusion_meta: dict[str, dict[str, RecordFusion]] | None = None,
) -> list[Violation]:
    return _Validator(scenario, plan, cfg or PlanningConfig(), now_min, parent, fusion_meta).run()


class _Validator:
    def __init__(
        self, s: ScenarioFile, plan: Plan, cfg: PlanningConfig, now_min: int,
        parent: Plan | None, meta: dict[str, dict[str, RecordFusion]] | None,
    ) -> None:
        self.s, self.plan, self.cfg, self.now = s, plan, cfg, now_min
        self.parent, self.meta = parent, meta
        self.out: list[Violation] = []
        self.type = {t.id: t for t in s.aircraft_types}
        self.base = {b.id: b for b in s.bases}
        self.ac = {a.id: a for a in s.aircraft}
        self.crew = {c.id: c for c in s.crew}
        self.load = {ld.id: ld for ld in s.loadouts}
        self.mission = {m.id: m for m in s.missions}
        self.stock = {(w.base_id, w.item_type): w.qty_available for w in s.weapon_stocks}
        self.rules = s.scenario.duty_rules
        self.wx: dict[str, list[WeatherRecord]] = defaultdict(list)
        for w in s.weather:
            self.wx[w.base_id].append(w)
        for recs in self.wx.values():
            recs.sort(key=lambda w: (w.time_min, w.kind is WeatherKind.OBSERVATION))

    def bad(self, code: ReasonCode | str, msg: str, a: Assignment | None = None,
            mission_id: str | None = None) -> None:
        self.out.append(Violation(
            code.value if isinstance(code, ReasonCode) else code, msg,
            a.id if a else None, a.mission_id if a else mission_id,
        ))

    # ------------------------------------------------------------------------------------ run
    def run(self) -> list[Violation]:
        ids = Counter(a.id for a in self.plan.assignments)
        for aid, n in ids.items():
            if n > 1:
                self.bad("DUPLICATE_ASSIGNMENT_ID", f"assignment id {aid} used {n} times")
        usable = [a for a in self.plan.assignments if self._known(a)]
        for a in usable:
            self._sortie(a)
        self._missions(usable)
        self._stock(usable)
        self._aircraft_overlap(usable)
        self._crew_rules(usable)
        self._runways(usable)
        self._frozen()
        return self.out

    def _known(self, a: Assignment) -> bool:
        problems = []
        if a.mission_id not in self.mission:
            problems.append(f"mission {a.mission_id}")
        if a.aircraft_id not in self.ac:
            problems.append(f"aircraft {a.aircraft_id}")
        problems += [f"crew {c}" for c in a.crew_ids if c not in self.crew]
        if a.loadout_id != NO_LOADOUT and a.loadout_id not in self.load:
            problems.append(f"loadout {a.loadout_id}")
        if problems:
            self.bad("UNKNOWN_REFERENCE", "unknown " + ", ".join(problems), a)
        return not problems

    # -------------------------------------------------------------------- per-sortie checks
    def _sortie(self, a: Assignment) -> None:
        m, ac = self.mission[a.mission_id], self.ac[a.aircraft_id]
        ty, base = self.type[ac.type_id], self.base[ac.base_id]
        if m.status not in (MissionStatus.PENDING, MissionStatus.PLANNED):
            self.bad("MISSION_NOT_PLANNABLE", f"{m.id} is {m.status.value}", a)
        if m.capability_required not in ty.role:  # 1 capability
            self.bad(
                ReasonCode.NO_CAPABLE_AIRCRAFT, f"{ty.id} cannot do {m.capability_required}", a
            )
        if a.base_from != base.id or a.base_to != base.id:
            self.bad("BASE_MISMATCH", f"{ac.id} is based at {base.id}", a)

        dist = haversine_km(base.lat, base.lon, m.aoi.center.lat, m.aoi.center.lon)
        transit = math.ceil(dist / ty.cruise_kmh * 60)
        flight = 2 * transit + m.duration_min
        if a.land_min != a.takeoff_min + flight:
            self.bad(
                "TIMING_INCONSISTENT",
                f"landing T+{a.land_min} but takeoff T+{a.takeoff_min} + flight {flight} min", a,
            )
        self._aircraft(a, m, ac, ty, flight)
        self._range(a, base, ty, dist, flight)
        self._loadout(a, m, base, ty)
        arrive = a.takeoff_min + transit  # 6 time window
        if arrive < m.window_start_min or arrive + m.duration_min > m.window_end_min:
            self.bad(
                ReasonCode.TIME_WINDOW_UNREACHABLE,
                f"on station T+{arrive}..T+{arrive + m.duration_min} outside window "
                f"T+{m.window_start_min}..T+{m.window_end_min}", a,
            )
        profile = build_profile(
            (base.lat, base.lon), (m.aoi.center.lat, m.aoi.center.lon), ty.cruise_kmh,
            m.duration_min, self.cfg.route_step_km, self.cfg.on_station_step_min,
        )
        self._airspace(a, profile)
        self._weather(a, m, base, ty, transit)
        self._threat(a, m, profile)
        self._crew_roles(a, m, ty, base.id)

    def _aircraft(self, a, m, ac, ty, flight) -> None:
        status = (
            effective_aircraft_status(ac, (self.meta or {}).get("aircraft", {}).get(ac.id))
            if self.meta else ac.status
        )
        if not a.frozen:  # frozen sorties are already under way
            if a.takeoff_min < self.now:
                self.bad("TAKEOFF_IN_PAST", f"takeoff T+{a.takeoff_min} before now T+{self.now}", a)
            if a.takeoff_min < ac.available_from_min:
                self.bad(ReasonCode.AIRCRAFT_UNSERVICEABLE,
                         f"{ac.id} not available before T+{ac.available_from_min}", a)
            if status in (AircraftStatus.UNSERVICEABLE, AircraftStatus.IN_MAINTENANCE) and (
                ac.available_from_min <= self.now
            ):
                self.bad(ReasonCode.AIRCRAFT_UNSERVICEABLE, f"{ac.id} is {status.value}", a)
            if status is AircraftStatus.DEGRADED and not self.cfg.allow_degraded:
                self.bad(ReasonCode.AIRCRAFT_UNSERVICEABLE, f"{ac.id} is DEGRADED", a)
        if ac.hours_since_maintenance + flight / 60 > ty.flight_hours_between_maintenance:
            self.bad(
                ReasonCode.MAINTENANCE_DUE, f"{ac.id} would exceed its maintenance interval", a
            )

    def _range(self, a, base, ty, dist, flight) -> None:
        rf = range_factor(ty.id, density_altitude_ft(base.elevation_m, base.ref_temperature_c))
        if dist > ty.combat_radius_km * rf:
            self.bad(ReasonCode.OUT_OF_RANGE, f"{dist:.0f} km exceeds derated radius", a)
        if flight > ty.endurance_min * rf * (1 - self.cfg.reserve_fraction):
            self.bad(
                ReasonCode.INSUFFICIENT_FUEL_ENDURANCE, f"{flight} min exceeds usable endurance", a
            )

    def _loadout(self, a, m, base, ty) -> None:
        required = m.loadout_category_required
        if a.loadout_id == NO_LOADOUT:
            if required is not None:
                self.bad(
                    ReasonCode.LOADOUT_INCOMPATIBLE, f"{m.id} needs a {required.value} loadout", a
                )
            return
        ld = self.load[a.loadout_id]
        if required is not None and ld.category is not required:
            self.bad(ReasonCode.LOADOUT_INCOMPATIBLE, f"{ld.id} is {ld.category.value}", a)
        if ty.id not in ld.compatible_aircraft_types or ld.id not in ty.compatible_loadouts:
            self.bad(ReasonCode.LOADOUT_INCOMPATIBLE, f"{ld.id} does not fit {ty.id}", a)
        if ld.mass_kg > available_payload_kg(ty.id, base.elevation_m, base.ref_temperature_c):
            self.bad(ReasonCode.LOADOUT_INCOMPATIBLE, f"{ld.id} too heavy at {base.id}", a)

    def _airspace(self, a, profile) -> None:
        times = a.takeoff_min + profile.offset
        zones = [z for z in self.s.airspace]

        def inside(z: AirspaceZone) -> np.ndarray:
            rings = z.polygon.coordinates
            poly = Polygon(rings[0], holes=rings[1:] or None)
            hit = np.array(
                [poly.contains(Point(x, y)) for x, y in zip(profile.lon, profile.lat, strict=True)]
            )
            return hit & (times >= z.active_from_min) & (times <= z.active_to_min)

        covered = np.zeros(len(times), dtype=bool)
        for z in zones:
            if z.kind is AirspaceKind.CORRIDOR:
                covered |= inside(z)
        for z in zones:
            if z.kind is not AirspaceKind.CORRIDOR and (inside(z) & ~covered).any():
                self.bad(
                    ReasonCode.AIRSPACE_CONFLICT, f"route crosses {z.kind.value} zone {z.id}", a
                )

    def _wx_at(self, base_id: str, minute: float) -> WeatherRecord | None:
        recs = self.wx.get(base_id)
        if not recs:
            return None
        chosen = recs[0]
        for r in recs:
            if r.time_min <= minute:
                chosen = r
        return chosen

    def _weather(self, a, m, base, ty, transit) -> None:
        mn = ty.weather_minima

        def ok(r: WeatherRecord) -> bool:
            return (r.visibility_km >= mn.min_visibility_km and r.ceiling_ft >= mn.min_ceiling_ft
                    and r.wind_kmh <= mn.max_wind_kmh)

        for minute in (a.takeoff_min, a.land_min):
            r = self._wx_at(base.id, minute)
            if r is not None and not ok(r):
                self.bad(
                    ReasonCode.WEATHER_BELOW_MINIMA_BASE, f"{base.id} below minima at T+{minute}", a
                )
                break
        near = min(self.base.values(), key=lambda b: (
            haversine_km(m.aoi.center.lat, m.aoi.center.lon, b.lat, b.lon), b.id))
        arrive = a.takeoff_min + transit
        depart = arrive + m.duration_min
        hours = range(-(-arrive // 60) * 60, depart, 60)
        for minute in sorted({arrive, depart, *hours}):
            r = self._wx_at(near.id, minute)
            if r is not None and not ok(r):
                self.bad(ReasonCode.WEATHER_BELOW_MINIMA_TARGET,
                         f"target area below minima at T+{minute}", a)
                break

    def _threat(self, a, m, profile) -> None:
        times = a.takeoff_min + profile.offset
        total = 0.0
        for th in self.s.threats:
            d = haversine_vec(profile.lat, profile.lon, th.center.lat, th.center.lon)
            near = d <= th.radius_km
            live = (times >= th.active_from_min) & (times <= th.active_to_min)
            minutes = float(profile.dt[near & live].sum())
            total += th.severity * th.confidence * minutes / profile.total_min
        if min(1.0, total) > m.max_acceptable_risk:
            self.bad(ReasonCode.THREAT_RISK_EXCEEDS_LIMIT,
                     f"threat exposure {min(1.0, total):.2f} > limit {m.max_acceptable_risk}", a)

    def _crew_roles(self, a, m, ty, base_id) -> None:
        need = Counter(ty.crew_roles)
        for role, n in Counter(m.min_crew_roles).items():
            need[role] = max(need[role], n)
        if len(set(a.crew_ids)) != len(a.crew_ids):
            self.bad(ReasonCode.NO_QUALIFIED_CREW, "a crew member is listed twice", a)
        have = Counter()
        for cid in a.crew_ids:
            c = self.crew[cid]
            have[c.role] += 1
            if c.base_id != base_id:
                self.bad(ReasonCode.NO_QUALIFIED_CREW, f"{cid} is at {c.base_id}, not {base_id}", a)
            if ty.id not in c.qualifications:
                self.bad(ReasonCode.NO_QUALIFIED_CREW, f"{cid} is not qualified on {ty.id}", a)
            if c.status.value != "AVAILABLE":
                self.bad(ReasonCode.NO_QUALIFIED_CREW, f"{cid} is {c.status.value}", a)
        if have != need:
            self.bad(ReasonCode.NO_QUALIFIED_CREW,
                     f"crew roles {dict(have)} do not match required {dict(need)}", a)

    # ------------------------------------------------------------------------- plan-level
    def _missions(self, usable: list[Assignment]) -> None:
        per: dict[str, list[Assignment]] = defaultdict(list)
        for a in usable:
            per[a.mission_id].append(a)
        unassigned = {u.mission_id for u in self.plan.unassigned}
        for mid, rows in per.items():
            need = self.mission[mid].aircraft_required
            if len(rows) != need:
                self.bad("PARTIAL_MISSION", f"{mid} has {len(rows)} sorties, needs {need}",
                         mission_id=mid)
            if len({r.aircraft_id for r in rows}) != len(rows):
                self.bad("DUPLICATE_AIRCRAFT_IN_MISSION", f"{mid} uses an aircraft twice",
                         mission_id=mid)
            if mid in unassigned:
                self.bad("INCONSISTENT_PLAN", f"{mid} is both assigned and unassigned",
                         mission_id=mid)

    def _stock(self, usable: list[Assignment]) -> None:
        used: Counter[tuple[str, str]] = Counter()
        for a in usable:
            if a.loadout_id == NO_LOADOUT:
                continue
            for item, qty in self.load[a.loadout_id].items.items():
                used[(self.ac[a.aircraft_id].base_id, item)] += qty
        for (b, item), n in used.items():
            if n > self.stock.get((b, item), 0):
                self.bad(ReasonCode.NO_LOADOUT_STOCK,
                         f"{b} stock of {item}: plan uses {n}, has {self.stock.get((b, item), 0)}")

    def _aircraft_overlap(self, usable: list[Assignment]) -> None:
        by_ac: dict[str, list[Assignment]] = defaultdict(list)
        for a in usable:
            by_ac[a.aircraft_id].append(a)
        for aid, rows in by_ac.items():
            ac = self.ac[aid]
            gap = self.base[ac.base_id].turnaround_min_by_type.get(
                ac.type_id, self.type[ac.type_id].turnaround_min)
            rows.sort(key=lambda r: r.takeoff_min)
            for first, second in zip(rows, rows[1:], strict=False):
                if second.takeoff_min < first.land_min + gap:
                    self.bad(ReasonCode.TURNAROUND_CONFLICT,
                             f"{aid}: {first.id} lands T+{first.land_min}, {second.id} takes off "
                             f"T+{second.takeoff_min} (turnaround {gap})", second)

    def _crew_rules(self, usable: list[Assignment]) -> None:
        by_crew: dict[str, list[Assignment]] = defaultdict(list)
        for a in usable:
            for cid in a.crew_ids:
                by_crew[cid].append(a)
        for cid, rows in by_crew.items():
            c = self.crew[cid]
            rows.sort(key=lambda r: r.takeoff_min)
            if rows[0].takeoff_min - c.last_duty_end_min < self.rules.min_rest_min:
                self.bad(ReasonCode.CREW_REST_VIOLATION,
                         f"{cid} has less than {self.rules.min_rest_min} min rest before "
                         f"{rows[0].id}", rows[0])
            for first, second in zip(rows, rows[1:], strict=False):
                if second.takeoff_min - first.land_min < self.rules.min_rest_min:
                    self.bad(ReasonCode.CREW_REST_VIOLATION,
                             f"{cid}: only {second.takeoff_min - first.land_min} min between "
                             f"{first.id} and {second.id}", second)
            for r in rows:
                window = sum(
                    x.land_min - x.takeoff_min for x in rows
                    if x.takeoff_min <= r.land_min and x.land_min > r.land_min - DAY
                )
                if r.land_min - DAY < 0:
                    window += c.duty_minutes_last_24h
                if window > self.rules.max_duty_min_24h:
                    self.bad(ReasonCode.CREW_DUTY_LIMIT,
                             f"{cid}: {window} duty min in the 24 h to T+{r.land_min}", r)

    def _runways(self, usable: list[Assignment]) -> None:
        ops: Counter[tuple[str, int]] = Counter()
        slot = self.cfg.slot_min
        for a in usable:
            b = self.ac[a.aircraft_id].base_id
            ops[(b, a.takeoff_min // slot)] += 1
            ops[(b, a.land_min // slot)] += 1
        for (b, k), n in ops.items():
            cap = self.base[b].runways * self.cfg.runway_ops_per_runway_per_slot
            if n > cap:
                self.bad(ReasonCode.BASE_RUNWAY_CAPACITY,
                         f"{b} has {n} runway operations in slot {k} (capacity {cap})")

    def _frozen(self) -> None:
        if self.parent is None:
            return
        now = {a.id: a for a in self.plan.assignments}
        for old in self.parent.assignments:
            if not old.frozen:
                continue
            new = now.get(old.id)
            same = new is not None and all(
                getattr(new, f) == getattr(old, f)
                for f in ("mission_id", "aircraft_id", "crew_ids", "loadout_id", "takeoff_min",
                          "land_min")
            )
            if not same:
                self.bad(ReasonCode.FROZEN_AIRBORNE, f"frozen assignment {old.id} was changed", new)
