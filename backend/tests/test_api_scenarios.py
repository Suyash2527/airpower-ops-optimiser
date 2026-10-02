from pathlib import Path

from fastapi.testclient import TestClient

from app.models.scenario import GROUPS, ScenarioFile
from app.sim.scenario_io import save_scenario

SMALL = {"seed": 9, "n_aircraft": 12, "n_crew": 20, "n_missions": 10, "n_bases": 2}


def _generate(client: TestClient, **body: object) -> dict:
    r = client.post("/api/v1/scenarios/generate", json={**SMALL, **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_generate_returns_summary_with_data_label(client: TestClient) -> None:
    body = _generate(client)
    assert body["scenario_id"].startswith("sc_")
    assert body["data_label"] == "mixed"  # includes open civil-airport data
    assert body["counts"]["aircraft"] == 12 and body["counts"]["missions"] == 10


def test_generate_is_idempotent_for_same_params(client: TestClient) -> None:
    a, b = _generate(client), _generate(client)
    assert a["scenario_id"] == b["scenario_id"]
    assert len(client.get("/api/v1/scenarios").json()["scenarios"]) == 1


def test_snapshot_returns_every_entity_group_with_provenance(client: TestClient) -> None:
    sid = _generate(client)["scenario_id"]
    r = client.get(f"/api/v1/scenarios/{sid}/snapshot")
    assert r.status_code == 200
    snap = r.json()
    assert snap["scenario_id"] == sid and snap["data_label"] == "mixed"
    assert snap["scenario"]["source"] == "SYNTHETIC"
    for group in GROUPS:
        assert snap[group], f"group {group} is empty"
        for record in snap[group]:
            prov = record["provenance"]
            assert prov["source"] in ("SYNTHETIC", "OURAIRPORTS")
            assert set(prov) == {"source", "observed_at", "ingested_at", "confidence", "data_label"}


def test_snapshot_round_trips_the_stored_scenario_exactly(client: TestClient) -> None:
    from app.models.scenario import GeneratorParams
    from app.sim.generate import generate_scenario

    sid = _generate(client)["scenario_id"]
    snap = client.get(f"/api/v1/scenarios/{sid}/snapshot").json()
    rebuilt = ScenarioFile(**{k: snap[k] for k in ScenarioFile.model_fields})
    expected = generate_scenario(GeneratorParams(**SMALL)).to_canonical_json()
    assert rebuilt.to_canonical_json() == expected


def test_snapshot_contains_intentionally_infeasible_missions(client: TestClient) -> None:
    sid = _generate(client)["scenario_id"]
    snap = client.get(f"/api/v1/scenarios/{sid}/snapshot").json()
    hard = snap["scenario"]["hard_cases"]
    assert len(hard) >= 4
    assert {h["mission_id"] for h in hard} <= {m["id"] for m in snap["missions"]}


def test_list_returns_generated_scenarios(client: TestClient) -> None:
    _generate(client, seed=1)
    _generate(client, seed=2)
    body = client.get("/api/v1/scenarios").json()
    assert body["data_label"] == "synthetic"
    assert {s["seed"] for s in body["scenarios"]} == {1, 2}


def test_load_reads_a_json_file_from_the_scenario_dir(
    client: TestClient, scenario_dir: Path, scenario42: ScenarioFile
) -> None:
    save_scenario(scenario42, scenario_dir / "demo.json")
    r = client.post("/api/v1/scenarios/load", json={"path": "demo.json"})
    assert r.status_code == 200
    sid = r.json()["scenario_id"]
    assert client.get(f"/api/v1/scenarios/{sid}/snapshot").status_code == 200


def test_load_rejects_paths_outside_the_scenario_dir(
    client: TestClient, scenario_dir: Path, tmp_path_factory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "secret.json"
    outside.write_text("{}")
    for bad in ("../secret.json", str(outside), "demo.txt"):
        r = client.post("/api/v1/scenarios/load", json={"path": bad})
        assert r.status_code == 400, bad
        assert r.json()["error"]["code"] == "invalid_path"


def test_load_missing_and_invalid_files(client: TestClient, scenario_dir: Path) -> None:
    r = client.post("/api/v1/scenarios/load", json={"path": "nope.json"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    (scenario_dir / "bad.json").write_text('{"scenario": 1}')
    r = client.post("/api/v1/scenarios/load", json={"path": "bad.json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_scenario"


def test_unknown_scenario_and_validation_errors_use_the_documented_shape(
    client: TestClient,
) -> None:
    r = client.get("/api/v1/scenarios/sc_missing/snapshot")
    assert r.status_code == 404
    assert set(r.json()) == {"error"} and r.json()["error"]["code"] == "not_found"
    r = client.post("/api/v1/scenarios/generate", json={"seed": 1, "n_bases": 99})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.post("/api/v1/scenarios/generate", json={"n_bases": 3})  # seed is required
    assert r.status_code == 422 and "seed" in r.json()["error"]["message"]


def test_generate_with_too_few_sites_is_a_clean_422(client: TestClient) -> None:
    r = client.post(
        "/api/v1/scenarios/generate", json={**SMALL, "n_bases": 6, "regions": ["north"]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameters"


def test_health_still_ok(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok", "data_label": "synthetic"}
