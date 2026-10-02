"""Planning endpoints. Phase 3: `GET /feasibility` (API_SPEC "Planning"), the debug / explain view
of which aircraft and loadouts can fly a mission and what blocks the rest."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.core.db import get_session
from app.core.errors import ApiError
from app.ingest import service
from app.models.enums import ReasonCode
from app.models.plans import RiskBreakdown
from app.planning.context import PlanningContext
from app.planning.explain import PHRASE
from app.planning.feasibility import PLANNABLE, build_mission

router = APIRouter(tags=["planning"])


class ReasonOut(BaseModel):
    code: ReasonCode
    detail: str


class OptionOut(BaseModel):
    aircraft_id: str
    loadout_id: str
    base_id: str
    n_slots: int
    earliest_takeoff_min: int
    latest_takeoff_min: int
    best_takeoff_min: int
    best_risk: RiskBreakdown
    land_offset_min: int


class BlockedOut(BaseModel):
    aircraft_id: str
    loadout_id: str | None
    base_id: str
    reasons: list[ReasonOut]


class TallyOut(BaseModel):
    code: ReasonCode
    phrase: str
    count: int  # aircraft options (aircraft x loadout) blocked by this reason
    example: str | None


class FeasibilityResponse(BaseModel):
    scenario_id: str
    mission_id: str
    data_label: str
    fused: bool
    now_min: int
    aircraft_required: int
    capable_aircraft: int
    options_total: int
    options_feasible: int
    feasible_aircraft: int
    coverable: bool
    mission_level: list[ReasonOut]
    blocked_by: list[TallyOut]
    options: list[OptionOut]
    blocked: list[BlockedOut]
    notes: list[str]


NOTES = [
    "Counts are aircraft options (aircraft x loadout); one option can appear under several "
    "reasons. Reserve, thresholds and risk formulas are placeholders (see DECISIONS.md).",
    "Weather risk and service risk are placeholder formulas until the Phase 7 models exist.",
]


@router.get("/feasibility", response_model=FeasibilityResponse)
def feasibility(
    scenario_id: str,
    mission_id: str,
    fused: bool = True,
    secondary: bool = True,
    now_min: Annotated[int, Query(ge=0, le=100_000)] = 0,
    session: Session = Depends(get_session),
) -> FeasibilityResponse:
    if fused:
        snap = service.fused_snapshot(session, scenario_id, now_min=now_min, secondary=secondary)
        scenario, meta = (snap.scenario, snap.meta) if snap else (None, None)
    else:
        scenario, meta = service.current_scenario(session, scenario_id), None
    if scenario is None:
        raise ApiError(404, "not_found", f"unknown scenario: {scenario_id}")
    ctx = PlanningContext(scenario, fusion_meta=meta, now_min=now_min)
    mission = ctx.missions.get(mission_id)
    if mission is None:
        raise ApiError(404, "not_found", f"unknown mission: {mission_id}")
    if mission.status not in PLANNABLE:
        raise ApiError(409, "not_plannable", f"{mission_id} is {mission.status.value}")

    feas = build_mission(ctx, mission)
    options = [
        OptionOut(
            aircraft_id=o.aircraft_id, loadout_id=o.loadout_id, base_id=o.base_id,
            n_slots=len(o.slots), earliest_takeoff_min=o.slots[0].takeoff_min,
            latest_takeoff_min=o.slots[-1].takeoff_min, best_takeoff_min=o.best.takeoff_min,
            best_risk=o.best.risk, land_offset_min=o.land_offset,
        )
        for o in feas.options
    ]
    tally = [
        TallyOut(code=c, phrase=PHRASE.get(c, c.value), count=n, example=feas.examples.get(c))
        for c, n in sorted(feas.tally.items(), key=lambda kv: (-kv[1], kv[0].value))
    ]
    return FeasibilityResponse(
        scenario_id=scenario_id, mission_id=mission_id,
        data_label=scenario.scenario.data_label, fused=fused, now_min=now_min,
        aircraft_required=feas.required, capable_aircraft=feas.n_capable,
        options_total=feas.n_combos, options_feasible=len(options),
        feasible_aircraft=len(feas.feasible_aircraft), coverable=feas.coverable,
        mission_level=[ReasonOut(code=f.code, detail=f.detail) for f in feas.mission_level],
        blocked_by=tally, options=options,
        blocked=[
            BlockedOut(
                aircraft_id=b.aircraft_id, loadout_id=b.loadout_id, base_id=b.base_id,
                reasons=[ReasonOut(code=f.code, detail=f.detail) for f in b.reasons],
            )
            for b in feas.blocked
        ],
        notes=NOTES,
    )

