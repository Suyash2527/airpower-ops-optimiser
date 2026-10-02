"""Fusion endpoints (API_SPEC "Scenarios & state"): fusion report and human pins."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ValidationError, model_validator
from sqlmodel import Session

from app.audit import log as audit
from app.core.clock import utcnow
from app.core.db import get_session
from app.core.errors import ApiError
from app.ingest import service
from app.ingest.models import Conflict, FusionReport, Pin
from app.models.entities import Model

router = APIRouter(prefix="/scenarios", tags=["fusion"])

NowMin = Annotated[int, Query(ge=0, le=100_000, description="fusion time, minutes from t0")]
Secondary = Annotated[bool, Query(description="include the noisy secondary synthetic source")]


class PinRequest(Model):
    """Pin a field to the value one source reported (`source`) or to an explicit `value`."""

    actor: str
    reason: str | None = None
    source: str | None = None
    value: Any = None

    @model_validator(mode="after")
    def _exactly_one_choice(self) -> PinRequest:
        has_value = "value" in self.model_fields_set
        if (self.source is None) == (not has_value):
            raise ValueError("give exactly one of `source` or `value`")
        if not self.actor.strip():
            raise ValueError("actor must not be empty")
        return self


class PinResponse(BaseModel):
    conflict: Conflict
    state_version: int
    data_label: str


def _unknown(scenario_id: str) -> ApiError:
    return ApiError(404, "not_found", f"unknown scenario: {scenario_id}")


@router.get("/{scenario_id}/fusion-report", response_model=FusionReport)
def fusion_report(
    scenario_id: str,
    now_min: NowMin = 0,
    secondary: Secondary = True,
    session: Session = Depends(get_session),
) -> FusionReport:
    fused = service.fused_snapshot(session, scenario_id, now_min=now_min, secondary=secondary)
    if fused is None:
        raise _unknown(scenario_id)
    return fused.report


@router.post("/{scenario_id}/conflicts/{conflict_id}/pin", response_model=PinResponse)
def pin_conflict(
    scenario_id: str,
    conflict_id: str,
    body: PinRequest,
    now_min: NowMin = 0,
    secondary: Secondary = True,
    session: Session = Depends(get_session),
) -> PinResponse:
    before = service.fused_snapshot(session, scenario_id, now_min=now_min, secondary=secondary)
    if before is None:
        raise _unknown(scenario_id)
    conflict = next((c for c in before.report.conflicts if c.id == conflict_id), None)
    if conflict is None:
        raise ApiError(404, "not_found", f"no conflict {conflict_id} at now_min={now_min}")

    chosen = body.source
    if chosen is not None:
        match = next((c for c in conflict.candidates if c.source == chosen), None)
        if match is None:
            sources = ", ".join(c.source for c in conflict.candidates)
            raise ApiError(422, "unknown_source", f"{chosen!r} did not report it ({sources})")
        value = match.value
    else:
        value = body.value
    pin = Pin(
        conflict_id=conflict_id, group=conflict.group, entity_id=conflict.entity_id,
        field=conflict.field, value=value, actor=body.actor.strip(), reason=body.reason,
        chosen_source=chosen, ts=utcnow(),
    )
    try:  # dry run: the pinned value must still make a valid record
        after = service.fused_snapshot(
            session, scenario_id, now_min=now_min, secondary=secondary, extra_pins=(pin,)
        )
    except ValidationError as exc:
        err = exc.errors()[0]
        raise ApiError(422, "invalid_pin_value", f"{conflict.field}: {err['msg']}") from exc
    assert after is not None

    service.add_pin(session, scenario_id, pin)
    audit.append(
        session, scenario_id, actor=pin.actor, action="fusion.pin", object_type="conflict",
        object_id=conflict_id,
        details={
            "group": pin.group, "entity_id": pin.entity_id, "field": pin.field,
            "from_value": conflict.resolved_value, "from_source": conflict.resolved_source,
            "to_value": value, "chosen_source": chosen, "reason": pin.reason,
            "now_min": now_min,
        },
    )
    session.commit()
    pinned = next((c for c in after.report.conflicts if c.id == conflict_id), None)
    if pinned is None:  # pinned to a value every source agrees with: still report the decision
        pinned = conflict.model_copy(
            update={"status": "pinned", "pin": pin, "resolved_value": value}
        )
    return PinResponse(
        conflict=pinned, state_version=after.state_version + 1,
        data_label=after.report.data_label,
    )
