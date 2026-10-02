"""ResourceLedger: tracks what a partial plan has already used, so a planner can place the next
sortie without breaking cross-sortie rules (aircraft turnaround, crew rest and duty, base stock,
runway capacity). Used by the greedy baselines; `validate.py` deliberately does NOT use it (the
validator must be an independent re-implementation).

Rules (placeholders, configurable via PlanningConfig / DutyRules):
- An aircraft is busy from takeoff until landing + turnaround.
- A crew member needs `min_rest_min` between sorties and before the first (from last_duty_end),
  and carries `duty_minutes_last_24h` into any 24 h window that starts before t0; duty in any
  rolling 24 h window must stay within `max_duty_min_24h`.
- Stock used by loadouts at a base never exceeds that base's stock.
- Takeoffs and landings at a base per slot never exceed runways * runway_ops_per_runway_per_slot.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.models.entities import CrewMember, Mission
from app.models.enums import ReasonCode
from app.planning.config import NO_LOADOUT
from app.planning.context import PlanningContext
from app.planning.feasibility import Option, SlotOption, eligible_crew, required_roles

DAY_MIN = 1440


@dataclass(frozen=True)
class Placed:
    mission_id: str
    aircraft_id: str
    loadout_id: str
    base_id: str
    takeoff: int
    land: int
    crew_ids: tuple[str, ...]


class ResourceLedger:
    def __init__(self, ctx: PlanningContext) -> None:
        self.ctx = ctx
        self.placed: list[Placed] = []
        self._aircraft: dict[str, list[Placed]] = defaultdict(list)
        self._crew: dict[str, list[Placed]] = defaultdict(list)
        self._stock: dict[tuple[str, str], int] = defaultdict(int)
        self._ops: dict[tuple[str, int], int] = defaultdict(int)

    # ------------------------------------------------------------------------------- checks
    def aircraft_free(self, aircraft_id: str, takeoff: int, land: int) -> bool:
        a = self.ctx.aircraft[aircraft_id]
        mine = self.ctx.turnaround_min(a.base_id, a.type_id)
        return all(
            takeoff >= p.land + mine or land + mine <= p.takeoff
            for p in self._aircraft[aircraft_id]
        )

    def stock_ok(self, base_id: str, loadout_id: str) -> bool:
        if loadout_id == NO_LOADOUT:
            return True
        return all(
            self._stock[(base_id, item)] + qty <= self.ctx.stock.get((base_id, item), 0)
            for item, qty in self.ctx.loadouts[loadout_id].items.items()
        )

    def runway_ok(self, base_id: str, takeoff: int, land: int) -> bool:
        slot = self.ctx.cfg.slot_min
        cap = self.ctx.bases[base_id].runways * self.ctx.cfg.runway_ops_per_runway_per_slot
        need: dict[int, int] = defaultdict(int)
        need[takeoff // slot] += 1
        need[land // slot] += 1
        return all(self._ops[(base_id, b)] + n <= cap for b, n in need.items())

    def crew_free(self, c: CrewMember, takeoff: int, land: int) -> ReasonCode | None:
        rest = self.ctx.rules.min_rest_min
        mine = self._crew[c.id]
        for p in mine:
            if not (takeoff >= p.land + rest or land + rest <= p.takeoff):
                return ReasonCode.CREW_REST_VIOLATION
        spans = sorted([*((p.takeoff, p.land) for p in mine), (takeoff, land)])
        cap = self.ctx.rules.max_duty_min_24h
        for _, end in spans:
            total = sum(e - s for s, e in spans if s <= end and e > end - DAY_MIN)
            if end - DAY_MIN < 0:
                total += c.duty_minutes_last_24h
            if total > cap:
                return ReasonCode.CREW_DUTY_LIMIT
        return None

    def pick_crew(
        self, mission: Mission, opt: Option, slot: SlotOption
    ) -> tuple[list[str] | None, ReasonCode | None]:
        """Choose crew for every required role (least planned duty first), or say why not."""
        ctx = self.ctx
        a = ctx.aircraft[opt.aircraft_id]
        type_ = ctx.types[a.type_id]
        takeoff, land = slot.takeoff_min, slot.takeoff_min + opt.land_offset
        chosen: list[str] = []
        why: ReasonCode | None = None
        needs = sorted(required_roles(mission, type_).items(), key=lambda kv: kv[0].value)
        for role, need in needs:
            _, _, rested = eligible_crew(ctx, a.base_id, a.type_id, role, opt.land_offset, takeoff)
            free: list[tuple[int, str]] = []
            for c in rested:
                if c.id in chosen:
                    continue
                problem = self.crew_free(c, takeoff, land)
                if problem is None:
                    free.append((sum(p.land - p.takeoff for p in self._crew[c.id]), c.id))
                else:
                    why = problem
            free.sort()
            if len(free) < need:
                return None, why or ReasonCode.NO_QUALIFIED_CREW
            chosen.extend(cid for _, cid in free[:need])
        return chosen, None

    # ------------------------------------------------------------------------------ commit
    def try_place(
        self, mission: Mission, opt: Option, slot: SlotOption
    ) -> tuple[Placed | None, ReasonCode | None]:
        takeoff, land = slot.takeoff_min, slot.takeoff_min + opt.land_offset
        if not self.aircraft_free(opt.aircraft_id, takeoff, land):
            return None, ReasonCode.TURNAROUND_CONFLICT
        if not self.stock_ok(opt.base_id, opt.loadout_id):
            return None, ReasonCode.NO_LOADOUT_STOCK
        if not self.runway_ok(opt.base_id, takeoff, land):
            return None, ReasonCode.BASE_RUNWAY_CAPACITY
        crew, why = self.pick_crew(mission, opt, slot)
        if crew is None:
            return None, why
        placed = Placed(
            mission.id, opt.aircraft_id, opt.loadout_id, opt.base_id, takeoff, land, tuple(crew)
        )
        self.add(placed)
        return placed, None

    def add(self, p: Placed) -> None:
        self.placed.append(p)
        self._aircraft[p.aircraft_id].append(p)
        for cid in p.crew_ids:
            self._crew[cid].append(p)
        if p.loadout_id != NO_LOADOUT:
            for item, qty in self.ctx.loadouts[p.loadout_id].items.items():
                self._stock[(p.base_id, item)] += qty
        slot = self.ctx.cfg.slot_min
        self._ops[(p.base_id, p.takeoff // slot)] += 1
        self._ops[(p.base_id, p.land // slot)] += 1

    def remove(self, p: Placed) -> None:
        self.placed.remove(p)
        self._aircraft[p.aircraft_id].remove(p)
        for cid in p.crew_ids:
            self._crew[cid].remove(p)
        if p.loadout_id != NO_LOADOUT:
            for item, qty in self.ctx.loadouts[p.loadout_id].items.items():
                self._stock[(p.base_id, item)] -= qty
        slot = self.ctx.cfg.slot_min
        self._ops[(p.base_id, p.takeoff // slot)] -= 1
        self._ops[(p.base_id, p.land // slot)] -= 1

