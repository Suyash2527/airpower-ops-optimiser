"""Client-held state cache for serverless deployments without a shared database (D-72).

Each serverless instance has its own temporary SQLite, so a plan stored by one request is unknown
to the next. The browser therefore keeps a signed copy of a scenario's mutable state (plans,
proposals, live events, pins, audit) and the server checks it on every request:

* a client that sends `X-AirPower-Sync: 1` gets every successful write wrapped as
  `{"data": <normal body>, "state": <bundle>}` (header `X-AirPower-Envelope: 1`);
* a client that also sends `X-AirPower-Scenario` + `X-AirPower-Rev` gets `409 state_out_of_sync`
  when this instance's state differs; it then posts its bundle to `/sync/restore` and retries.

With a shared database the revisions always match, so nothing is ever restored. Clients that do
not send the headers (tests, scripts) see the API unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from app.core.db import get_session
from app.core.errors import ApiError
from app.models import store, tables
from app.models.scenario import GeneratorParams

router = APIRouter(prefix="/sync", tags=["sync"])

# Mutable per-scenario tables, restored in this order. The scenario itself is rebuilt from its
# generator params (deterministic, D-69), so the bundle stays small.
_MUTABLE: dict[str, type[tables.EntityRow]] = {
    "plan": tables.PlanRow,
    "proposal": tables.ProposalRow,
    "live_event": tables.LiveEventRow,
    "fusion_pin": tables.FusionPinRow,
    "audit_entry": tables.AuditEntryRow,
}
# Writes whose response names the scenario they created (the request header names the old one).
_CREATES_SCENARIO = ("/scenarios/generate", "/scenarios/load")


def _secret() -> bytes:
    # Tamper evidence only (a restored plan skips the validator, so it must be one we issued).
    # Every instance of a deployment must share the value; set AIRPOWER_STATE_SECRET in production.
    return os.environ.get("AIRPOWER_STATE_SECRET", "airpower-dev-state-secret").encode()


def _js_numbers(obj: Any) -> Any:
    """The bundle comes back through JSON.stringify, which writes 1.0 as 1: hash both alike."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _js_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_js_numbers(v) for v in obj]
    return obj


def _canonical(obj: Any) -> bytes:
    return json.dumps(_js_numbers(obj), sort_keys=True, separators=(",", ":"), default=str).encode()


def _rows(session: Session, scenario_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for name, cls in _MUTABLE.items():
        rows = session.exec(
            select(cls).where(cls.scenario_id == scenario_id).order_by(cls.pk)  # type: ignore[arg-type]
        ).all()
        out[name] = [{"entity_id": r.entity_id, "data": r.data} for r in rows]
    return out


def revision(rows: dict[str, list[dict[str, Any]]]) -> str:
    return hashlib.sha256(_canonical(rows)).hexdigest()[:20]


def local_revision(session: Session, scenario_id: str) -> str | None:
    """None when this instance does not hold the scenario at all."""
    if session.get(tables.ScenarioRow, scenario_id) is None:
        return None
    return revision(_rows(session, scenario_id))


class StateBundle(BaseModel):
    scenario_id: str
    params: dict[str, Any] | None
    rows: dict[str, list[dict[str, Any]]]
    rev: str
    sig: str


def _sign(scenario_id: str, params: Any, rows: Any, rev: str) -> str:
    msg = _canonical({"scenario_id": scenario_id, "params": params, "rows": rows, "rev": rev})
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def export_state(session: Session, scenario_id: str) -> StateBundle | None:
    head = session.get(tables.ScenarioRow, scenario_id)
    if head is None:
        return None
    rows = _rows(session, scenario_id)
    rev = revision(rows)
    params = head.meta.get("params")
    return StateBundle(scenario_id=scenario_id, params=params, rows=rows, rev=rev,
                       sig=_sign(scenario_id, params, rows, rev))


def _ensure_scenario(session: Session, bundle: StateBundle) -> None:
    if store.load_scenario_rows(session, bundle.scenario_id) is not None:  # also rebuilds presets
        return
    if not bundle.params:
        raise ApiError(409, "cannot_restore", "scenario has no generator params to rebuild from")
    from app.sim.generate import generate_scenario

    rebuilt = generate_scenario(GeneratorParams.model_validate(bundle.params))
    if store.scenario_id_for(rebuilt) != bundle.scenario_id:
        raise ApiError(409, "cannot_restore", "rebuilt scenario does not match its id")
    store.save_scenario_rows(session, rebuilt)


def restore_state(session: Session, bundle: StateBundle) -> str:
    good = _sign(bundle.scenario_id, bundle.params, bundle.rows, bundle.rev)
    if not hmac.compare_digest(good, bundle.sig) or revision(bundle.rows) != bundle.rev:
        raise ApiError(403, "bad_state_signature", "state bundle was not issued by this server")
    if set(bundle.rows) != set(_MUTABLE):
        raise ApiError(422, "validation_error", "state bundle has unexpected tables")
    _ensure_scenario(session, bundle)
    sid = bundle.scenario_id
    for name, cls in _MUTABLE.items():
        session.exec(delete(cls).where(cls.scenario_id == sid))  # type: ignore[arg-type]
        for r in bundle.rows[name]:
            session.add(cls(scenario_id=sid, entity_id=r["entity_id"], data=r["data"]))
    session.commit()
    return bundle.rev


class RestoreResponse(BaseModel):
    scenario_id: str
    rev: str


@router.post("/restore", response_model=RestoreResponse)
def restore(bundle: StateBundle, session: Session = Depends(get_session)) -> RestoreResponse:
    """Replace this instance's mutable state for one scenario with a bundle it issued earlier."""
    return RestoreResponse(scenario_id=bundle.scenario_id, rev=restore_state(session, bundle))


# ------------------------------------------------------------------------------- middleware
def install_sync_middleware(app: FastAPI, api_prefix: str) -> None:
    engine = app.state.engine

    def _local_rev(sid: str) -> str | None:
        with Session(engine) as session:
            return local_revision(session, sid)

    def _export(sid: str) -> dict[str, Any] | None:
        with Session(engine) as session:
            bundle = export_state(session, sid)
        return bundle.model_dump() if bundle else None

    @app.middleware("http")
    async def state_sync(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path.removeprefix(api_prefix)
        if request.headers.get("x-airpower-sync") != "1" or path.startswith("/sync"):
            return await call_next(request)

        sid = request.headers.get("x-airpower-scenario")
        client_rev = request.headers.get("x-airpower-rev")
        if sid and client_rev and await run_in_threadpool(_local_rev, sid) != client_rev:
            return JSONResponse({"error": {
                "code": "state_out_of_sync",
                "message": "this server instance does not hold your latest state; restore it",
            }}, status_code=409)

        response = await call_next(request)
        if request.method == "GET" or not 200 <= response.status_code < 300:
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
        plain = Response(body, status_code=response.status_code,
                         headers=dict(response.headers), media_type=response.media_type)
        try:
            data = json.loads(body)
        except ValueError:
            return plain
        if path in _CREATES_SCENARIO and isinstance(data, dict):
            sid = data.get("scenario_id") or sid
        state = await run_in_threadpool(_export, sid) if sid else None
        if state is None:
            return plain
        return JSONResponse({"data": data, "state": state}, status_code=response.status_code,
                            headers={"X-AirPower-Envelope": "1"})
