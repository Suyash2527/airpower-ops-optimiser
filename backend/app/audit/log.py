"""Append-only audit log (DATA_MODEL AuditEntry). There is deliberately no update or delete.

Phase 2 uses it for conflict pins; Phase 5 adds plan approvals, proposals and events on top.
"""

from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime
from sqlmodel import Session, func, select

from app.core.clock import utcnow
from app.models import tables
from app.models.entities import Model


class AuditEntry(Model):
    id: str
    ts: AwareDatetime
    actor: str
    action: str
    object_type: str
    object_id: str
    details: dict[str, Any]


def append(
    session: Session,
    scenario_id: str,
    *,
    actor: str,
    action: str,
    object_type: str,
    object_id: str,
    details: dict[str, Any],
) -> AuditEntry:
    """Add one entry in the caller's transaction (the caller commits)."""
    count = session.exec(
        select(func.count()).select_from(tables.AuditEntryRow).where(
            tables.AuditEntryRow.scenario_id == scenario_id
        )
    ).one()
    entry = AuditEntry(
        id=f"au_{count + 1:05d}", ts=utcnow(), actor=actor, action=action,
        object_type=object_type, object_id=object_id, details=details,
    )
    session.add(
        tables.AuditEntryRow(
            scenario_id=scenario_id, entity_id=object_id, data=entry.model_dump(mode="json")
        )
    )
    session.flush()
    return entry


def list_entries(
    session: Session, scenario_id: str | None, object_id: str | None = None, limit: int = 100
) -> list[AuditEntry]:
    """Oldest first. `scenario_id=None` lists every scenario."""
    query = select(tables.AuditEntryRow)
    if scenario_id is not None:
        query = query.where(tables.AuditEntryRow.scenario_id == scenario_id)
    if object_id is not None:
        query = query.where(tables.AuditEntryRow.entity_id == object_id)
    rows = session.exec(query.order_by(tables.AuditEntryRow.pk).limit(limit)).all()  # type: ignore[arg-type]
    return [AuditEntry.model_validate(r.data) for r in rows]
