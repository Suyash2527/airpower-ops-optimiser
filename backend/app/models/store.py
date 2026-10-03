"""Persist a ScenarioFile as rows and rebuild it (the snapshot) from the rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, select

from app.models import tables
from app.models.entities import Model
from app.models.scenario import GROUPS, ScenarioFile, ScenarioMeta, entity_key
from app.sim.scenario_io import scenario_digest

# group name -> table; the lookup key comes from models.scenario.entity_key
_TABLES: dict[str, type[tables.EntityRow]] = {
    "bases": tables.BaseRow,
    "aircraft_types": tables.AircraftTypeRow,
    "aircraft": tables.AircraftRow,
    "crew": tables.CrewMemberRow,
    "loadouts": tables.LoadoutRow,
    "weapon_stocks": tables.WeaponStockRow,
    "missions": tables.MissionRow,
    "threats": tables.ThreatRow,
    "airspace": tables.AirspaceZoneRow,
    "weather": tables.WeatherRow,
    "alternate_airfields": tables.AirfieldRow,
    "maintenance_history": tables.MaintenanceRecordRow,
    "events": tables.EventRow,
}
assert set(_TABLES) == set(GROUPS)


def scenario_id_for(scenario: ScenarioFile) -> str:
    return "sc_" + scenario_digest(scenario)[:10]


def save_scenario_rows(session: Session, scenario: ScenarioFile) -> str:
    """Insert (replacing any previous copy of the same content) and return the scenario id."""
    sid = scenario_id_for(scenario)
    for row_cls in _TABLES.values():
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
    for group, row_cls in _TABLES.items():
        for entity in getattr(scenario, group):
            session.add(
                row_cls(
                    scenario_id=sid, entity_id=entity_key(group, entity),
                    data=entity.model_dump(mode="json"),
                )
            )
    session.commit()
    return sid


def load_scenario_rows(session: Session, scenario_id: str) -> ScenarioFile | None:
    head = session.get(tables.ScenarioRow, scenario_id)
    if head is None:
        # A saved preset can be rebuilt exactly from its params (D-69/D-70), so a database that
        # was reset (e.g. a new serverless instance) still serves it. Unknown ids stay unknown.
        from app.sim.presets import preset_by_id

        preset = preset_by_id().get(scenario_id)
        if preset is None:
            return None
        save_scenario_rows(session, preset)
        head = session.get(tables.ScenarioRow, scenario_id)
    parts: dict[str, Any] = {"scenario": ScenarioMeta.model_validate(head.meta)}
    for group, row_cls in _TABLES.items():
        model_cls: type[Model] = GROUPS[group]
        rows = session.exec(
            select(row_cls).where(row_cls.scenario_id == scenario_id).order_by(row_cls.pk)
        ).all()
        parts[group] = [model_cls.model_validate(r.data) for r in rows]
    return ScenarioFile(**parts)


def list_scenarios(session: Session) -> list[tables.ScenarioRow]:
    return list(session.exec(select(tables.ScenarioRow).order_by(tables.ScenarioRow.id)).all())
