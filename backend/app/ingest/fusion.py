"""Multi-source fusion (ALGORITHMS §1). Pure and deterministic: no DB, no network, no clock.

For every record (matched by its stable key) and every field with more than one observation:

1. Observations older than `max_age_min[group]` are *stale*. If at least one fresh observation
   exists, stale ones are discarded from the contest; if none does, the best stale one is kept and
   flagged (the planner must then be conservative, see `effective_aircraft_status`).
2. score = source_trust * confidence * exp(-age / tau). Highest score wins; ties go to the higher
   trust, then to the source name (alphabetical), so the result never depends on input order.
3. Losers whose value differs *materially* from the winner are kept as a `Conflict`, with every
   candidate's numbers and a reason code. A human can pin a value (`Pin`); a pin beats all sources.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.ingest.models import (
    FUSED_GROUPS,
    Candidate,
    Conflict,
    FusionConfig,
    FusionCounts,
    FusionReason,
    FusionReport,
    GroupCounts,
    Pin,
    RecordBatch,
    RecordFusion,
    SourceSummary,
    StaleItem,
)
from app.models.entities import Aircraft, Provenance
from app.models.enums import AircraftStatus
from app.models.scenario import GROUPS, KEY_FIELDS, record_key

PIN_SOURCE_PREFIX = "PIN:"
PinIndex = Mapping[tuple[str, str, str], Pin]  # (group, entity_id, field) -> pin


@dataclass(frozen=True)
class FusedState:
    entities: dict[str, list[BaseModel]]
    meta: dict[str, dict[str, RecordFusion]]
    report: FusionReport


@dataclass(frozen=True)
class _Obs:
    """One source's view of one record (all fields share the same provenance)."""

    source: str
    record: dict[str, Any]
    prov: Provenance
    trust: float
    age_min: float
    score: float
    stale: bool


# ----------------------------------------------------------------------------- comparisons
def materially_different(
    a: Any, b: Any, abs_tol: float, rel_tol: float, coord_tol: float, leaf: str = ""
) -> bool:
    """Tolerance-aware inequality over JSON-like values. `lat`/`lon` leaves use an absolute
    tolerance in degrees; other numbers use max(abs_tol, rel_tol * magnitude)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a != b)
    if isinstance(a, int | float) and isinstance(b, int | float):
        if leaf in ("lat", "lon"):
            return abs(a - b) > coord_tol
        return abs(a - b) > max(abs_tol, rel_tol * max(abs(a), abs(b)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() != b.keys() or any(
            materially_different(a[k], b[k], abs_tol, rel_tol, coord_tol, k) for k in a
        )
    if isinstance(a, list) and isinstance(b, list):
        return len(a) != len(b) or any(
            materially_different(x, y, abs_tol, rel_tol, coord_tol, leaf)
            for x, y in zip(a, b, strict=True)
        )
    return bool(a != b)


def conflict_id(group: str, entity_id: str, fieldname: str) -> str:
    digest = hashlib.sha1(f"{group}|{entity_id}|{fieldname}".encode()).hexdigest()
    return f"cf_{digest[:10]}"


def _fmt(value: Any, limit: int = 48) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _minutes(delta_seconds: float) -> float:
    return round(max(0.0, delta_seconds) / 60.0, 3)


def _merge_label(labels: set[str]) -> str:
    """Never present synthetic as real: any external -> external, else synthetic beats open."""
    for label in ("external", "synthetic", "open"):
        if label in labels:
            return label
    return "synthetic"


# --------------------------------------------------------------------------------- the engine
def fuse(
    batches: Sequence[RecordBatch],
    now: datetime,
    config: FusionConfig | None = None,
    pins: PinIndex | None = None,
) -> FusedState:
    config = config or FusionConfig()
    pins = pins or {}
    observed, order, duplicates = _collect(batches, now, config)

    entities: dict[str, list[BaseModel]] = {}
    meta: dict[str, dict[str, RecordFusion]] = {}
    conflicts: list[Conflict] = []
    counts = FusionCounts(duplicates_dropped=duplicates)
    by_group: dict[str, GroupCounts] = {}
    source_records: dict[str, int] = {}
    source_wins: dict[str, int] = {}

    for group in FUSED_GROUPS:
        if group not in order:
            continue
        entities[group], meta[group] = [], {}
        gc = by_group.setdefault(group, GroupCounts())
        for key in order[group]:
            per_source = observed[group][key]
            entity, rec_meta, found, wins = _fuse_record(
                group, key, per_source, now, config, pins, counts
            )
            entities[group].append(entity)
            meta[group][key] = rec_meta
            conflicts.extend(found)
            for src in per_source:
                source_records[src] = source_records.get(src, 0) + 1
            for src, n in wins.items():
                source_wins[src] = source_wins.get(src, 0) + n
            gc.records += 1
            gc.multi_source += len(per_source) > 1
            gc.conflicts += len(found)
            gc.stale_records += rec_meta.stale

    counts.records = sum(g.records for g in by_group.values())
    counts.multi_source = sum(g.multi_source for g in by_group.values())
    counts.single_source = counts.records - counts.multi_source
    counts.conflicts = len(conflicts)
    counts.conflicts_pinned = sum(c.status == "pinned" for c in conflicts)
    counts.conflicts_open = counts.conflicts - counts.conflicts_pinned
    counts.stale_records = sum(g.stale_records for g in by_group.values())
    counts.stale_fields = sum(len(m.stale_fields) for g in meta.values() for m in g.values())
    rejected = [r for b in batches for r in b.rejected]
    counts.rejected_records = len(rejected)

    order_index = {g: i for i, g in enumerate(FUSED_GROUPS)}
    conflicts.sort(key=lambda c: (order_index[c.group], c.entity_id, c.field))
    report = FusionReport(
        now=now,
        sources=[
            SourceSummary(
                source=s, trust=config.trust_for(s), records=source_records[s],
                fields_won=source_wins.get(s, 0),
            )
            for s in sorted(source_records)
        ],
        counts=counts, by_group=by_group, conflicts=conflicts,
        stale=_stale_items(meta, config), rejected=rejected, config=config,
    )
    return FusedState(entities=entities, meta=meta, report=report)


def _collect(
    batches: Sequence[RecordBatch], now: datetime, config: FusionConfig
) -> tuple[dict[str, dict[str, dict[str, _Obs]]], dict[str, list[str]], int]:
    """group -> key -> source -> observation, plus first-seen key order and duplicates dropped."""
    observed: dict[str, dict[str, dict[str, _Obs]]] = {}
    order: dict[str, list[str]] = {}
    duplicates = 0
    for batch in batches:
        for group, records in batch.records.items():
            if group not in FUSED_GROUPS:
                raise ValueError(f"group {group!r} is not fused (expected one of {FUSED_GROUPS})")
            for entity in records:
                rec = entity.model_dump(mode="json")
                prov: Provenance = entity.provenance  # type: ignore[attr-defined]
                key = record_key(group, rec)
                age = _minutes((now - prov.observed_at).total_seconds())
                trust = config.trust_for(prov.source)
                obs = _Obs(
                    source=prov.source, record=rec, prov=prov, trust=trust, age_min=age,
                    score=trust * prov.confidence * math.exp(-age / config.tau_for(group)),
                    stale=age > config.max_age_min[group],
                )
                slot = observed.setdefault(group, {}).setdefault(key, {})
                if key not in order.setdefault(group, []) and not slot:
                    order[group].append(key)
                prior = slot.get(prov.source)
                if prior is not None:
                    duplicates += 1  # same source, same record twice: keep the newer observation
                    if prior.prov.observed_at > prov.observed_at:
                        continue
                slot[prov.source] = obs
    return observed, order, duplicates


def _fuse_record(
    group: str,
    key: str,
    per_source: dict[str, _Obs],
    now: datetime,
    config: FusionConfig,
    pins: PinIndex,
    counts: FusionCounts,
) -> tuple[BaseModel, RecordFusion, list[Conflict], dict[str, int]]:
    obs_list = sorted(per_source.values(), key=lambda o: o.source)
    first = obs_list[0].record
    skip = {"provenance", *KEY_FIELDS[group]}
    fields = [f for f in GROUPS[group].model_fields if f not in skip]
    data: dict[str, Any] = {f: first[f] for f in KEY_FIELDS[group]}
    conflicts: list[Conflict] = []
    wins: dict[str, int] = {}
    winners: dict[str, _Winner] = {}

    for name in fields:
        winner, conflict = _fuse_field(group, key, name, obs_list, now, config, pins, counts)
        data[name] = winner.value
        winners[name] = winner
        wins[winner.source] = wins.get(winner.source, 0) + 1
        if conflict is not None:
            conflicts.append(conflict)

    record_source = min(wins, key=lambda s: (-wins[s], -_trust(s, config), s))
    stale_fields = {n: w.age_min for n, w in winners.items() if w.stale}
    oldest = max(winners.values(), key=lambda w: (w.age_min, w.source))
    prov = Provenance(
        source=record_source,
        observed_at=min(w.observed_at for w in winners.values()),
        ingested_at=now,
        confidence=min(w.confidence for w in winners.values()),
        data_label=_merge_label({w.data_label for w in winners.values()}),  # type: ignore[arg-type]
    )
    data["provenance"] = prov.model_dump(mode="json")
    entity = GROUPS[group].model_validate(data)
    rec_meta = RecordFusion(
        group=group, entity_id=key, source=record_source, sources=sorted(per_source),
        observed_at=prov.observed_at, confidence=prov.confidence,
        staleness_min=oldest.age_min, stale=bool(stale_fields), stale_fields=stale_fields,
        conflict_fields=[c.field for c in conflicts],
        pinned_fields=[n for n, w in winners.items() if w.pinned],
        field_sources={n: w.source for n, w in winners.items() if w.source != record_source},
    )
    return entity, rec_meta, conflicts, wins


def _trust(source: str, config: FusionConfig) -> float:
    return 1.0 if source.startswith(PIN_SOURCE_PREFIX) else config.trust_for(source)


@dataclass(frozen=True)
class _Winner:
    source: str
    value: Any
    observed_at: datetime
    confidence: float
    data_label: str
    age_min: float
    stale: bool
    pinned: bool


def _fuse_field(
    group: str,
    key: str,
    name: str,
    obs_list: list[_Obs],
    now: datetime,
    config: FusionConfig,
    pins: PinIndex,
    counts: FusionCounts,
) -> tuple[_Winner, Conflict | None]:
    abs_tol, rel_tol = config.tolerance_for(group, name)
    coord = config.coordinate_abs_tol_deg

    def differs(a: Any, b: Any) -> bool:
        return materially_different(a, b, abs_tol, rel_tol, coord)

    fresh = [o for o in obs_list if not o.stale]
    pool = fresh or obs_list
    ranked = sorted(pool, key=lambda o: (-o.score, -o.trust, o.source))
    best = ranked[0]
    pin = pins.get((group, key, name))

    if len(obs_list) > 1:
        counts.fields_compared += 1
        counts.discarded_stale_observations += len(obs_list) - len(pool)

    resolved = best.record[name] if pin is None else pin.value
    # Observations (stale-discarded ones included) that disagree with the resolved value.
    rivals = [
        o for o in obs_list
        if (pin is not None or o is not best) and differs(o.record[name], resolved)
    ]
    if len(obs_list) > 1 and not rivals:
        counts.fields_agree += 1

    if pin is not None:
        winner = _Winner(
            source=f"{PIN_SOURCE_PREFIX}{pin.actor}", value=pin.value, observed_at=now,
            confidence=1.0, data_label=best.prov.data_label, age_min=0.0, stale=False, pinned=True,
        )
    else:
        winner = _Winner(
            source=best.source, value=best.record[name], observed_at=best.prov.observed_at,
            confidence=best.prov.confidence, data_label=best.prov.data_label,
            age_min=best.age_min, stale=best.stale, pinned=False,
        )
    if not rivals:
        return winner, None

    cid = conflict_id(group, key, name)
    reason = _reason(pin, fresh, rivals, pool)
    candidates = [
        Candidate(
            source=o.source, value=o.record[name], observed_at=o.prov.observed_at,
            confidence=o.prov.confidence, trust=o.trust, age_min=o.age_min,
            score=round(o.score, 6), stale=o.stale, selected=pin is None and o is best,
            discarded_stale=o not in pool,
        )
        for o in sorted(obs_list, key=lambda o: (-o.score, -o.trust, o.source))
    ]
    conflict = Conflict(
        id=cid, group=group, entity_id=key, field=name,
        status="pinned" if pin else "open", reason=reason, resolved_value=winner.value,
        resolved_source=winner.source, candidates=candidates, pin=pin,
        explanation=_explain(group, key, name, winner, candidates, reason),
    )
    return winner, conflict


def _reason(
    pin: Pin | None, fresh: list[_Obs], rivals: list[_Obs], pool: list[_Obs]
) -> FusionReason:
    if pin is not None:
        return FusionReason.PINNED_BY_HUMAN
    if not fresh:
        return FusionReason.ALL_OBSERVATIONS_STALE
    if all(r not in pool for r in rivals):
        return FusionReason.STALE_OBSERVATION_DISCARDED
    return FusionReason.HIGHEST_SCORE


def _explain(
    group: str, key: str, name: str, winner: _Winner, candidates: list[Candidate],
    reason: FusionReason,
) -> str:
    seen = "; ".join(
        f"{c.source} says {_fmt(c.value)} (score {c.score:.2f}"
        f"{', stale' if c.stale else ''}{', discarded' if c.discarded_stale else ''})"
        for c in candidates
    )
    how = {
        FusionReason.HIGHEST_SCORE: "highest trust x confidence x recency score",
        FusionReason.STALE_OBSERVATION_DISCARDED: "the disagreeing report was stale and discarded",
        FusionReason.ALL_OBSERVATIONS_STALE: "best score among stale reports; treat with caution",
        FusionReason.PINNED_BY_HUMAN: "pinned by a human operator",
    }[reason]
    return (
        f"{group} {key} / {name}: {seen}. Kept {_fmt(winner.value)} from {winner.source} "
        f"because {how}."
    )


def _stale_items(
    meta: dict[str, dict[str, RecordFusion]], config: FusionConfig
) -> list[StaleItem]:
    return [
        StaleItem(
            group=g, entity_id=k, source=m.source, staleness_min=m.staleness_min,
            max_age_min=config.max_age_min[g], fields=sorted(m.stale_fields),
        )
        for g in FUSED_GROUPS if g in meta
        for k, m in meta[g].items() if m.stale
    ]


# ------------------------------------------------------------------- planner-facing helpers
def effective_aircraft_status(aircraft: Aircraft, meta: RecordFusion | None) -> AircraftStatus:
    """ALGORITHMS §1.4: a SERVICEABLE status whose winning observation is stale is treated as
    DEGRADED for risk purposes. The stored value is never rewritten."""
    if (
        meta is not None
        and "status" in meta.stale_fields
        and aircraft.status is AircraftStatus.SERVICEABLE
    ):
        return AircraftStatus.DEGRADED
    return aircraft.status

