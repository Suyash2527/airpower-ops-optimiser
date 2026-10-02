"""Plan endpoints (API_SPEC "Planning"): generate, fetch, list, validate, compare, approve."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.state import (
    PlanInputs,
    active_plan,
    expire_open,
    load_plan,
    set_plan_status,
    store_plan,
)
from app.audit import log as audit
from app.core.db import get_session
from app.core.errors import ApiError
from app.ingest import service
from app.models import tables
from app.models.entities import Model
from app.models.enums import PlanStatus
from app.models.plans import Plan, PlanDiff, PlanKPIs
from app.models.scenario import ScenarioFile
from app.planning.context import PlanningContext
from app.planning.diff import diff_plans
from app.planning.feasibility import build_matrix
from app.planning.greedy import plan as greedy_plan
from app.planning.optimiser import SolveParams, solve
from app.planning.validate import Violation, validate_plan
from app.planning.weights import preset_names

router = APIRouter(prefix="/plans", tags=["plans"])


class GenerateRequest(Model):
    scenario_id: str
    planner: Literal["cpsat", "greedy", "fifo"] = "cpsat"
    time_limit_s: float | None = Field(None, gt=0, le=300)
    weight_preset: str = "coverage_first"
    fused: bool = True
    secondary: bool = True
    now_min: int = Field(0, ge=0, le=100_000)
    seed: int = 0


class PlanResponse(Plan):
    inputs: PlanInputs
    violations: int = 0


class ViolationOut(BaseModel):
    code: str
    message: str
    assignment_id: str | None
    mission_id: str | None


class ValidateResponse(BaseModel):
    plan_id: str
    valid: bool
    violations: list[ViolationOut]
    note: str


class CompareResponse(BaseModel):
    a: str
    b: str
    kpis_a: PlanKPIs
    kpis_b: PlanKPIs
    kpi_delta: dict[str, float]
    diff: PlanDiff
    data_label: str


def _scenario_for(
    session: Session, scenario_id: str, inputs: PlanInputs
) -> tuple[ScenarioFile, Any]:
    if inputs.fused:
        snap = service.fused_snapshot(
            session, scenario_id, now_min=inputs.now_min, secondary=inputs.secondary
        )
        if snap is None:
            raise ApiError(404, "not_found", f"unknown scenario: {scenario_id}")
        return snap.scenario, snap.meta
    scenario = service.current_scenario(session, scenario_id)
    if scenario is None:
        raise ApiError(404, "not_found", f"unknown scenario: {scenario_id}")
    return scenario, None


_load = load_plan


def _violations(vs: list[Violation]) -> list[ViolationOut]:
    return [ViolationOut(code=v.code, message=v.message, assignment_id=v.assignment_id,
                         mission_id=v.mission_id) for v in vs]


@router.post("/generate", response_model=PlanResponse)
def generate(
    body: GenerateRequest, request: Request, session: Session = Depends(get_session)
) -> PlanResponse:
    settings = request.app.state.settings
    if body.weight_preset not in preset_names():
        raise ApiError(422, "unknown_weight_preset",
                       f"choose one of {', '.join(preset_names())}")
    limit = body.time_limit_s or settings.solver_time_limit_s
    inputs = PlanInputs(
        planner=body.planner, time_limit_s=limit, weight_preset=body.weight_preset,
        fused=body.fused, secondary=body.secondary, now_min=body.now_min, seed=body.seed,
    )
    scenario, meta = _scenario_for(session, body.scenario_id, inputs)
    ctx = PlanningContext(scenario, fusion_meta=meta, now_min=body.now_min)
    if body.planner == "cpsat":
        plan = solve(ctx, body.scenario_id, SolveParams(
            time_limit_s=limit, num_workers=settings.solver_workers, seed=body.seed,
            weight_preset=body.weight_preset,
        ), build_matrix(ctx))
    else:
        name = "greedy_priority" if body.planner == "greedy" else "fifo"
        plan = greedy_plan(ctx, body.scenario_id, name)  # type: ignore[arg-type]

    found = validate_plan(scenario, plan, now_min=body.now_min, fusion_meta=meta)
    if found:  # a planner bug: never hand out or store a plan the validator rejects
        first = found[0]
        raise ApiError(500, "plan_failed_validation",
                       f"{len(found)} violation(s); first: {first.code}: {first.message}")

    plan = store_plan(session, body.scenario_id, plan, inputs)
    audit.append(
        session, body.scenario_id, actor="system", action="plan.generate", object_type="plan",
        object_id=plan.id,
        details={"planner": body.planner, "weight_preset": body.weight_preset,
                 "solver_status": plan.solver.status, "covered": plan.kpis.missions_covered},
    )
    session.commit()
    request.app.state.hub.publish(body.scenario_id, "plan.created", {
        "plan_id": plan.id, "version": plan.version, "planner": body.planner,
        "coverage": plan.kpis.priority_weighted_coverage})
    return PlanResponse(**plan.model_dump(), inputs=inputs, violations=0)


@router.get("/compare", response_model=CompareResponse)
def compare(
    a: str = Query(...), b: str = Query(...), session: Session = Depends(get_session)
) -> CompareResponse:
    row_a, plan_a, _ = _load(session, a)
    row_b, plan_b, _ = _load(session, b)
    if row_a.scenario_id != row_b.scenario_id:
        raise ApiError(409, "different_scenarios", "plans belong to different scenarios")
    ka, kb = plan_a.kpis.model_dump(), plan_b.kpis.model_dump()
    delta = {k: round(kb[k] - ka[k], 4) for k in ka
             if isinstance(ka[k], int | float) and kb[k] is not None and ka[k] is not None}
    return CompareResponse(
        a=a, b=b, kpis_a=plan_a.kpis, kpis_b=plan_b.kpis, kpi_delta=delta,
        diff=diff_plans(plan_a, plan_b), data_label=plan_b.data_label,
    )


@router.get("", response_model=list[PlanResponse])
def list_plans(
    scenario_id: str, session: Session = Depends(get_session)
) -> list[PlanResponse]:
    rows = session.exec(
        select(tables.PlanRow).where(tables.PlanRow.scenario_id == scenario_id)
        .order_by(tables.PlanRow.pk)  # type: ignore[arg-type]
    ).all()
    return [
        PlanResponse(**Plan.model_validate(r.data["plan"]).model_dump(),
                     inputs=PlanInputs.model_validate(r.data["inputs"]))
        for r in rows
    ]


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str, session: Session = Depends(get_session)) -> PlanResponse:
    _, plan, inputs = _load(session, plan_id)
    return PlanResponse(**plan.model_dump(), inputs=inputs)


@router.post("/{plan_id}/validate", response_model=ValidateResponse)
def validate(plan_id: str, session: Session = Depends(get_session)) -> ValidateResponse:
    """Re-run the independent validator against the snapshot the plan was made from, rebuilt
    with the scenario's current pins (so a plan can become invalid after a human pin)."""
    row, plan, inputs = _load(session, plan_id)
    scenario, meta = _scenario_for(session, row.scenario_id, inputs)
    found = validate_plan(scenario, plan, now_min=inputs.now_min, fusion_meta=meta)
    return ValidateResponse(
        plan_id=plan_id, valid=not found, violations=_violations(found),
        note="checked against the snapshot rebuilt with the scenario's current pins",
    )


class ApproveRequest(Model):
    actor: str
    reason: str | None = None


@router.post("/{plan_id}/approve", response_model=PlanResponse)
def approve(
    plan_id: str, body: ApproveRequest, request: Request, session: Session = Depends(get_session)
) -> PlanResponse:
    """Make a draft plan the active plan; the previous active plan is superseded (audited). A
    human decision only: nothing in the system calls this by itself."""
    row, plan, inputs = _load(session, plan_id)
    if plan.status is not PlanStatus.DRAFT:
        raise ApiError(409, "not_approvable", f"{plan_id} is {plan.status.value}, not draft")
    if not body.actor.strip():
        raise ApiError(422, "validation_error", "actor must not be empty")
    hub = request.app.state.hub
    old = active_plan(session, row.scenario_id)
    if old is not None:
        set_plan_status(session, old[0], PlanStatus.SUPERSEDED)
        audit.append(session, row.scenario_id, actor=body.actor, action="plan.supersede",
                     object_type="plan", object_id=old[1].id, details={"replaced_by": plan_id})
        expire_open(session, hub, row.scenario_id, old[1].id)
    set_plan_status(session, row, PlanStatus.APPROVED)
    audit.append(session, row.scenario_id, actor=body.actor.strip(), action="plan.approve",
                 object_type="plan", object_id=plan_id,
                 details={"reason": body.reason, "version": plan.version,
                          "superseded": old[1].id if old else None})
    session.commit()
    hub.publish(row.scenario_id, "plan.approved", {"plan_id": plan_id, "version": plan.version})
    return PlanResponse(**plan.model_copy(update={"status": PlanStatus.APPROVED}).model_dump(),
                        inputs=inputs)
