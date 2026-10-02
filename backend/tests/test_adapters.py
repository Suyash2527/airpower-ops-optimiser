"""Adapter tests: SyntheticAdapter, the seeded noisy secondary, and FileAdapter (Tasks 2.1-2.3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.ingest.adapters import (
    Adapter,
    AdapterError,
    FileAdapter,
    SecondaryParams,
    SecondarySyntheticAdapter,
    SyntheticAdapter,
)
from app.ingest.adapters.synthetic import NOISE
from app.ingest.fusion import fuse
from app.ingest.models import FUSED_GROUPS
from app.models.scenario import GeneratorParams, ScenarioFile, entity_key
from app.sim.generate import generate_scenario


@pytest.fixture(scope="module")
def scenario() -> ScenarioFile:
    return generate_scenario(GeneratorParams(seed=7, n_aircraft=20, n_crew=30, n_missions=20))


def test_adapters_satisfy_the_protocol(scenario: ScenarioFile, tmp_path: Path) -> None:
    assert isinstance(SyntheticAdapter(scenario), Adapter)
    assert isinstance(SecondarySyntheticAdapter(scenario), Adapter)
    assert isinstance(FileAdapter(tmp_path / "x.json", "aircraft"), Adapter)


def test_synthetic_adapter_returns_every_fused_group_unchanged(scenario: ScenarioFile) -> None:
    batch = SyntheticAdapter(scenario).fetch()
    assert set(batch.records) == set(FUSED_GROUPS)
    for group in FUSED_GROUPS:
        assert batch.records[group] == getattr(scenario, group)
    assert batch.rejected == []


# ----------------------------------------------------------------------- secondary (noisy) feed
def _dump(batch) -> str:
    return json.dumps(
        {g: [r.model_dump(mode="json") for r in rows] for g, rows in batch.records.items()},
        sort_keys=True,
    )


def test_secondary_feed_is_deterministic_per_seed_and_differs_across_seeds(
    scenario: ScenarioFile,
) -> None:
    first = _dump(SecondarySyntheticAdapter(scenario).fetch())
    assert first == _dump(SecondarySyntheticAdapter(scenario).fetch())
    other = generate_scenario(GeneratorParams(seed=8, n_aircraft=20, n_crew=30, n_missions=20))
    assert first != _dump(SecondarySyntheticAdapter(other).fetch())


def test_secondary_feed_only_touches_documented_noisy_fields(scenario: ScenarioFile) -> None:
    batch = SecondarySyntheticAdapter(scenario).fetch()
    for group, rows in batch.records.items():
        truth = {entity_key(group, e): e.model_dump(mode="json") for e in getattr(scenario, group)}
        for row in rows:
            rec = row.model_dump(mode="json")
            original = truth[entity_key(group, row)]
            changed = {k for k in rec if k != "provenance" and rec[k] != original[k]}
            assert changed <= set(NOISE[group]), (group, changed)
            assert rec["provenance"]["source"] == "SYNTHETIC_SECONDARY"
            assert rec["provenance"]["data_label"] == "synthetic"
            assert rec["provenance"]["observed_at"] <= scenario.scenario.t0.isoformat().replace(
                "+00:00", "Z"
            )


def test_secondary_feed_covers_a_subset_and_includes_some_stale_timestamps(
    scenario: ScenarioFile,
) -> None:
    batch = SecondarySyntheticAdapter(scenario).fetch()
    total = sum(len(getattr(scenario, g)) for g in FUSED_GROUPS)
    reported = sum(len(rows) for rows in batch.records.values())
    assert 0.3 * total < reported < 0.7 * total  # coverage 0.5 +/- sampling noise
    ages = [
        (scenario.scenario.t0 - r.provenance.observed_at).total_seconds() / 60  # type: ignore[attr-defined]
        for r in batch.records["aircraft"]
    ]
    assert any(a > 60 for a in ages) and any(a <= 30 for a in ages)


def test_secondary_params_zero_noise_means_full_agreement(scenario: ScenarioFile) -> None:
    quiet = SecondaryParams(coverage=1.0, field_noise_rate=0.0, stale_fraction=0.0)
    batches = [
        SyntheticAdapter(scenario).fetch(), SecondarySyntheticAdapter(scenario, quiet).fetch()
    ]
    state = fuse(batches, scenario.scenario.t0)
    assert state.report.counts.conflicts == 0
    assert state.report.counts.fields_agree == state.report.counts.fields_compared > 0


def test_fusing_primary_and_noisy_secondary_produces_conflicts_and_valid_entities(
    scenario: ScenarioFile,
) -> None:
    state = fuse(
        [SyntheticAdapter(scenario).fetch(), SecondarySyntheticAdapter(scenario).fetch()],
        scenario.scenario.t0,
    )
    assert state.report.counts.conflicts > 0
    assert {c.group for c in state.report.conflicts} <= set(NOISE)
    for group in FUSED_GROUPS:  # nothing lost, nothing invented
        assert [entity_key(group, e) for e in state.entities[group]] == [
            entity_key(group, e) for e in getattr(scenario, group)
        ]


# --------------------------------------------------------------------------------- FileAdapter
OBSERVED = datetime(2027, 7, 20, 2, 0, tzinfo=UTC)


def _aircraft_row(**over) -> dict:
    row = {
        "id": "A-901", "tail": "X-901", "type_id": "FTR-A", "base_id": "BASE-N1",
        "status": "SERVICEABLE", "available_from_min": 0, "hours_since_maintenance": 12.5,
        "fuel_state_pct": 90.0, "current_loadout_id": None,
    }
    return {**row, **over}


def test_file_adapter_reads_json_and_stamps_provenance(tmp_path: Path) -> None:
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps({"records": [_aircraft_row(), _aircraft_row(id="A-902")]}))
    batch = FileAdapter(path, "aircraft", observed_at=OBSERVED, confidence=0.6).fetch()
    assert [r.id for r in batch.records["aircraft"]] == ["A-901", "A-902"]  # type: ignore[attr-defined]
    p = batch.records["aircraft"][0].provenance  # type: ignore[attr-defined]
    assert (p.source, p.observed_at, p.confidence, p.data_label) == (
        "FILE:fleet", OBSERVED, 0.6, "external",
    )
    assert batch.rejected == []


def test_file_adapter_reads_csv_with_structured_cells_and_per_row_metadata(tmp_path: Path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text(
        "id,name,role,qualifications,base_id,status,duty_minutes_last_24h,last_duty_end_min,"
        "_observed_at,_confidence\n"
        'C-901,CODE-1,PILOT,"[""FTR-A"", ""TPT-B""]",BASE-N1,AVAILABLE,120,-700,'
        "2027-07-20T01:00:00Z,0.9\n"
        'C-902,CODE-2,PILOT,"[""FTR-A""]",BASE-N1,SICK,0,-900,,\n',
        encoding="utf-8",
    )
    adapter = FileAdapter(path, "crew", observed_at=OBSERVED, confidence=0.5, source="FILE:hr")
    batch = adapter.fetch()
    first, second = batch.records["crew"]
    assert first.qualifications == ["FTR-A", "TPT-B"]  # type: ignore[attr-defined]
    assert first.provenance.observed_at == datetime(2027, 7, 20, 1, 0, tzinfo=UTC)  # type: ignore[attr-defined]
    assert first.provenance.confidence == 0.9  # type: ignore[attr-defined]
    assert second.provenance.observed_at == OBSERVED and second.provenance.confidence == 0.5  # type: ignore[attr-defined]
    assert second.provenance.source == "FILE:hr"  # type: ignore[attr-defined]


def test_csv_ids_keep_leading_zeros(tmp_path: Path) -> None:
    path = tmp_path / "fleet.csv"
    path.write_text(
        "id,tail,type_id,base_id,status,available_from_min,hours_since_maintenance,"
        "fuel_state_pct,current_loadout_id\n007,X-1,FTR-A,BASE-N1,SERVICEABLE,0,1.5,50,\n"
    )
    (rec,) = FileAdapter(path, "aircraft", observed_at=OBSERVED).fetch().records["aircraft"]
    assert rec.id == "007" and rec.current_loadout_id is None  # type: ignore[attr-defined]


def test_bad_rows_are_rejected_with_a_reason_not_dropped_silently(tmp_path: Path) -> None:
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps([
        _aircraft_row(),
        _aircraft_row(id="A-902", fuel_state_pct=140),  # out of range
        _aircraft_row(id="A-903", status="FLYING"),  # not a status
        {**_aircraft_row(id="A-904"), "mystery": 1},  # unknown column
        _aircraft_row(id="A-905"),
    ]))
    batch = FileAdapter(path, "aircraft", observed_at=OBSERVED).fetch()
    assert [r.id for r in batch.records["aircraft"]] == ["A-901", "A-905"]  # type: ignore[attr-defined]
    assert [r.row for r in batch.rejected] == [2, 3, 4]
    assert "fuel_state_pct" in batch.rejected[0].message
    assert all(r.group == "aircraft" and r.adapter == "FILE:fleet" for r in batch.rejected)


def test_row_without_any_observed_time_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps([_aircraft_row()]))
    batch = FileAdapter(path, "aircraft").fetch()
    assert batch.records["aircraft"] == [] and "observed time" in batch.rejected[0].message


def test_naive_timestamps_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fleet.csv"
    path.write_text(
        "id,tail,type_id,base_id,status,available_from_min,hours_since_maintenance,"
        "fuel_state_pct,current_loadout_id,_observed_at\n"
        "A-1,X,FTR-A,BASE-N1,SERVICEABLE,0,1,50,,2027-07-20T01:00:00\n"
    )
    batch = FileAdapter(path, "aircraft").fetch()
    assert batch.records["aircraft"] == [] and batch.rejected[0].row == 1


@pytest.mark.parametrize(
    ("name", "content", "group", "needle"),
    [
        ("missing.json", None, "aircraft", "not found"),
        ("bad.json", "{not json", "aircraft", "not valid JSON"),
        ("shape.json", '{"a": 1}', "aircraft", "list of objects"),
        ("feed.xml", "<x/>", "aircraft", "unsupported"),
        ("fleet.json", "[]", "bases", "cannot be fused"),
    ],
)
def test_unusable_input_raises_adapter_error(
    tmp_path: Path, name: str, content: str | None, group: str, needle: str
) -> None:
    path = tmp_path / name
    if content is not None:
        path.write_text(content)
    with pytest.raises(AdapterError, match=needle):
        FileAdapter(path, group).fetch()


def test_file_feed_participates_in_fusion_like_any_other_source(
    scenario: ScenarioFile, tmp_path: Path
) -> None:
    a0 = scenario.aircraft[0]
    path = tmp_path / "ops_desk.json"
    other = "DEGRADED" if a0.status.value == "SERVICEABLE" else "SERVICEABLE"
    path.write_text(json.dumps([
        {**a0.model_dump(mode="json", exclude={"provenance"}), "status": other},
        _aircraft_row(id="A-NEW"),  # only the file knows this aircraft
        _aircraft_row(id="A-BAD", fuel_state_pct=-5),
    ]))
    t0 = scenario.scenario.t0
    file_batch = FileAdapter(path, "aircraft", observed_at=t0 - timedelta(minutes=1)).fetch()
    state = fuse([SyntheticAdapter(scenario).fetch(), file_batch], t0)
    ids = [a.id for a in state.entities["aircraft"]]  # type: ignore[attr-defined]
    assert ids[-1] == "A-NEW" and "A-BAD" not in ids and len(ids) == len(scenario.aircraft) + 1
    assert state.report.counts.rejected_records == 1
    status = next(c for c in state.report.conflicts if c.entity_id == a0.id and c.field == "status")
    assert {c.source for c in status.candidates} == {"SYNTHETIC", "FILE:ops_desk"}
    assert state.meta["aircraft"]["A-NEW"].sources == ["FILE:ops_desk"]
