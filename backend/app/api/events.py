"""Event endpoints (API_SPEC "Events & retasking"): inject an event, simulate disruptions, history.
An event is stored and applied to the scenario state; if a plan is active, ranked retasking
proposals are generated. Nothing is applied to the active plan: a human approves a proposal."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session

from app.api.plans import _scenario_for
from app.api.state import (
    StoredProposal,
    active_plan,
    expire_open,
    proposals_of,
    save_proposal,
)
from app.audit import log as audit
from app.core.db import get_session
from app.core.errors import ApiError
from app.ingest import service
from app.models.entities import Event, Model, Provenance
from app.models.enums import EventOrigin, EventType, ProposalStatus
from app.models.plans import Proposal
from app.planning.context import PlanningContext
from app.planning.retask import RetaskParams, describe_event, propose
from app.sim.events import EventError, apply_event, simulate_events, validate_event

router = APIRouter(prefix="/events", tags=["events"])


class EventRequest(Model):
    scenario_id: str
    type: EventType
    time_min: int = Field(ge=0, le=100_000)
    payload: dict[str, Any]
    source: str = "USER"
    propose: bool = True
    time_limit_s: float | None = Field(None, gt=0, le=300)


class SimulateRequest(Model):
    scenario_id: str
    seed: int
    rate: float = Field(0.5, gt=0, le=20)  # disruptions per hour over the window
    count: int | None = Field(None, ge=1, le=50)  # overrides rate
    from_min: int | None = Field(None, ge=0, le=100_000)
    to_min: int | None = Field(None, ge=0, le=100_000)
    propose: bool = False  # propose once, for the last event
    time_limit_s: float | None = Field(None, gt=0, le=300)


class EventResponse(BaseModel):
    events: list[Event]
    state_version: int
    active_plan_id: str | None
    affected_assignments: list[str]
    proposals: list[StoredProposal]
    note: str
    data_label: str


def _make(
    serial: int, type_: EventType, time_min: int, payload: dict[str, Any],
    origin: EventOrigin, source: str, t0: datetime,
) -> Event:
    seen = t0 + timedelta(minutes=time_min)
    try:
        return Event(
            id=f"EV-{serial:03d}", type=type_, time_min=time_min, payload=payload, source=source,
            created_by=origin,
            provenance=Provenance(source=source, observed_at=seen, ingested_at=seen,
                                  confidence=1.0, data_label="synthetic"),
        )
    except ValidationError as exc:
        err = exc.errors()[0]
        raise ApiError(422, "invalid_event", str(err["msg"])) from exc


def inject(
    session: Session, request: Request, scenario_id: str,
    specs: list[tuple[EventType, int, dict[str, Any]]], origin: EventOrigin, source: str,
) -> list[Event]:
    """Validate every event against the evolving state first, then store them all."""
    current = service.current_scenario(session, scenario_id)
    if current is None:
        raise ApiError(404, "not_found", f"unknown scenario: {scenario_id}")
    serial = len(service.live_events(session, scenario_id))
    out: list[Event] = []
    for type_, time_min, payload in specs:
        serial += 1
        event = _make(serial, type_, time_min, payload, origin, source, current.scenario.t0)
        try:
            validate_event(current, event)
            current = apply_event(current, event)
        except EventError as exc:
            raise ApiError(422, "invalid_event", str(exc)) from exc
        out.append(event)
    hub = request.app.state.hub
    for event in out:
        service.add_event(session, scenario_id, event)
        audit.append(
            session, scenario_id, actor=source, action="event.inject", object_type="event",
            object_id=event.id,
            details={"type": event.type.value, "time_min": event.time_min,
                     "description": describe_event(event), "origin": origin.value},
        )
    session.commit()
    for event in out:
        hub.publish(scenario_id, "event.created", {
            "event_id": event.id, "type": event.type.value, "time_min": event.time_min,
            "description": describe_event(event)})
    hub.publish(scenario_id, "state.updated", {
        "state_version": len(service.live_events(session, scenario_id)),
        "reason": "events", "event_ids": [e.id for e in out]})
    return out


def run_retask(
    session: Session, request: Request, scenario_id: str, event: Event, time_limit_s: float | None
) -> tuple[str | None, list[str], list[StoredProposal]]:
    """Propose alternatives to the active plan for the (already stored) `event`."""
    active = active_plan(session, scenario_id)
    if active is None:
        return None, [], []
    _, parent, inputs = active
    settings = request.app.state.settings
    hub = request.app.state.hub
    scenario, meta = _scenario_for(session, scenario_id, inputs)
    ctx = PlanningContext(scenario, fusion_meta=meta, now_min=event.time_min)
    drafts, affected = propose(
        ctx, scenario_id, parent, event,
        RetaskParams(time_budget_s=time_limit_s or settings.solver_time_limit_s,
                     num_workers=settings.solver_workers),
        meta,
    )
    expire_open(session, hub, scenario_id, parent.id)  # older proposals are about an older state
    n = len(proposals_of(session, scenario_id))
    stored: list[StoredProposal] = []
    for rank, d in enumerate(drafts, start=1):
        n += 1
        prop = StoredProposal(
            **Proposal(
                id=f"pr_{scenario_id[3:]}_{n}", event_id=event.id, base_plan_id=parent.id,
                rank=rank, fallback=d.fallback, plan=d.plan, diff=d.diff,
                score_breakdown=d.score_breakdown, explanation=d.explanation,
                status=ProposalStatus.OPEN,
            ).model_dump(by_alias=True),
            scenario_id=scenario_id, event_description=describe_event(event), preset=d.preset,
            affected_assignment_ids=sorted(affected.ids), base_inputs=inputs,
        )
        save_proposal(session, scenario_id, prop)
        stored.append(prop)
    audit.append(
        session, scenario_id, actor="system", action="retask.propose", object_type="event",
        object_id=event.id,
        details={"base_plan_id": parent.id, "n_proposals": len(stored),
                 "affected": sorted(affected.ids),
                 "fallback": [p.id for p in stored if p.fallback]},
    )
    session.commit()
    for p in stored:
        hub.publish(scenario_id, "proposal.created", {
            "proposal_id": p.id, "event_id": event.id, "rank": p.rank, "preset": p.preset,
            "fallback": p.fallback, "n_changes": p.diff.n_changes})
    if affected.ids:
        hub.publish(scenario_id, "alert.created", {
            "event_id": event.id, "message": describe_event(event),
            "affected_assignments": sorted(affected.ids), "n_proposals": len(stored)})
    return parent.id, sorted(affected.ids), stored


def _response(
    session: Session, scenario_id: str, events: list[Event], active_id: str | None,
    affected: list[str], proposals: list[StoredProposal], request: Request, proposed: bool,
) -> EventResponse:
    scenario = service.current_scenario(session, scenario_id)
    assert scenario is not None
    if active_id is None:
        note = "stored and applied; there is no active plan, so no proposals were made"
    elif not proposed:
        note = "stored and applied; proposals were not requested"
    else:
        note = f"{len(proposals)} proposal(s) for the active plan; nothing has been applied to it"
    return EventResponse(
        events=events, state_version=len(service.live_events(session, scenario_id)),
        active_plan_id=active_id, affected_assignments=affected, proposals=proposals, note=note,
        data_label=scenario.scenario.data_label,
    )


@router.post("", response_model=EventResponse)
def create_event(
    body: EventRequest, request: Request, session: Session = Depends(get_session)
) -> EventResponse:
    (event,) = inject(session, request, body.scenario_id,
                      [(body.type, body.time_min, body.payload)], EventOrigin.USER, body.source)
    active_id: str | None = None
    affected: list[str] = []
    proposals: list[StoredProposal] = []
    if body.propose:
        active_id, affected, proposals = run_retask(
            session, request, body.scenario_id, event, body.time_limit_s)
    else:
        active = active_plan(session, body.scenario_id)
        active_id = active[1].id if active else None
    return _response(session, body.scenario_id, [event], active_id, affected, proposals,
                     request, body.propose)


@router.post("/simulate", response_model=EventResponse)
def simulate(
    body: SimulateRequest, request: Request, session: Session = Depends(get_session)
) -> EventResponse:
    """Generate seeded disruptions against the current state and inject them in time order."""
    current = service.current_scenario(session, body.scenario_id)
    if current is None:
        raise ApiError(404, "not_found", f"unknown scenario: {body.scenario_id}")
    horizon = current.scenario.horizon_min
    start = body.from_min if body.from_min is not None else 0
    end = body.to_min if body.to_min is not None else horizon - 1
    if end < start:
        raise ApiError(422, "invalid_window", "to_min must not be before from_min")
    count = body.count or max(1, math.ceil(body.rate * (end - start) / 60))
    serial = len(service.live_events(session, body.scenario_id))
    raw = simulate_events(current, body.seed, min(count, 50), start, end, serial)
    specs = [(ty, t, p) for t, ty, p in raw]
    events = inject(session, request, body.scenario_id, specs, EventOrigin.SIM, "SIM")
    active_id: str | None = None
    affected: list[str] = []
    proposals: list[StoredProposal] = []
    if body.propose:
        active_id, affected, proposals = run_retask(
            session, request, body.scenario_id, events[-1], body.time_limit_s)
    else:
        active = active_plan(session, body.scenario_id)
        active_id = active[1].id if active else None
    return _response(session, body.scenario_id, events, active_id, affected, proposals,
                     request, body.propose)


@router.get("", response_model=list[Event])
def history(
    scenario_id: str, limit: int = Query(200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[Event]:
    if service.current_scenario(session, scenario_id) is None:
        raise ApiError(404, "not_found", f"unknown scenario: {scenario_id}")
    return service.live_events(session, scenario_id)[-limit:]

