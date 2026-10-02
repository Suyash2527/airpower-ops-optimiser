"""Storage helpers shared by the plan, event and proposal endpoints: the active plan of a scenario,
storing plans and proposals, and expiring proposals whose base plan is no longer active."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.errors import ApiError
from app.core.hub import Hub
from app.models import tables
from app.models.enums import PlanStatus, ProposalStatus
from app.models.plans import Plan, Proposal


class PlanInputs(BaseModel):
    """Everything needed to rebuild the snapshot a plan was made from."""

    planner: str
    time_limit_s: float | None
    weight_preset: str
    fused: bool
    secondary: bool
    now_min: int
    seed: int


class StoredProposal(Proposal):
    scenario_id: str
    event_description: str
    preset: str
    affected_assignment_ids: list[str]
    base_inputs: PlanInputs


# ------------------------------------------------------------------------------------- plans
def load_plan(session: Session, plan_id: str) -> tuple[tables.PlanRow, Plan, PlanInputs]:
    row = session.exec(
        select(tables.PlanRow).where(tables.PlanRow.entity_id == plan_id)
    ).first()
    if row is None:
        raise ApiError(404, "not_found", f"unknown plan: {plan_id}")
    return row, Plan.model_validate(row.data["plan"]), PlanInputs.model_validate(row.data["inputs"])


def active_plan(
    session: Session, scenario_id: str
) -> tuple[tables.PlanRow, Plan, PlanInputs] | None:
    rows = session.exec(
        select(tables.PlanRow).where(tables.PlanRow.scenario_id == scenario_id)
        .order_by(tables.PlanRow.pk.desc())  # type: ignore[attr-defined]
    ).all()
    for row in rows:
        if row.data["plan"]["status"] == PlanStatus.APPROVED.value:
            return row, Plan.model_validate(row.data["plan"]), PlanInputs.model_validate(
                row.data["inputs"])
    return None


def set_plan_status(session: Session, row: tables.PlanRow, status: PlanStatus) -> None:
    row.data = {**row.data, "plan": {**row.data["plan"], "status": status.value}}
    session.add(row)


def store_plan(session: Session, scenario_id: str, plan: Plan, inputs: PlanInputs) -> Plan:
    n = len(session.exec(
        select(tables.PlanRow).where(tables.PlanRow.scenario_id == scenario_id)
    ).all()) + 1
    plan = plan.model_copy(update={"id": f"p_{scenario_id[3:]}_{n}", "version": n})
    session.add(tables.PlanRow(
        scenario_id=scenario_id, entity_id=plan.id,
        data={"plan": plan.model_dump(mode="json", by_alias=True),
              "inputs": inputs.model_dump(mode="json")},
    ))
    return plan


# -------------------------------------------------------------------------------- proposals
def load_proposal(session: Session, proposal_id: str) -> tuple[tables.ProposalRow, StoredProposal]:
    row = session.exec(
        select(tables.ProposalRow).where(tables.ProposalRow.entity_id == proposal_id)
    ).first()
    if row is None:
        raise ApiError(404, "not_found", f"unknown proposal: {proposal_id}")
    return row, StoredProposal.model_validate(row.data)


def save_proposal(session: Session, scenario_id: str, proposal: StoredProposal) -> None:
    session.add(tables.ProposalRow(
        scenario_id=scenario_id, entity_id=proposal.id,
        data=proposal.model_dump(mode="json", by_alias=True),
    ))


def set_proposal_status(
    session: Session, row: tables.ProposalRow, status: ProposalStatus
) -> dict[str, Any]:
    row.data = {**row.data, "status": status.value}
    session.add(row)
    return row.data


def proposals_of(
    session: Session, scenario_id: str
) -> list[tuple[tables.ProposalRow, StoredProposal]]:
    rows = session.exec(
        select(tables.ProposalRow).where(tables.ProposalRow.scenario_id == scenario_id)
        .order_by(tables.ProposalRow.pk)  # type: ignore[arg-type]
    ).all()
    return [(r, StoredProposal.model_validate(r.data)) for r in rows]


def expire_open(
    session: Session, hub: Hub, scenario_id: str, base_plan_id: str, except_id: str | None = None
) -> list[str]:
    """Open proposals that were made against `base_plan_id` can no longer be applied."""
    expired = []
    for row, prop in proposals_of(session, scenario_id):
        if prop.base_plan_id == base_plan_id and prop.status is ProposalStatus.OPEN and (
            prop.id != except_id
        ):
            set_proposal_status(session, row, ProposalStatus.EXPIRED)
            expired.append(prop.id)
            hub.publish(scenario_id, "proposal.updated", {"proposal_id": prop.id,
                                                          "status": "expired"})
    return expired
