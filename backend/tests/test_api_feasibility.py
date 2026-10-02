"""GET /feasibility (Task 3.14): the debug / explain view of one mission's options."""

from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"
SMALL = {"seed": 3, "n_aircraft": 20, "n_crew": 30, "n_missions": 12, "n_bases": 3}


def _sid(client: TestClient, **over) -> str:
    return client.post(f"{API}/scenarios/generate", json={**SMALL, **over}).json()["scenario_id"]


def _get(client: TestClient, sid: str, mission: str, **params):
    return client.get(f"{API}/feasibility", params={"scenario_id": sid, "mission_id": mission,
                                                    **params})


def test_feasibility_shape_and_internal_consistency(client: TestClient) -> None:
    sid = _sid(client)
    snap = client.get(f"{API}/scenarios/{sid}/snapshot").json()
    seen_coverable = seen_blocked = False
    for m in snap["missions"]:
        r = _get(client, sid, m["id"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scenario_id"] == sid and body["mission_id"] == m["id"]
        assert body["data_label"] == "mixed" and body["fused"] is True and body["notes"]
        assert body["options_total"] == body["options_feasible"] + len(body["blocked"])
        assert body["options_feasible"] == len(body["options"])
        assert body["aircraft_required"] == m["aircraft_required"]
        assert body["feasible_aircraft"] == len({o["aircraft_id"] for o in body["options"]})
        for o in body["options"]:
            assert o["n_slots"] >= 1
            assert o["earliest_takeoff_min"] <= o["best_takeoff_min"] <= o["latest_takeoff_min"]
            assert o["earliest_takeoff_min"] % 15 == 0
            risk = o["best_risk"]
            assert 0 <= risk["total"] <= 1 and risk["total"] >= max(
                risk["threat"], risk["weather"], risk["service"]) - 1e-9
        for b in body["blocked"]:
            assert b["reasons"], b
        for t in body["blocked_by"]:
            assert t["count"] >= 1 and t["phrase"] and t["code"]
        if body["coverable"]:
            seen_coverable = True
            assert body["feasible_aircraft"] >= body["aircraft_required"]
        elif body["options_total"]:
            seen_blocked = True
    assert seen_coverable and seen_blocked  # the scenario has both kinds of mission


def test_hard_cases_report_their_intended_reason(client: TestClient) -> None:
    sid = _sid(client)
    snap = client.get(f"{API}/scenarios/{sid}/snapshot", params={"fused": "false"}).json()
    for hard in snap["scenario"]["hard_cases"]:
        body = _get(client, sid, hard["mission_id"], fused="false").json()
        codes = {t["code"] for t in body["blocked_by"]} | {r["code"] for r in body["mission_level"]}
        assert hard["intended_reason"] in codes, hard
        assert body["coverable"] is False


def test_fused_flag_and_secondary_change_the_inputs_not_the_shape(client: TestClient) -> None:
    sid = _sid(client)
    raw = _get(client, sid, "M-001", fused="false").json()
    fused = _get(client, sid, "M-001", secondary="false").json()
    assert raw["fused"] is False and fused["fused"] is True
    assert raw["options_total"] == fused["options_total"]  # same fleet, same missions
    assert _get(client, sid, "M-001").json() == _get(client, sid, "M-001").json()  # deterministic


def test_now_min_moves_the_earliest_takeoff(client: TestClient) -> None:
    sid = _sid(client)
    for m in range(1, 13):
        base = _get(client, sid, f"M-{m:03d}", fused="false").json()
        if base["options"]:
            later = _get(client, sid, f"M-{m:03d}", fused="false", now_min=1000).json()
            assert all(o["earliest_takeoff_min"] >= 1000 for o in later["options"])
            return
    raise AssertionError("no coverable mission found")


def test_unknown_scenario_mission_and_bad_params(client: TestClient) -> None:
    sid = _sid(client)
    r = _get(client, "sc_nope", "M-001")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = _get(client, sid, "M-999")
    assert r.status_code == 404 and "unknown mission" in r.json()["error"]["message"]
    assert client.get(f"{API}/feasibility", params={"scenario_id": sid}).status_code == 422
    assert _get(client, sid, "M-001", now_min=-5).status_code == 422
