"""Persist a ScenarioFile as rows and rebuild it (the snapshot) from the rows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, select

from app.models import tables
from app.models.entities import Model
from app.models.scenario import GROUPS, ScenarioFile, ScenarioMeta
from app.sim.scenario_io import scenario_digest

# group name -> table, and how to derive the entity's lookup key
_TABLES: dict[str, tuple[type[tables.EntityRow], Callable[[Any], str]]] = {
    "bases": (tables.BaseRow, lambda e: e.id),
    "aircraft_types": (tables.AircraftTypeRow, lambda e: e.id),
    "aircraft": (tables.AircraftRow, lambda e: e.id),
    "crew": (tables.CrewMemberRow, lambda e: e.id),
    "loadouts": (tables.LoadoutRow, lambda e: e.id),
    "weapon_stocks": (tables.WeaponStockRow, lambda e: f"{e.base_id}:{e.item_type}"),
    "missions": (tables.MissionRow, lambda e: e.id),
    "threats": (tables.ThreatRow, lambda e: e.id),
    "airspace": (tables.AirspaceZoneRow, lambda e: e.id),
    "weather": (tables.WeatherRow, lambda e: f"{e.base_id}:{e.kind.value}:{e.time_min}"),
    "alternate_airfields": (tables.AirfieldRow, lambda e: e.id),
    "maintenance_history": (tables.MaintenanceRecordRow, lambda e: e.id),
    "events": (tables.EventRow, lambda e: e.id),
}
assert set(_TABLES) == set(GROUPS)


def scenario_id_for(scenario: ScenarioFile) -> str:
    return "sc_" + scenario_digest(scenario)[:10]


def save_scenario_rows(session: Session, scenario: ScenarioFile) -> str:
    """Insert (replacing any previous copy of the same content) and return the scenario id."""
    sid = scenario_id_for(scenario)
    for row_cls, _ in _TABLES.values():
        session.exec(delete(row_cls).where(row_cls.scenario_id == sid))  # type: ignore[arg-type]
    session.exec(delete(tables.ScenarioRow).where(tables.ScenarioRow.id == sid))  # type: ignore[arg-type]
    meta = scenario.scenario
    session.add(
        tables.ScenarioRow(
            id=sid, name=meta.name, seed=meta.seed, horizon_min=meta.horizon_min,
            data_label=meta.data_label, content_sha256=scenario_digest(scenario),
            meta=meta.model_dump(mode="json"), counts=scenario.counts(),
        )
    )
    for group, (row_cls, key) in _TABLES.items():
        for entity in getattr(scenario, group):
            session.add(
                row_cls(scenario_id=sid, entity_id=key(entity), data=entity.model_dump(mode="json"))
            )
    session.commit()
    return sid


def load_scenario_rows(session: Session, scenario_id: str) -> ScenarioFile | None:
    head = session.get(tables.ScenarioRow, scenario_id)
    if head is None:
        return None
    parts: dict[str, Any] = {"scenario": ScenarioMeta.model_validate(head.meta)}
    for group, (row_cls, _) in _TABLES.items():
        model_cls: type[Model] = GROUPS[group]
        rows = session.exec(
            select(row_cls).where(row_cls.scenario_id == scenario_id).order_by(row_cls.pk)
        ).all()
        parts[group] = [model_cls.model_validate(r.data) for r in rows]
    return ScenarioFile(**parts)


def list_scenarios(session: Session) -> list[tables.ScenarioRow]:
    return list(session.exec(select(tables.ScenarioRow).order_by(tables.ScenarioRow.id)).all())
