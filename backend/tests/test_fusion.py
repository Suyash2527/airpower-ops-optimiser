"""Unit tests for the pure fusion step with small, hand-computable cases (Phase 2, Task 2.6).

Defaults used throughout: aircraft max age 60 min, tau 60 min; trust SYNTHETIC 1.0,
SYNTHETIC_SECONDARY 0.7, FILE:* 0.8. score = trust * confidence * exp(-age / 60).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.ingest.fusion import (
    conflict_id,
    effective_aircraft_status,
    fuse,
    materially_different,
)
from app.ingest.models import FusionConfig, FusionReason, Pin, RecordBatch
from app.models.entities import Aircraft, GeoPoint, Provenance, Threat
from app.models.enums import AircraftStatus, ThreatType

NOW = datetime(2027, 7, 20, 2, 30, tzinfo=UTC)


def prov(
    source: str, age_min: float, confidence: float = 1.0, label: str = "synthetic"
) -> Provenance:
    return Provenance(
        source=source, observed_at=NOW - timedelta(minutes=age_min), ingested_at=NOW,
        confidence=confidence, data_label=label,  # type: ignore[arg-type]
    )


def aircraft(p: Provenance, *, id: str = "A-1", status: str = "SERVICEABLE", fuel: float = 80.0,
             hours: float = 100.0) -> Aircraft:
    return Aircraft(
        id=id, tail="T-1", type_id="FTR-A", base_id="BASE-N1", status=AircraftStatus(status),
        available_from_min=0, hours_since_maintenance=hours, fuel_state_pct=fuel,
        current_loadout_id=None, provenance=p,
    )


def batch(name: str, *records: Aircraft) -> RecordBatch:
    return RecordBatch(adapter=name, records={"aircraft": list(records)})


def one(state, field: str = "status"):
    return next(c for c in state.report.conflicts if c.field == field)


# ----------------------------------------------------------------------------- merge basics
def test_single_source_passes_through_without_conflicts() -> None:
    state = fuse([batch("a", aircraft(prov("SYNTHETIC", 10, 0.9)))], NOW)
    (rec,) = state.entities["aircraft"]
    assert rec.status is AircraftStatus.SERVICEABLE  # type: ignore[attr-defined]
    meta = state.meta["aircraft"]["A-1"]
    assert meta.sources == ["SYNTHETIC"] and meta.staleness_min == 10 and not meta.stale
    assert state.report.counts.conflicts == 0 and state.report.counts.single_source == 1


def test_agreeing_sources_merge_with_no_conflict() -> None:
    a = aircraft(prov("SYNTHETIC", 10, 0.9))
    b = aircraft(prov("SYNTHETIC_SECONDARY", 5, 0.8))
    state = fuse([batch("a", a), batch("b", b)], NOW)
    c = state.report.counts
    assert c.conflicts == 0 and c.multi_source == 1
    assert c.fields_compared == 8 and c.fields_agree == 8  # every non-key field of Aircraft


def test_values_within_tolerance_are_not_a_conflict_but_beyond_it_is() -> None:
    a = aircraft(prov("SYNTHETIC", 0), fuel=70.0)
    near = aircraft(prov("SYNTHETIC_SECONDARY", 0), fuel=71.0)  # 1.4% apart, tolerance 5%
    far = aircraft(prov("SYNTHETIC_SECONDARY", 0), fuel=90.0)
    assert fuse([batch("a", a), batch("b", near)], NOW).report.counts.conflicts == 0
    state = fuse([batch("a", a), batch("b", far)], NOW)
    assert [c.field for c in state.report.conflicts] == ["fuel_state_pct"]


def test_materially_different_handles_nesting_booleans_and_coordinates() -> None:
    args = (1e-6, 0.05, 0.02)
    assert not materially_different({"lat": 25.00, "lon": 75.0}, {"lat": 25.01, "lon": 75.0}, *args)
    assert materially_different({"lat": 25.00, "lon": 75.0}, {"lat": 25.10, "lon": 75.0}, *args)
    assert materially_different(True, False, *args)
    assert not materially_different(True, True, *args)
    assert materially_different([1, 2], [1, 2, 3], *args)
    assert materially_different("a", "b", *args)
    assert materially_different({"x": 1}, {"y": 1}, *args)


def test_threat_centre_shift_of_a_few_km_is_a_conflict_and_a_hundred_metres_is_not() -> None:
    def threat(p: Provenance, lat: float) -> Threat:
        return Threat(
            id="T-1", type=ThreatType.GROUND_THREAT_ZONE, center=GeoPoint(lat=lat, lon=77.0),
            radius_km=50, severity=0.5, active_from_min=0, active_to_min=100, confidence=0.8,
            provenance=p,
        )

    def run(lat2: float):
        batches = [
            RecordBatch("a", {"threats": [threat(prov("SYNTHETIC", 0), 25.0)]}),
            RecordBatch("b", {"threats": [threat(prov("SYNTHETIC_SECONDARY", 0), lat2)]}),
        ]
        return fuse(batches, NOW).report.counts.conflicts

    assert run(25.001) == 0  # ~110 m
    assert run(25.1) == 1  # ~11 km


# ----------------------------------------------------------------------------- scoring rule
def test_higher_trust_times_confidence_wins_and_scores_are_exactly_as_documented() -> None:
    a = aircraft(prov("SYNTHETIC", 10, 0.9), status="SERVICEABLE")
    b = aircraft(prov("SYNTHETIC_SECONDARY", 5, 0.95), status="DEGRADED")
    state = fuse([batch("a", a), batch("b", b)], NOW)
    c = one(state)
    assert c.resolved_value == "SERVICEABLE" and c.resolved_source == "SYNTHETIC"
    assert c.status == "open" and c.reason is FusionReason.HIGHEST_SCORE
    win, lose = c.candidates
    assert win.selected and not lose.selected
    assert win.score == pytest.approx(1.0 * 0.9 * math.exp(-10 / 60), abs=1e-6)  # 0.7618
    assert lose.score == pytest.approx(0.7 * 0.95 * math.exp(-5 / 60), abs=1e-6)  # 0.6119
    assert state.entities["aircraft"][0].status is AircraftStatus.SERVICEABLE  # type: ignore[attr-defined]
    assert "Kept" in c.explanation and "SYNTHETIC_SECONDARY" in c.explanation


def test_recency_can_overturn_higher_trust() -> None:
    old = aircraft(prov("SYNTHETIC", 55, 0.9), status="SERVICEABLE")  # 0.9*exp(-55/60) = 0.3598
    new = aircraft(prov("SYNTHETIC_SECONDARY", 0, 0.9), status="DEGRADED")  # 0.7*0.9 = 0.63
    c = one(fuse([batch("a", old), batch("b", new)], NOW))
    assert c.resolved_value == "DEGRADED" and c.resolved_source == "SYNTHETIC_SECONDARY"


def test_ties_break_by_trust_then_source_name_regardless_of_input_order() -> None:
    # Equal scores: SYNTHETIC 0.7*1.0 = SYNTHETIC_SECONDARY 1.0*0.7 once trust is made equal.
    cfg = FusionConfig()
    cfg.source_trust["SYNTHETIC_SECONDARY"] = 1.0
    a = aircraft(prov("SYNTHETIC", 0, 0.8), fuel=50.0)
    b = aircraft(prov("SYNTHETIC_SECONDARY", 0, 0.8), fuel=90.0)
    forward = fuse([batch("a", a), batch("b", b)], NOW, cfg).entities["aircraft"][0]
    backward = fuse([batch("b", b), batch("a", a)], NOW, cfg).entities["aircraft"][0]
    assert forward.fuel_state_pct == backward.fuel_state_pct == 50.0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------- staleness
def test_stale_observation_is_discarded_when_a_fresh_one_exists_even_if_it_scores_higher() -> None:
    cfg = FusionConfig()
    cfg.source_trust["SYNTHETIC_SECONDARY"] = 0.3
    stale_hi = aircraft(prov("SYNTHETIC", 70, 1.0), status="UNSERVICEABLE")  # 0.311, but stale
    fresh_lo = aircraft(prov("SYNTHETIC_SECONDARY", 0, 0.5), status="SERVICEABLE")  # 0.15
    state = fuse([batch("a", stale_hi), batch("b", fresh_lo)], NOW, cfg)
    c = one(state)
    assert c.resolved_value == "SERVICEABLE"
    assert c.reason is FusionReason.STALE_OBSERVATION_DISCARDED
    discarded = next(x for x in c.candidates if x.source == "SYNTHETIC")
    assert discarded.stale and discarded.discarded_stale
    assert discarded.score > c.candidates[-1].score
    assert state.report.counts.discarded_stale_observations >= 1


def test_when_every_observation_is_stale_the_best_is_kept_and_flagged() -> None:
    a = aircraft(prov("SYNTHETIC", 70, 0.9), status="SERVICEABLE")
    b = aircraft(prov("SYNTHETIC_SECONDARY", 100, 0.9), status="DEGRADED")
    state = fuse([batch("a", a), batch("b", b)], NOW)
    c = one(state)
    assert c.reason is FusionReason.ALL_OBSERVATIONS_STALE and c.resolved_value == "SERVICEABLE"
    meta = state.meta["aircraft"]["A-1"]
    assert meta.stale and meta.staleness_min == 70 and "status" in meta.stale_fields
    assert state.report.stale[0].entity_id == "A-1" and state.report.stale[0].max_age_min == 60
    assert state.report.counts.stale_records == 1


def test_a_record_exactly_at_the_limit_is_fresh_and_one_minute_over_is_stale() -> None:
    at = fuse([batch("a", aircraft(prov("SYNTHETIC", 60)))], NOW)
    over = fuse([batch("a", aircraft(prov("SYNTHETIC", 61)))], NOW)
    assert not at.meta["aircraft"]["A-1"].stale and over.meta["aircraft"]["A-1"].stale


def test_future_dated_observation_counts_as_age_zero() -> None:
    state = fuse([batch("a", aircraft(prov("SYNTHETIC", -30)))], NOW)
    assert state.meta["aircraft"]["A-1"].staleness_min == 0


def test_stale_serviceable_is_treated_as_degraded_but_the_value_is_not_rewritten() -> None:
    state = fuse([batch("a", aircraft(prov("SYNTHETIC", 90), status="SERVICEABLE"))], NOW)
    rec = state.entities["aircraft"][0]
    meta = state.meta["aircraft"]["A-1"]
    assert rec.status is AircraftStatus.SERVICEABLE  # type: ignore[attr-defined]
    assert effective_aircraft_status(rec, meta) is AircraftStatus.DEGRADED  # type: ignore[arg-type]
    fresh = fuse([batch("a", aircraft(prov("SYNTHETIC", 5)))], NOW)
    assert effective_aircraft_status(
        fresh.entities["aircraft"][0], fresh.meta["aircraft"]["A-1"]  # type: ignore[arg-type]
    ) is AircraftStatus.SERVICEABLE
    unserviceable = fuse([batch("a", aircraft(prov("SYNTHETIC", 90), status="UNSERVICEABLE"))], NOW)
    assert effective_aircraft_status(
        unserviceable.entities["aircraft"][0], unserviceable.meta["aircraft"]["A-1"]  # type: ignore[arg-type]
    ) is AircraftStatus.UNSERVICEABLE


# ------------------------------------------------------------------ provenance of the result
def test_fused_record_provenance_follows_the_winning_fields() -> None:
    # FILE scores 0.8*1.0 = 0.80 against SYNTHETIC 1.0*0.9*exp(-10/60) = 0.76, so it wins every
    # field and the record is labelled external, with the conservative (lowest) confidence.
    a = aircraft(prov("SYNTHETIC", 10, 0.9, "synthetic"), status="SERVICEABLE")
    b = aircraft(prov("FILE:fleet", 0, 1.0, "external"), status="DEGRADED", fuel=60.0)
    state = fuse([batch("a", a), batch("b", b)], NOW)
    rec = state.entities["aircraft"][0]
    p = rec.provenance  # type: ignore[attr-defined]
    assert p.source == "FILE:fleet" and p.data_label == "external" and p.ingested_at == NOW
    assert p.confidence == 1.0 and p.observed_at == NOW
    assert set(state.meta["aircraft"]["A-1"].sources) == {"SYNTHETIC", "FILE:fleet"}
    # A record whose winning fields are all synthetic stays synthetic even if an external source
    # also reported it.
    weak = aircraft(prov("FILE:fleet", 30, 0.5, "external"), status="DEGRADED")
    kept = fuse([batch("a", a), batch("b", weak)], NOW).entities["aircraft"][0]
    assert kept.provenance.data_label == "synthetic"  # type: ignore[attr-defined]


def test_pin_is_the_only_way_winners_differ_within_a_record() -> None:
    # Provenance is per record, so one source wins every field of a record; only a pin splits it.
    a = aircraft(prov("SYNTHETIC", 20, 0.95), fuel=50.0)
    b = aircraft(prov("SYNTHETIC_SECONDARY", 0, 0.99), fuel=90.0)
    plain = fuse([batch("a", a), batch("b", b)], NOW).meta["aircraft"]["A-1"]
    assert plain.source == "SYNTHETIC_SECONDARY" and plain.field_sources == {}  # 0.693 > 0.681
    pin = _pin("55.0", fieldname="fuel_state_pct")
    pinned = fuse(
        [batch("a", a), batch("b", b)], NOW, pins={("aircraft", "A-1", "fuel_state_pct"): pin}
    ).meta["aircraft"]["A-1"]
    assert pinned.field_sources == {"fuel_state_pct": "PIN:duty.officer"}
    assert pinned.confidence == 0.99  # min over winners: 0.99 (feed) and 1.0 (pin)


def test_synthetic_beats_open_when_labels_mix() -> None:
    a = aircraft(prov("SYNTHETIC", 0, 1.0, "synthetic"))
    b = aircraft(prov("OPEN_METEO", 0, 1.0, "open"), fuel=79.9)
    rec = fuse([batch("a", a), batch("b", b)], NOW).entities["aircraft"][0]
    assert rec.provenance.data_label == "synthetic"  # type: ignore[attr-defined]


def test_duplicate_records_from_one_source_keep_the_newer_observation() -> None:
    older = aircraft(prov("SYNTHETIC", 40), fuel=10.0)
    newer = aircraft(prov("SYNTHETIC", 5), fuel=20.0)
    state = fuse([batch("a", older, newer)], NOW)
    assert state.entities["aircraft"][0].fuel_state_pct == 20.0  # type: ignore[attr-defined]
    assert state.report.counts.duplicates_dropped == 1
    state2 = fuse([batch("a", newer, older)], NOW)  # order must not matter
    assert state2.entities["aircraft"][0].fuel_state_pct == 20.0  # type: ignore[attr-defined]


def test_unknown_or_unfused_group_is_rejected() -> None:
    with pytest.raises(ValueError, match="not fused"):
        fuse([RecordBatch("x", {"bases": []})], NOW)


# --------------------------------------------------------------------------------------- pins
def _pin(
    value: str, group: str = "aircraft", entity: str = "A-1", fieldname: str = "status"
) -> Pin:
    return Pin(
        conflict_id=conflict_id(group, entity, fieldname), group=group, entity_id=entity,
        field=fieldname, value=value, actor="duty.officer", reason="checked on the apron",
        chosen_source=None, ts=NOW,
    )


def test_pin_overrides_every_source_and_is_reported_as_pinned() -> None:
    a = aircraft(prov("SYNTHETIC", 5, 1.0), status="SERVICEABLE")
    b = aircraft(prov("SYNTHETIC_SECONDARY", 5, 0.9), status="DEGRADED")
    pin = _pin("UNSERVICEABLE")
    state = fuse([batch("a", a), batch("b", b)], NOW, pins={("aircraft", "A-1", "status"): pin})
    rec = state.entities["aircraft"][0]
    assert rec.status is AircraftStatus.UNSERVICEABLE  # type: ignore[attr-defined]
    c = one(state)
    assert c.status == "pinned" and c.reason is FusionReason.PINNED_BY_HUMAN
    assert c.resolved_source == "PIN:duty.officer" and c.pin == pin
    assert not any(x.selected for x in c.candidates)  # no source was selected
    meta = state.meta["aircraft"]["A-1"]
    assert meta.pinned_fields == ["status"] and "status" not in meta.stale_fields
    assert state.report.counts.conflicts_pinned == 1 and state.report.counts.conflicts_open == 0


def test_pin_makes_a_stale_field_fresh() -> None:
    stale = aircraft(prov("SYNTHETIC", 500), status="SERVICEABLE")
    state = fuse([batch("a", stale)], NOW, pins={("aircraft", "A-1", "status"): _pin("DEGRADED")})
    assert "status" not in state.meta["aircraft"]["A-1"].stale_fields
    # other fields are still stale
    assert "fuel_state_pct" in state.meta["aircraft"]["A-1"].stale_fields


def test_conflict_id_is_stable_and_distinguishes_fields() -> None:
    assert conflict_id("aircraft", "A-1", "status") == conflict_id("aircraft", "A-1", "status")
    other = conflict_id("aircraft", "A-1", "fuel_state_pct")
    assert conflict_id("aircraft", "A-1", "status") != other
    assert conflict_id("aircraft", "A-1", "status").startswith("cf_")


# ----------------------------------------------------------------------------- determinism
def test_fusion_is_deterministic_for_identical_inputs() -> None:
    a = aircraft(prov("SYNTHETIC", 10, 0.9), status="SERVICEABLE", fuel=70.0)
    b = aircraft(prov("SYNTHETIC_SECONDARY", 5, 0.8), status="DEGRADED", fuel=95.0)
    first = fuse([batch("a", a), batch("b", b)], NOW).report.model_dump_json()
    second = fuse([batch("a", a), batch("b", b)], NOW).report.model_dump_json()
    assert first == second
    swapped = fuse([batch("b", b), batch("a", a)], NOW).report
    assert [c.model_dump() for c in swapped.conflicts] == [
        c.model_dump() for c in fuse([batch("a", a), batch("b", b)], NOW).report.conflicts
    ]
