"""Proposal endpoints: list, fetch, approve (creates a new plan version, audited) and reject.
A proposal is the only way retasking changes the active plan, and only a human call does it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlmodel import Session

from app.api.state import (
    StoredProposal,
    active_plan,
    expire_open,
    load_proposal,
    proposals_of,
    set_plan_status,
    set_proposal_status,
    store_plan,
)
from app.audit import log as audit
from app.core.db import get_session
from app.core.errors import ApiError
from app.ingest import service
from app.models.entities import Model
from app.models.enums import PlanStatus, ProposalStatus
from app.models.plans import Plan

router = APIRouter(prefix="/proposals", tags=["proposals"])


class DecisionRequest(Model):
    actor: str
    reason: str | None = None


class ApproveResponse(BaseModel):
    proposal: StoredProposal
    plan: Plan
    superseded_plan_id: str
    expired_proposals: list[str]


def _actor(body: DecisionRequest) -> str:
    if not body.actor.strip():
        raise ApiError(422, "validation_error", "actor must not be empty")
    return body.actor.strip()


@router.get("", response_model=list[StoredProposal])
def list_proposals(
    scenario_id: str, status: ProposalStatus | None = Query(None),
    session: Session = Depends(get_session),
) -> list[StoredProposal]:
    if service.current_scenario(session, scenario_id) is None:
        raise ApiError(404, "not_found", f"unknown scenario: {scenario_id}")
    return [p for _, p in proposals_of(session, scenario_id)
            if status is None or p.status is status]


@router.get("/{proposal_id}", response_model=StoredProposal)
def get_proposal(proposal_id: str, session: Session = Depends(get_session)) -> StoredProposal:
    return load_proposal(session, proposal_id)[1]


@router.post("/{proposal_id}/approve", response_model=ApproveResponse)
def approve(
    proposal_id: str, body: DecisionRequest, request: Request,
    session: Session = Depends(get_session),
) -> ApproveResponse:
    actor = _actor(body)
    row, prop = load_proposal(session, proposal_id)
    if prop.status is not ProposalStatus.OPEN:
        raise ApiError(409, "not_open", f"{proposal_id} is {prop.status.value}")
    hub = request.app.state.hub
    sid = prop.scenario_id
    current = active_plan(session, sid)
    if current is None or current[1].id != prop.base_plan_id:
        set_proposal_status(session, row, ProposalStatus.EXPIRED)
        session.commit()
        raise ApiError(409, "stale_proposal",
                       f"{proposal_id} was made for plan {prop.base_plan_id}, which is no longer "
                       f"the active plan")
    base_row, base_plan, _ = current

    new_plan = store_plan(
        session, sid,
        prop.plan.model_copy(update={"status": PlanStatus.APPROVED,
                                     "parent_plan_id": base_plan.id}),
        prop.base_inputs,
    )
    set_plan_status(session, base_row, PlanStatus.SUPERSEDED)
    set_proposal_status(session, row, ProposalStatus.APPROVED)
    expired = expire_open(session, hub, sid, base_plan.id, except_id=proposal_id)
    audit.append(
        session, sid, actor=actor, action="proposal.approve", object_type="proposal",
        object_id=proposal_id,
        details={"event_id": prop.event_id, "new_plan_id": new_plan.id,
                 "base_plan_id": base_plan.id, "n_changes": prop.diff.n_changes,
                 "preset": prop.preset, "fallback": prop.fallback, "reason": body.reason,
                 "expired": expired},
    )
    audit.append(
        session, sid, actor=actor, action="plan.supersede", object_type="plan",
        object_id=base_plan.id, details={"replaced_by": new_plan.id, "via": proposal_id},
    )
    session.commit()
    hub.publish(sid, "plan.approved", {"plan_id": new_plan.id, "version": new_plan.version,
                                       "via_proposal": proposal_id})
    hub.publish(sid, "proposal.updated", {"proposal_id": proposal_id, "status": "approved"})
    approved = prop.model_copy(update={"status": ProposalStatus.APPROVED})
    return ApproveResponse(proposal=approved, plan=new_plan, superseded_plan_id=base_plan.id,
                           expired_proposals=expired)


@router.post("/{proposal_id}/reject", response_model=StoredProposal)
def reject(
    proposal_id: str, body: DecisionRequest, request: Request,
    session: Session = Depends(get_session),
) -> StoredProposal:
    actor = _actor(body)
    row, prop = load_proposal(session, proposal_id)
    if prop.status is not ProposalStatus.OPEN:
        raise ApiError(409, "not_open", f"{proposal_id} is {prop.status.value}")
    set_proposal_status(session, row, ProposalStatus.REJECTED)
    audit.append(
        session, prop.scenario_id, actor=actor, action="proposal.reject",
        object_type="proposal", object_id=proposal_id,
        details={"event_id": prop.event_id, "reason": body.reason, "preset": prop.preset},
    )
    session.commit()
    request.app.state.hub.publish(prop.scenario_id, "proposal.updated",
                                  {"proposal_id": proposal_id, "status": "rejected"})
    return prop.model_copy(update={"status": ProposalStatus.REJECTED})
