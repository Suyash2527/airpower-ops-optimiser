"""Client-held state cache (D-72): two app instances with separate databases stand in for two
serverless instances; the browser's signed bundle carries plans and retasking between them."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

API = "/api/v1"
SMALL = {"seed": 3, "n_aircraft": 20, "n_crew": 30, "n_missions": 14, "n_bases": 3}


class Browser:
    """What frontend/lib/api.ts does: send the sync headers, keep the newest bundle, restore on
    409 state_out_of_sync and retry once."""

    def __init__(self) -> None:
        self.sid: str | None = None
        self.bundle: dict | None = None

    def call(self, server: TestClient, method: str, path: str, **kw):
        headers = {"X-AirPower-Sync": "1"}
        if self.sid:
            headers["X-AirPower-Scenario"] = self.sid
        if self.bundle and self.bundle["scenario_id"] == self.sid:
            headers["X-AirPower-Rev"] = self.bundle["rev"]
        r = server.request(method, f"{API}{path}", headers=headers, **kw)
        if r.status_code == 409 and r.json()["error"]["code"] == "state_out_of_sync":
            restored = server.post(f"{API}/sync/restore", json=self.bundle)
            assert restored.status_code == 200, restored.text
            r = server.request(method, f"{API}{path}", headers=headers, **kw)
        if r.headers.get("x-airpower-envelope") == "1":
            body = r.json()
            self.bundle = body["state"]
            return r.status_code, body["data"]
        return r.status_code, r.json()


def _server(tmp: Path) -> TestClient:
    return TestClient(create_app(Settings(database_url="sqlite://", scenario_dir=tmp,
                                          solver_time_limit_s=1.0, solver_workers=1)))


@pytest.fixture
def servers(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient]]:
    with _server(tmp_path) as a, _server(tmp_path) as b:
        yield a, b


def test_plan_and_retasking_survive_a_switch_to_a_fresh_instance(servers) -> None:
    a, b = servers
    web = Browser()
    status, summary = web.call(a, "POST", "/scenarios/generate", json=SMALL)
    assert status == 200 and web.bundle and web.bundle["scenario_id"] == summary["scenario_id"]
    web.sid = summary["scenario_id"]
    _, plan = web.call(a, "POST", "/plans/generate",
                       json={"scenario_id": web.sid, "planner": "greedy"})
    status, _ = web.call(a, "POST", f"/plans/{plan['id']}/approve", json={"actor": "ops"})
    assert status == 200

    # Instance b has never seen the scenario: the timeline still finds the approved plan.
    status, plans = web.call(b, "GET", f"/plans?scenario_id={web.sid}")
    assert status == 200 and [p["status"] for p in plans] == ["approved"]

    victim = next(x for x in plan["assignments"] if x["takeoff_min"] > 100)
    status, event = web.call(b, "POST", "/events", json={
        "scenario_id": web.sid, "type": "AIRCRAFT_UNSERVICEABLE", "time_min": 100,
        "payload": {"aircraft_id": victim["aircraft_id"], "until_min": None}, "time_limit_s": 4})
    assert status == 200 and event["proposals"], event

    # Back on instance a (now stale): approving the proposal restores first, then works.
    status, approved = web.call(a, "POST", f"/proposals/{event['proposals'][0]['id']}/approve",
                                json={"actor": "ops"})
    assert status == 200, approved
    status, audit = web.call(b, "GET", f"/audit?scenario_id={web.sid}")
    assert "proposal.approve" in [e["action"] for e in audit]


def _as_javascript_would(obj):
    """JSON.stringify drops the fraction of whole floats (1.0 -> 1)."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _as_javascript_would(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_as_javascript_would(v) for v in obj]
    return obj


def test_bundle_round_tripped_through_javascript_still_restores(servers) -> None:
    a, b = servers
    web = Browser()
    _, summary = web.call(a, "POST", "/scenarios/generate", json=SMALL)
    web.sid = summary["scenario_id"]
    web.call(a, "POST", "/plans/generate", json={"scenario_id": web.sid, "planner": "greedy"})
    r = b.post(f"{API}/sync/restore", json=_as_javascript_would(web.bundle))
    assert r.status_code == 200, r.text


def test_tampered_bundle_is_refused(servers) -> None:
    a, b = servers
    web = Browser()
    _, summary = web.call(a, "POST", "/scenarios/generate", json=SMALL)
    web.sid = summary["scenario_id"]
    web.call(a, "POST", "/plans/generate", json={"scenario_id": web.sid, "planner": "greedy"})
    forged = {**web.bundle}
    forged["rows"]["plan"][0]["data"]["plan"]["status"] = "approved"
    r = b.post(f"{API}/sync/restore", json=forged)
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_state_signature"


def test_clients_without_sync_headers_see_the_plain_api(servers) -> None:
    a, _ = servers
    r = a.post(f"{API}/scenarios/generate", json=SMALL)
    assert "x-airpower-envelope" not in r.headers and "scenario_id" in r.json()
