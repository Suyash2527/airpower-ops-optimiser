"""API tests for the fusion layer (Tasks 2.5, 2.6): fusion-report, fused snapshot, pins, audit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.audit import log as audit
from app.models.scenario import GROUPS

API = "/api/v1/scenarios"
SMALL = {"seed": 11, "n_aircraft": 20, "n_crew": 30, "n_missions": 16, "n_bases": 3}


def _sid(client: TestClient, **over) -> str:
    r = client.post(f"{API}/generate", json={**SMALL, **over})
    assert r.status_code == 200, r.text
    return r.json()["scenario_id"]


def _report(client: TestClient, sid: str, **params) -> dict:
    r = client.get(f"{API}/{sid}/fusion-report", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------- report
def test_fusion_report_shape_and_counts_are_self_consistent(client: TestClient) -> None:
    sid = _sid(client)
    rep = _report(client, sid)
    counts = rep["counts"]
    assert rep["scenario_id"] == sid and rep["data_label"] == "mixed"
    assert rep["secondary_source_enabled"] is True and rep["state_version"] == 0
    assert counts["records"] == counts["single_source"] + counts["multi_source"] > 0
    assert counts["conflicts"] == len(rep["conflicts"]) > 0
    assert counts["conflicts"] == counts["conflicts_open"] + counts["conflicts_pinned"]
    assert counts["fields_compared"] >= counts["fields_agree"] + counts["conflicts"] - 1
    assert sum(g["records"] for g in rep["by_group"].values()) == counts["records"]
    assert {s["source"] for s in rep["sources"]} == {"SYNTHETIC", "SYNTHETIC_SECONDARY"}
    assert "not empirical" in rep["config"]["notice"]
    for c in rep["conflicts"]:  # UI-ready: both values, sources, numbers, reason, sentence
        assert len(c["candidates"]) >= 2 and c["explanation"] and c["reason"]
        assert c["id"].startswith("cf_") and c["status"] == "open"
        assert sum(x["selected"] for x in c["candidates"]) == 1
        assert len({json.dumps(x["value"], sort_keys=True) for x in c["candidates"]}) >= 2


def test_report_is_deterministic_within_and_across_requests(client: TestClient) -> None:
    sid = _sid(client)
    assert _report(client, sid) == _report(client, sid)
    # regenerating the same parameters gives the same scenario id and the same report
    assert _sid(client) == sid and _report(client, sid) == _report(client, sid)


def test_secondary_source_can_be_switched_off(client: TestClient) -> None:
    sid = _sid(client)
    rep = _report(client, sid, secondary="false")
    assert rep["secondary_source_enabled"] is False
    assert rep["counts"]["conflicts"] == 0 and rep["counts"]["multi_source"] == 0
    assert [s["source"] for s in rep["sources"]] == ["SYNTHETIC"]


def test_staleness_grows_as_fusion_time_advances(client: TestClient) -> None:
    sid = _sid(client)
    stale = [
        _report(client, sid, now_min=m)["counts"]["stale_records"] for m in (0, 60, 240, 2000)
    ]
    assert stale == sorted(stale) and stale[0] == 0 and stale[-1] > 0
    late = _report(client, sid, now_min=2000)
    assert late["stale"] and all(s["staleness_min"] > s["max_age_min"] for s in late["stale"])
    assert {c["reason"] for c in late["conflicts"]} >= {"ALL_OBSERVATIONS_STALE"}


def test_fusion_report_unknown_scenario_and_bad_params(client: TestClient) -> None:
    r = client.get(f"{API}/sc_nope/fusion-report")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    sid = _sid(client)
    assert client.get(f"{API}/{sid}/fusion-report", params={"now_min": -1}).status_code == 422


# ------------------------------------------------------------------------------- fused snapshot
def test_fused_snapshot_keeps_every_group_and_adds_staleness_meta(client: TestClient) -> None:
    sid = _sid(client)
    snap = client.get(f"{API}/{sid}/snapshot").json()
    raw = client.get(f"{API}/{sid}/snapshot", params={"fused": "false"}).json()
    assert snap["fused"] is True and raw["fused"] is False and raw["fusion_meta"] == {}
    for group in GROUPS:
        assert len(snap[group]) == len(raw[group]) > 0
    meta = snap["fusion_meta"]["aircraft"]
    assert set(meta) == {a["id"] for a in snap["aircraft"]}
    one = next(iter(meta.values()))
    assert {"source", "sources", "staleness_min", "stale", "stale_fields", "confidence"} <= set(one)
    for a in snap["aircraft"]:  # fused provenance agrees with the sidecar
        m = meta[a["id"]]
        assert a["provenance"]["source"] == m["source"]
        assert a["provenance"]["observed_at"].replace("Z", "+00:00") == m["observed_at"].replace(
            "Z", "+00:00"
        )
    # reference data is untouched by fusion
    for group in ("bases", "aircraft_types", "loadouts", "alternate_airfields", "events"):
        assert snap[group] == raw[group]


def test_snapshot_without_secondary_equals_the_stored_values(client: TestClient) -> None:
    sid = _sid(client)
    fused = client.get(f"{API}/{sid}/snapshot", params={"secondary": "false"}).json()
    raw = client.get(f"{API}/{sid}/snapshot", params={"fused": "false"}).json()
    strip = lambda rows: [{k: v for k, v in r.items() if k != "provenance"} for r in rows]  # noqa: E731
    live = ("aircraft", "crew", "missions", "threats", "weather", "airspace", "weapon_stocks")
    for group in live:
        assert strip(fused[group]) == strip(raw[group]), group


# --------------------------------------------------------------------------------------- pins
def _pick(client: TestClient, sid: str, field: str = "status", group: str = "aircraft") -> dict:
    rep = _report(client, sid)
    return next(c for c in rep["conflicts"] if c["group"] == group and c["field"] == field)


def _entity(client: TestClient, sid: str, group: str, key: str) -> dict:
    snap = client.get(f"{API}/{sid}/snapshot").json()
    return next(r for r in snap[group] if r["id"] == key)


def _db_session(client: TestClient) -> Session:
    return Session(client.app.state.engine)  # type: ignore[attr-defined]


def test_pin_to_a_reported_source_changes_the_fused_value_and_is_audited(
    client: TestClient,
) -> None:
    sid = _sid(client)
    conflict = _pick(client, sid)
    loser = next(c for c in conflict["candidates"] if not c["selected"])
    assert loser["value"] != conflict["resolved_value"]

    r = client.post(
        f"{API}/{sid}/conflicts/{conflict['id']}/pin",
        json={"actor": "duty.officer", "source": loser["source"], "reason": "seen on the apron"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state_version"] == 1 and body["data_label"] == "mixed"
    pinned = body["conflict"]
    assert pinned["status"] == "pinned" and pinned["reason"] == "PINNED_BY_HUMAN"
    assert pinned["resolved_value"] == loser["value"]
    assert pinned["resolved_source"] == "PIN:duty.officer"
    assert pinned["pin"]["chosen_source"] == loser["source"]

    # persists: the report, the snapshot and the state version all reflect it
    rep = _report(client, sid)
    assert rep["state_version"] == 1 and rep["counts"]["conflicts_pinned"] == 1
    again = next(c for c in rep["conflicts"] if c["id"] == conflict["id"])
    assert again["status"] == "pinned" and again["resolved_value"] == loser["value"]
    entity = _entity(client, sid, conflict["group"], conflict["entity_id"])
    assert entity[conflict["field"]] == loser["value"]
    assert "status" in client.get(f"{API}/{sid}/snapshot").json()["fusion_meta"]["aircraft"][
        conflict["entity_id"]
    ]["pinned_fields"]

    # audited, append-only, with before/after
    with _db_session(client) as session:
        (entry,) = audit.list_entries(session, sid, object_id=conflict["id"])
    assert entry.action == "fusion.pin" and entry.actor == "duty.officer"
    assert entry.object_type == "conflict" and entry.id == "au_00001"
    assert entry.details["from_value"] == conflict["resolved_value"]
    assert entry.details["to_value"] == loser["value"] and entry.details["reason"]


def test_pin_with_an_explicit_value_and_a_second_pin_replaces_the_first(client: TestClient) -> None:
    sid = _sid(client)
    conflict = _pick(client, sid)
    url = f"{API}/{sid}/conflicts/{conflict['id']}/pin"
    assert client.post(url, json={"actor": "a", "value": "UNSERVICEABLE"}).status_code == 200
    assert _entity(client, sid, "aircraft", conflict["entity_id"])["status"] == "UNSERVICEABLE"
    second = client.post(url, json={"actor": "b", "value": "SERVICEABLE"})
    assert second.json()["state_version"] == 2
    assert _entity(client, sid, "aircraft", conflict["entity_id"])["status"] == "SERVICEABLE"
    with _db_session(client) as session:
        entries = audit.list_entries(session, sid)
    assert [e.actor for e in entries] == ["a", "b"]  # both decisions kept, in order


def test_invalid_pin_requests_are_refused_and_leave_no_trace(client: TestClient) -> None:
    sid = _sid(client)
    conflict = _pick(client, sid)
    url = f"{API}/{sid}/conflicts/{conflict['id']}/pin"

    bad_value = client.post(url, json={"actor": "a", "value": "FLYING"})
    assert bad_value.status_code == 422 and bad_value.json()["error"]["code"] == "invalid_pin_value"
    unknown_source = client.post(url, json={"actor": "a", "source": "NOBODY"})
    assert unknown_source.status_code == 422
    assert unknown_source.json()["error"]["code"] == "unknown_source"
    for body in (
        {"actor": "a"},  # neither source nor value
        {"actor": "a", "source": "SYNTHETIC", "value": "DEGRADED"},  # both
        {"actor": " ", "value": "DEGRADED"},  # blank actor
        {"value": "DEGRADED"},  # no actor
        {"actor": "a", "value": "DEGRADED", "extra": 1},  # unknown key
    ):
        assert client.post(url, json=body).status_code == 422, body
    assert client.post(f"{API}/{sid}/conflicts/cf_missing/pin", json={"actor": "a", "value": 1}
                       ).status_code == 404
    assert client.post(f"{API}/sc_nope/conflicts/{conflict['id']}/pin",
                       json={"actor": "a", "value": 1}).status_code == 404

    assert _report(client, sid)["state_version"] == 0
    with _db_session(client) as session:
        assert audit.list_entries(session, sid) == []


def test_explicit_null_is_a_real_choice_and_is_validated(client: TestClient) -> None:
    sid = _sid(client)
    rep = _report(client, sid)
    conflict = next((c for c in rep["conflicts"] if c["field"] == "status"), None)
    assert conflict is not None
    # value=None present in the body is a choice (distinct from omitting `value`); it is then
    # validated like any other value, and `status` may not be null.
    r = client.post(
        f"{API}/{sid}/conflicts/{conflict['id']}/pin", json={"actor": "a", "value": None}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_pin_value"


def test_pins_belong_to_one_scenario(client: TestClient) -> None:
    a, b = _sid(client, seed=1), _sid(client, seed=2)
    conflict = _pick(client, a)
    url = f"{API}/{a}/conflicts/{conflict['id']}/pin"
    client.post(url, json={"actor": "x", "value": "DEGRADED"})
    assert _report(client, a)["state_version"] == 1 and _report(client, b)["state_version"] == 0


# ------------------------------------------------------------- determinism across processes
HASH = (
    "import hashlib, sys;"
    "from fastapi.testclient import TestClient;"
    "from app.core.config import Settings;"
    "from app.main import create_app;"
    "from pathlib import Path;"
    "s = Settings(database_url='sqlite://', scenario_dir=Path('.'), solver_time_limit_s=1);"
    "c = TestClient(create_app(s)).__enter__();"
    "sid = c.post('/api/v1/scenarios/generate', json={'seed': 5, 'n_aircraft': 15, 'n_crew': 20,"
    " 'n_missions': 12}).json()['scenario_id'];"
    "r = c.get(f'/api/v1/scenarios/{sid}/fusion-report', params={'now_min': 90}).text;"
    "k = c.get(f'/api/v1/scenarios/{sid}/snapshot', params={'now_min': 90}).text;"
    "print(hashlib.sha256((r + k).encode()).hexdigest())"
)


@pytest.mark.parametrize("hash_seed", ["0", "1", "12345"])
def test_fusion_output_is_identical_across_processes_and_hash_seeds(hash_seed: str) -> None:
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    out = subprocess.run(
        [sys.executable, "-c", HASH], cwd=backend, env=env, capture_output=True, text=True,
        check=True,
    ).stdout.strip()
    assert out == _expected_digest()


_digest: list[str] = []


def _expected_digest() -> str:
    if not _digest:
        backend = Path(__file__).resolve().parents[1]
        out = subprocess.run(
            [sys.executable, "-c", HASH], cwd=backend, env={**os.environ, "PYTHONHASHSEED": "42"},
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        _digest.append(out)
    return _digest[0]
