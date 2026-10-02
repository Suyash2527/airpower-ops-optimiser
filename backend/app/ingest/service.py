"""Glue between storage and the pure fusion step: build the adapters for a stored scenario, load
its pins, fuse, and return a snapshot plus report. Nothing here mutates stored scenario rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, select

from app.ingest.adapters import Adapter, SecondarySyntheticAdapter, SyntheticAdapter
from app.ingest.fusion import fuse
from app.ingest.models import FusionReport, Pin, RecordFusion
from app.models import store, tables
from app.models.scenario import ScenarioFile


@dataclass(frozen=True)
class FusedSnapshot:
    scenario: ScenarioFile  # fused groups replaced, reference groups untouched
    meta: dict[str, dict[str, RecordFusion]]
    report: FusionReport
    state_version: int


def load_pins(session: Session, scenario_id: str) -> list[Pin]:
    rows = session.exec(
        select(tables.FusionPinRow)
        .where(tables.FusionPinRow.scenario_id == scenario_id)
        .order_by(tables.FusionPinRow.pk)  # type: ignore[arg-type]
    ).all()
    return [Pin.model_validate(r.data) for r in rows]


def add_pin(session: Session, scenario_id: str, pin: Pin) -> None:
    session.add(
        tables.FusionPinRow(
            scenario_id=scenario_id, entity_id=pin.conflict_id, data=pin.model_dump(mode="json")
        )
    )


def build_adapters(scenario: ScenarioFile, secondary: bool) -> list[Adapter]:
    adapters: list[Adapter] = [SyntheticAdapter(scenario)]
    if secondary:
        adapters.append(SecondarySyntheticAdapter(scenario))
    return adapters


def fused_snapshot(
    session: Session,
    scenario_id: str,
    *,
    now_min: int = 0,
    secondary: bool = True,
    extra_pins: tuple[Pin, ...] = (),
) -> FusedSnapshot | None:
    """Fuse a stored scenario at scenario time `now_min`. `extra_pins` lets a caller dry-run a pin
    before persisting it. Deterministic: same rows, pins and arguments give the same result."""
    scenario = store.load_scenario_rows(session, scenario_id)
    if scenario is None:
        return None
    stored = load_pins(session, scenario_id)
    index = {(p.group, p.entity_id, p.field): p for p in [*stored, *extra_pins]}
    now = scenario.scenario.t0 + timedelta(minutes=now_min)
    batches = [a.fetch() for a in build_adapters(scenario, secondary)]
    state = fuse(batches, now, pins=index)
    state.report.scenario_id = scenario_id
    state.report.data_label = scenario.scenario.data_label
    state.report.now_min = now_min
    state.report.secondary_source_enabled = secondary
    state.report.state_version = len(stored)
    fused = scenario.model_copy(update=dict(state.entities))
    return FusedSnapshot(
        scenario=fused, meta=state.meta, report=state.report, state_version=len(stored)
    )
