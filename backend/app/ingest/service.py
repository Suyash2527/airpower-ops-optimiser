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
from app.models.entities import Event
from app.models.scenario import ScenarioFile
from app.sim.events import apply_event


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


def live_events(session: Session, scenario_id: str) -> list[Event]:
    rows = session.exec(
        select(tables.LiveEventRow)
        .where(tables.LiveEventRow.scenario_id == scenario_id)
        .order_by(tables.LiveEventRow.pk)  # type: ignore[arg-type]
    ).all()
    return [Event.model_validate(r.data) for r in rows]


def add_event(session: Session, scenario_id: str, event: Event) -> None:
    session.add(tables.LiveEventRow(
        scenario_id=scenario_id, entity_id=event.id, data=event.model_dump(mode="json")
    ))


def current_scenario(
    session: Session, scenario_id: str, extra: tuple[Event, ...] = ()
) -> ScenarioFile | None:
    """The stored scenario with every injected event applied in order (plus `extra`, for a dry
    run before an event is stored)."""
    scenario = store.load_scenario_rows(session, scenario_id)
    if scenario is None:
        return None
    for event in [*live_events(session, scenario_id), *extra]:
        scenario = apply_event(scenario, event)
    return scenario


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
    scenario = current_scenario(session, scenario_id)
    if scenario is None:
        return None
    stored = load_pins(session, scenario_id)
    n_events = len(live_events(session, scenario_id))
    index = {(p.group, p.entity_id, p.field): p for p in [*stored, *extra_pins]}
    now = scenario.scenario.t0 + timedelta(minutes=now_min)
    batches = [a.fetch() for a in build_adapters(scenario, secondary)]
    state = fuse(batches, now, pins=index)
    state.report.scenario_id = scenario_id
    state.report.data_label = scenario.scenario.data_label
    state.report.now_min = now_min
    state.report.secondary_source_enabled = secondary
    state.report.state_version = len(stored) + n_events
    fused = scenario.model_copy(update=dict(state.entities))
    return FusedSnapshot(
        scenario=fused, meta=state.meta, report=state.report,
        state_version=len(stored) + n_events,
    )
