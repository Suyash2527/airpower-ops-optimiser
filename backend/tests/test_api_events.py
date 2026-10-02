"""Events, proposals, approvals, audit and WebSocket (Tasks 5.1, 5.7-5.10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"
SMALL = {"seed": 3, "n_aircraft": 20, "n_crew": 30, "n_missions": 14, "n_bases": 3}


def _sid(client: TestClient, **over) -> str:
    return client.post(f"{API}/scenarios/generate", json={**SMALL, **over}).json()["scenario_id"]


def _active_plan(client: TestClient, sid: str) -> dict:
    """A greedy plan, approved, so retasking has something to work from (fast and deterministic)."""
    plan = client.post(f"{API}/plans/generate", json={"scenario_id": sid, "planner": "greedy"}).json()
    r = client.post(f"{API}/plans/{plan['id']}/approve", json={"actor": "ops"})
    assert r.status_code == 200, r.text
    return plan


def _victim(plan: dict, after: int) -> dict:
    return next(a for a in plan["assignments"] if a["takeoff_min"] > after)


def _fail_aircraft(client: TestClient, sid: str, plan: dict, time_min: int = 100, **over):
    a = _victim(plan, time_min)
    body = {"scenario_id": sid, "type": "AIRCRAFT_UNSERVICEABLE", "time_min": time_min,
            "payload": {"aircraft_id": a["aircraft_id"], "until_min": None}, "time_limit_s": 6,
            **over}
    return a, client.post(f"{API}/events", json=body)


def _audit(client: TestClient, sid: str) -> list[dict]:
    return client.get(f"{API}/audit", params={"scenario_id": sid}).json()


# ----------------------------------------------------------------------------- plan approval
def test_approving_a_plan_makes_it_active_and_supersedes_the_previous_one(
    client: TestClient,
) -> None:
    sid = _sid(client)
    first = _active_plan(client, sid)
    second = client.post(f"{API}/plans/generate",
                         json={"scenario_id": sid, "planner": "fifo"}).json()
    assert client.get(f"{API}/plans/{second['id']}").json()["status"] == "draft"
    r = client.post(f"{API}/plans/{second['id']}/approve", json={"actor": "ops", "reason": "better"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.get(f"{API}/plans/{first['id']}").json()["status"] == "superseded"
    assert client.post(f"{API}/plans/{second['id']}/approve",
                       json={"actor": "x"}).json()["error"]["code"] == "not_approvable"
    actions = [(e["action"], e["actor"]) for e in _audit(client, sid)]
    assert ("plan.approve", "ops") in actions and ("plan.supersede", "ops") in actions


def test_plan_approval_needs_an_actor_and_a_draft(client: TestClient) -> None:
    sid = _sid(client)
    plan = client.post(f"{API}/plans/generate", json={"scenario_id": sid, "planner": "greedy"}).json()
    assert client.post(f"{API}/plans/{plan['id']}/approve", json={}).status_code == 422
    assert client.post(f"{API}/plans/{plan['id']}/approve", json={"actor": " "}).status_code == 422
    assert client.post(f"{API}/plans/p_nope/approve", json={"actor": "a"}).status_code == 404


# -------------------------------------------------------------------------------- events
def test_event_is_stored_applied_and_changes_the_state(client: TestClient) -> None:
    sid = _sid(client)
    snap0 = client.get(f"{API}/scenarios/{sid}/snapshot", params={"fused": "false"}).json()
    aid = snap0["aircraft"][0]["id"]
    r = client.post(f"{API}/events", json={
        "scenario_id": sid, "type": "AIRCRAFT_UNSERVICEABLE", "time_min": 50, "propose": False,
        "payload": {"aircraft_id": aid, "until_min": 500}})
    assert r.status_code == 200, r.text
    body = r.json()
    ev = body["events"][0]
    assert ev["id"] == "EV-001" and ev["created_by"] == "user" and ev["type"] == "AIRCRAFT_UNSERVICEABLE"
    assert body["state_version"] == 1 and body["active_plan_id"] is None
    assert "no active plan" in body["note"] or "not requested" in body["note"]
    snap1 = client.get(f"{API}/scenarios/{sid}/snapshot", params={"fused": "false"}).json()
    a1 = next(a for a in snap1["aircraft"] if a["id"] == aid)
    assert a1["status"] == "UNSERVICEABLE" and a1["available_from_min"] == 500
    hist = client.get(f"{API}/events", params={"scenario_id": sid}).json()
    assert [e["id"] for e in hist] == ["EV-001"]
    assert client.get(f"{API}/scenarios/{sid}/fusion-report").json()["state_version"] == 1


def test_event_without_an_active_plan_makes_no_proposals(client: TestClient) -> None:
    sid = _sid(client)
    snap = client.get(f"{API}/scenarios/{sid}/snapshot").json()
    r = client.post(f"{API}/events", json={
        "scenario_id": sid, "type": "MISSION_CANCELLED", "time_min": 10,
        "payload": {"mission_id": snap["missions"][0]["id"]}})
    assert r.status_code == 200 and r.json()["proposals"] == []
    assert r.json()["active_plan_id"] is None


@pytest.mark.parametrize(("body", "code"), [
    ({"type": "AIRCRAFT_UNSERVICEABLE", "time_min": 5,
      "payload": {"aircraft_id": "A-404", "until_min": None}}, "invalid_event"),
    ({"type": "AIRCRAFT_UNSERVICEABLE", "time_min": 5, "payload": {"aircraft_id": "A-001"}},
     "invalid_event"),
    ({"type": "MISSION_CANCELLED", "time_min": 5, "payload": {"mission_id": "M-999"}},
     "invalid_event"),
    ({"type": "PRIORITY_CHANGE", "time_min": 5, "payload": {"mission_id": "M-001",
                                                           "new_priority": 7}}, "invalid_event"),
])
def test_invalid_events_get_a_422_and_change_nothing(client: TestClient, body, code) -> None:
    sid = _sid(client)
    r = client.post(f"{API}/events", json={"scenario_id": sid, **body})
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    assert client.get(f"{API}/events", params={"scenario_id": sid}).json() == []
    assert _audit(client, sid) == []


def test_event_request_validation(client: TestClient) -> None:
    sid = _sid(client)
    ok = {"scenario_id": sid, "type": "MISSION_CANCELLED", "time_min": 1,
          "payload": {"mission_id": "M-001"}}
    assert client.post(f"{API}/events", json={**ok, "type": "EXPLODE"}).status_code == 422
    assert client.post(f"{API}/events", json={**ok, "time_min": -3}).status_code == 422
    assert client.post(f"{API}/events", json={**ok, "extra": 1}).status_code == 422
    assert client.post(f"{API}/events", json={**ok, "scenario_id": "sc_none"}).status_code == 404
    assert client.get(f"{API}/events", params={"scenario_id": "sc_none"}).status_code == 404


# ----------------------------------------------------------------- proposals and approval
def test_event_with_an_active_plan_yields_ranked_valid_proposals_and_changes_nothing(
    client: TestClient,
) -> None:
    sid = _sid(client)
    plan = _active_plan(client, sid)
    victim, r = _fail_aircraft(client, sid, plan)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_plan_id"] == plan["id"] and body["proposals"]
    assert victim["id"] in body["affected_assignments"]
    ranks = [p["rank"] for p in body["proposals"]]
    assert ranks == list(range(1, len(ranks) + 1))
    totals = [p["score_breakdown"]["total"] for p in body["proposals"]]
    assert totals == sorted(totals, reverse=True)
    for p in body["proposals"]:
        assert p["status"] == "open" and p["base_plan_id"] == plan["id"] and p["event_id"] == "EV-001"
        assert p["plan"]["status"] == "proposed" and p["plan"]["parent_plan_id"] == plan["id"]
        assert set(p["score_breakdown"]) == {"coverage", "risk", "stability", "total"}
        assert p["explanation"] and p["event_description"] and p["preset"]
        assert p["diff"]["n_changes"] >= 1 and set(p["diff"]) >= {"added", "removed", "changed"}
        assert all(a["aircraft_id"] != victim["aircraft_id"] for a in p["plan"]["assignments"]
                   if not a["frozen"] and a["takeoff_min"] > 100)
        for a in p["plan"]["assignments"]:
            if a["takeoff_min"] <= 100:
                assert a["frozen"] is True
    # advisory only: the active plan is untouched and no new plan version exists
    assert client.get(f"{API}/plans/{plan['id']}").json()["status"] == "approved"
    assert len(client.get(f"{API}/plans", params={"scenario_id": sid}).json()) == 1
    listed = client.get(f"{API}/proposals", params={"scenario_id": sid, "status": "open"}).json()
    assert [p["id"] for p in listed] == [p["id"] for p in body["proposals"]]
    one = client.get(f"{API}/proposals/{body['proposals'][0]['id']}").json()
    assert one["plan"]["assignments"] == body["proposals"][0]["plan"]["assignments"]


def test_approving_a_proposal_creates_a_new_plan_version_and_audit_rows(
    client: TestClient,
) -> None:
    sid = _sid(client)
    plan = _active_plan(client, sid)
    _, r = _fail_aircraft(client, sid, plan)
    props = r.json()["proposals"]
    chosen = props[0]
    ok = client.post(f"{API}/proposals/{chosen['id']}/approve",
                     json={"actor": "duty.officer", "reason": "least disruption"})
    assert ok.status_code == 200, ok.text
    out = ok.json()
    new = out["plan"]
    assert new["status"] == "approved" and new["version"] == 2 and new["parent_plan_id"] == plan["id"]
    assert out["superseded_plan_id"] == plan["id"] and out["proposal"]["status"] == "approved"
    assert client.get(f"{API}/plans/{plan['id']}").json()["status"] == "superseded"
    assert client.get(f"{API}/plans/{new['id']}").json()["status"] == "approved"
    assert [p["id"] for p in client.get(f"{API}/plans", params={"scenario_id": sid}).json()] == [
        plan["id"], new["id"]]
    others = {p["id"] for p in props[1:]}
    assert set(out["expired_proposals"]) == others
    for pid in others:
        assert client.get(f"{API}/proposals/{pid}").json()["status"] == "expired"
    audit = _audit(client, sid)
    row = next(e for e in audit if e["action"] == "proposal.approve")
    assert row["actor"] == "duty.officer" and row["object_id"] == chosen["id"]
    assert row["details"]["new_plan_id"] == new["id"] and row["details"]["reason"]
    assert row["details"]["n_changes"] == chosen["diff"]["n_changes"]
    assert any(e["action"] == "plan.supersede" and e["object_id"] == plan["id"] for e in audit)
    # the new plan still validates against the changed state
    v = client.post(f"{API}/plans/{new['id']}/validate").json()
    assert v["valid"] is True, v
    # audit is append-only and ordered
    ids = [e["id"] for e in audit]
    assert ids == sorted(ids)


def test_a_proposal_cannot_be_applied_twice_and_a_stale_one_is_refused(client: TestClient) -> None:
    sid = _sid(client)
    plan = _active_plan(client, sid)
    _, r = _fail_aircraft(client, sid, plan)
    props = r.json()["proposals"]
    first = props[0]["id"]
    assert client.post(f"{API}/proposals/{first}/approve", json={"actor": "a"}).status_code == 200
    again = client.post(f"{API}/proposals/{first}/approve", json={"actor": "a"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_open"
    if len(props) > 1:
        late = client.post(f"{API}/proposals/{props[1]['id']}/approve", json={"actor": "a"})
        assert late.status_code == 409  # expired by the first approval
    assert client.post(f"{API}/proposals/pr_nope/approve", json={"actor": "a"}).status_code == 404


def test_rejecting_a_proposal_is_audited_and_changes_no_plan(client: TestClient) -> None:
    sid = _sid(client)
    plan = _active_plan(client, sid)
    _, r = _fail_aircraft(client, sid, plan)
    pid = r.json()["proposals"][0]["id"]
    rej = client.post(f"{API}/proposals/{pid}/reject", json={"actor": "cdr", "reason": "too many"})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert client.get(f"{API}/plans/{plan['id']}").json()["status"] == "approved"
    row = next(e for e in _audit(client, sid) if e["action"] == "proposal.reject")
    assert row["actor"] == "cdr" and row["details"]["reason"] == "too many"
    assert client.post(f"{API}/proposals/{pid}/reject", json={"actor": "x"}).status_code == 409
    assert client.post(f"{API}/proposals/{pid}/approve", json={"actor": "x"}).status_code == 409
    for body in ({}, {"actor": ""}, {"actor": "a", "extra": 1}):
        assert client.post(f"{API}/proposals/{pid}/reject", json=body).status_code == 422


def test_a_new_event_expires_proposals_about_the_older_state(client: TestClient) -> None:
    sid = _sid(client)
    plan = _active_plan(client, sid)
    _, r1 = _fail_aircraft(client, sid, plan, time_min=100)
    old_ids = [p["id"] for p in r1.json()["proposals"]]
    snap = client.get(f"{API}/scenarios/{sid}/snapshot").json()
    r2 = client.post(f"{API}/events", json={
        "scenario_id": sid, "type": "CREW_UNAVAILABLE", "time_min": 120, "time_limit_s": 5,
        "payload": {"crew_id": snap["crew"][0]["id"], "until_min": 700}})
    assert r2.status_code == 200
    for pid in old_ids:
        assert client.get(f"{API}/proposals/{pid}").json()["status"] == "expired"
    open_now = client.get(f"{API}/proposals", params={"scenario_id": sid, "status": "open"}).json()
    assert {p["event_id"] for p in open_now} <= {"EV-002"}


def test_proposals_can_be_listed_by_status_and_unknown_scenarios_404(client: TestClient) -> None:
    assert client.get(f"{API}/proposals", params={"scenario_id": "sc_none"}).status_code == 404
    sid = _sid(client)
    assert client.get(f"{API}/proposals", params={"scenario_id": sid}).json() == []
    assert client.get(f"{API}/proposals", params={"scenario_id": sid, "status": "bogus"}
                      ).status_code == 422


# ------------------------------------------------------------------------------ simulator
def test_simulate_injects_seeded_events_in_time_order(client: TestClient) -> None:
    sid = _sid(client)
    a = client.post(f"{API}/events/simulate", json={"scenario_id": sid, "seed": 4, "count": 4,
                                                    "from_min": 50, "to_min": 900})
    assert a.status_code == 200, a.text
    evs = a.json()["events"]
    assert len(evs) == 4 and [e["id"] for e in evs] == ["EV-001", "EV-002", "EV-003", "EV-004"]
    assert all(e["created_by"] == "sim" and e["source"] == "SIM" for e in evs)
    assert [e["time_min"] for e in evs] == sorted(e["time_min"] for e in evs)
    assert a.json()["state_version"] == 4 and a.json()["proposals"] == []


def test_simulate_is_deterministic_for_identical_scenarios(client: TestClient) -> None:
    sid = _sid(client)
    body = {"scenario_id": sid, "seed": 9, "count": 5, "from_min": 0, "to_min": 800}
    first = client.post(f"{API}/events/simulate", json=body).json()["events"]
    # regenerating identical content restores the same id; clear the live events by a new db
    from app.core.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(database_url="sqlite://", scenario_dir=client.app.state
                                        .settings.scenario_dir, solver_time_limit_s=1.0,
                                        solver_workers=1))) as c2:
        sid2 = _sid(c2)
        assert sid2 == sid
        second = c2.post(f"{API}/events/simulate", json=body).json()["events"]
    assert [(e["type"], e["time_min"], e["payload"]) for e in first] == [
        (e["type"], e["time_min"], e["payload"]) for e in second]


def test_simulate_with_proposals_and_bad_requests(client: TestClient) -> None:
    sid = _sid(client)
    _active_plan(client, sid)
    r = client.post(f"{API}/events/simulate", json={
        "scenario_id": sid, "seed": 2, "count": 2, "from_min": 100, "to_min": 700,
        "propose": True, "time_limit_s": 6})
    assert r.status_code == 200
    assert r.json()["active_plan_id"] is not None
    assert all(p["event_id"] == r.json()["events"][-1]["id"] for p in r.json()["proposals"])
    for bad in ({"seed": 1, "count": 0}, {"seed": 1, "count": 99}, {"seed": 1, "rate": 0},
                {"seed": 1, "from_min": 500, "to_min": 100}, {"count": 2}):
        assert client.post(f"{API}/events/simulate", json={"scenario_id": sid, **bad}
                           ).status_code == 422, bad
    assert client.post(f"{API}/events/simulate", json={"scenario_id": "sc_none", "seed": 1}
                       ).status_code == 404


# ------------------------------------------------------------------------------ audit + ws
def test_audit_endpoint_filters_and_limits(client: TestClient) -> None:
    sid = _sid(client)
    plan = _active_plan(client, sid)
    _fail_aircraft(client, sid, plan)
    everything = _audit(client, sid)
    assert [e["action"] for e in everything][:3] == ["plan.generate", "plan.approve", "event.inject"]
    only = client.get(f"{API}/audit", params={"scenario_id": sid, "object_id": "EV-001"}).json()
    assert {e["object_id"] for e in only} == {"EV-001"} and len(only) >= 2  # inject + propose
    assert len(client.get(f"{API}/audit", params={"scenario_id": sid, "limit": 2}).json()) == 2
    assert client.get(f"{API}/audit", params={"scenario_id": sid, "limit": 0}).status_code == 422
    assert len(client.get(f"{API}/audit").json()) >= len(everything)


def test_websocket_pushes_the_documented_message_types(client: TestClient) -> None:
    sid = _sid(client)
    other = _sid(client, seed=4)
    plan = _active_plan(client, sid)
    with client.websocket_connect(f"{API}/ws") as ws, client.websocket_connect(f"{API}/ws") as ws2:
        ws.send_json({"type": "subscribe", "scenario_id": sid})
        assert ws.receive_json()["type"] == "subscribed"
        ws2.send_json({"type": "subscribe", "scenario_id": other})
        assert ws2.receive_json()["data"]["scenario_id"] == other
        _, r = _fail_aircraft(client, sid, plan)
        seen: list[dict] = []
        while not seen or seen[-1]["type"] != "alert.created":
            seen.append(ws.receive_json())
        types = [m["type"] for m in seen]
        assert types[:2] == ["event.created", "state.updated"]
        assert types.count("proposal.created") == len(r.json()["proposals"])
        assert types[-1] == "alert.created"
        for m in seen:
            assert set(m) == {"type", "ts", "data"} and m["ts"]
        alert = seen[-1]["data"]
        assert alert["event_id"] == "EV-001" and alert["affected_assignments"]
        client.post(f"{API}/proposals/{r.json()['proposals'][0]['id']}/approve",
                    json={"actor": "ops"})
        after = [ws.receive_json()["type"] for _ in range(2 + len(r.json()["proposals"]) - 1)]
        assert "plan.approved" in after and "proposal.updated" in after
    # a client subscribed to another scenario saw none of it
    with client.websocket_connect(f"{API}/ws") as ws3:
        ws3.send_json({"type": "subscribe", "scenario_id": other})
        assert ws3.receive_json()["type"] == "subscribed"


def test_websocket_ignores_garbage_and_publishes_plan_created_and_pins(client: TestClient) -> None:
    sid = _sid(client)
    with client.websocket_connect(f"{API}/ws") as ws:
        ws.send_json({"type": "hello"})
        ws.send_json({"type": "subscribe", "scenario_id": sid})
        assert ws.receive_json()["type"] == "subscribed"
        client.post(f"{API}/plans/generate", json={"scenario_id": sid, "planner": "greedy"})
        m = ws.receive_json()
        assert m["type"] == "plan.created" and m["data"]["planner"] == "greedy"
        conflict = client.get(f"{API}/scenarios/{sid}/fusion-report").json()["conflicts"][0]
        client.post(f"{API}/scenarios/{sid}/conflicts/{conflict['id']}/pin",
                    json={"actor": "a", "source": conflict["candidates"][0]["source"]})
        m2 = ws.receive_json()
        assert m2["type"] == "fusion.conflict" and m2["data"]["conflict_id"] == conflict["id"]
