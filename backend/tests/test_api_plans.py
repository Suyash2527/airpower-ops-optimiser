"""Plan endpoints (Task 4.8): generate, get, list, validate, compare."""

from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"
SMALL = {"seed": 3, "n_aircraft": 20, "n_crew": 30, "n_missions": 14, "n_bases": 3}


def _sid(client: TestClient) -> str:
    return client.post(f"{API}/scenarios/generate", json=SMALL).json()["scenario_id"]


def _gen(client: TestClient, sid: str, **over):
    return client.post(f"{API}/plans/generate",
                       json={"scenario_id": sid, "time_limit_s": 10, **over})


def test_generate_cpsat_returns_a_valid_plan_with_inputs_and_explanations(
    client: TestClient,
) -> None:
    sid = _sid(client)
    r = _gen(client, sid)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["id"].startswith("p_") and p["version"] == 1 and p["status"] == "draft"
    assert p["scenario_id"] == sid and p["parent_plan_id"] is None and p["data_label"] == "mixed"
    assert p["violations"] == 0 and p["solver"]["name"] == "cpsat"
    assert p["solver"]["status"] in ("OPTIMAL", "FEASIBLE") or p["solver"]["status"].startswith(
        "FALLBACK")
    assert p["inputs"] == {"planner": "cpsat", "time_limit_s": 10.0,
                           "weight_preset": "coverage_first", "fused": True, "secondary": True,
                           "now_min": 0, "seed": 0}
    k = p["kpis"]
    assert 0 <= k["priority_weighted_coverage"] <= 1 and k["missions_total"] == 14
    assert p["assignments"], "the scenario has coverable missions"
    for a in p["assignments"]:
        assert a["explanation"] and a["reasons"] == ["ASSIGNED_BEST_SCORE"] and a["crew_ids"]
    for u in p["unassigned"]:
        assert u["explanation"] and u["blocking_reasons"]
    assigned = {a["mission_id"] for a in p["assignments"]}
    assert assigned.isdisjoint({u["mission_id"] for u in p["unassigned"]})
    assert len(assigned) + len(p["unassigned"]) == 14 - 0


def test_versions_increase_and_plans_can_be_fetched_and_listed(client: TestClient) -> None:
    sid = _sid(client)
    ids = [_gen(client, sid, planner=pl).json()["id"] for pl in ("greedy", "fifo", "cpsat")]
    assert [client.get(f"{API}/plans/{i}").json()["version"] for i in ids] == [1, 2, 3]
    listed = client.get(f"{API}/plans", params={"scenario_id": sid}).json()
    assert [p["id"] for p in listed] == ids
    assert [p["solver"]["name"] for p in listed] == ["greedy_priority", "fifo", "cpsat"]
    assert client.get(f"{API}/plans", params={"scenario_id": "sc_none"}).json() == []


def test_validate_endpoint_rechecks_the_stored_plan(client: TestClient) -> None:
    sid = _sid(client)
    pid = _gen(client, sid, planner="greedy").json()["id"]
    v = client.post(f"{API}/plans/{pid}/validate").json()
    assert v["plan_id"] == pid and v["valid"] is True and v["violations"] == []
    assert "pins" in v["note"]


def test_compare_gives_kpi_deltas_and_a_diff(client: TestClient) -> None:
    sid = _sid(client)
    a = _gen(client, sid, planner="greedy").json()
    b = _gen(client, sid, planner="cpsat").json()
    c = client.get(f"{API}/plans/compare", params={"a": a["id"], "b": b["id"]}).json()
    assert c["a"] == a["id"] and c["b"] == b["id"]
    d = round(b["kpis"]["priority_weighted_coverage"] - a["kpis"]["priority_weighted_coverage"], 4)
    assert c["kpi_delta"]["priority_weighted_coverage"] == d
    assert c["diff"]["coverage_delta"] == d
    assert c["diff"]["n_changes"] >= 0 and set(c["diff"]) >= {"added", "removed", "changed"}
    same = client.get(f"{API}/plans/compare", params={"a": a["id"], "b": a["id"]}).json()
    assert same["diff"]["n_changes"] == 0 and same["kpi_delta"]["priority_weighted_coverage"] == 0


def test_weight_preset_and_options_are_recorded_and_validated(client: TestClient) -> None:
    sid = _sid(client)
    r = _gen(client, sid, weight_preset="risk_averse", fused=False, now_min=0, seed=7)
    assert r.status_code == 200
    assert r.json()["inputs"]["weight_preset"] == "risk_averse" and r.json()["inputs"]["fused"] is False
    bad = _gen(client, sid, weight_preset="nonsense")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_weight_preset"


def test_errors(client: TestClient) -> None:
    sid = _sid(client)
    assert _gen(client, "sc_nope").status_code == 404
    assert client.get(f"{API}/plans/p_nope").status_code == 404
    assert client.post(f"{API}/plans/p_nope/validate").status_code == 404
    assert client.get(f"{API}/plans/compare", params={"a": "x", "b": "y"}).status_code == 404
    assert _gen(client, sid, planner="magic").status_code == 422
    assert _gen(client, sid, time_limit_s=0).status_code == 422
    assert _gen(client, sid, extra_field=1).status_code == 422
    other = client.post(f"{API}/scenarios/generate", json={**SMALL, "seed": 4}).json()["scenario_id"]
    a, b = _gen(client, sid, planner="greedy").json()["id"], _gen(client, other,
                                                                   planner="greedy").json()["id"]
    r = client.get(f"{API}/plans/compare", params={"a": a, "b": b})
    assert r.status_code == 409 and r.json()["error"]["code"] == "different_scenarios"


def test_generation_is_deterministic_for_greedy(client: TestClient) -> None:
    sid = _sid(client)
    a = _gen(client, sid, planner="greedy").json()
    b = _gen(client, sid, planner="greedy").json()
    strip = lambda p: [{k: v for k, v in x.items()} for x in p["assignments"]]  # noqa: E731
    assert strip(a) == strip(b) and a["id"] != b["id"]
