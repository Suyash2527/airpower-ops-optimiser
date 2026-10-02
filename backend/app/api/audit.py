"""GET /audit (API_SPEC "KPIs, benchmarks, audit"): the append-only log, oldest first."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.audit import log as audit
from app.core.db import get_session

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[audit.AuditEntry])
def get_audit(
    scenario_id: str | None = None,
    object_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[audit.AuditEntry]:
    return audit.list_entries(session, scenario_id, object_id=object_id, limit=limit)
