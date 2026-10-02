"""SQLModel tables: one per entity (DATA_MODEL §3). Each stores the entity as JSON plus the keys
needed to look it up; typed filter columns are added when an endpoint needs them (decision D-21).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel


class ScenarioRow(SQLModel, table=True):
    __tablename__ = "scenario"

    id: str = Field(primary_key=True)  # "sc_" + first 10 hex of the canonical-JSON SHA-256
    name: str
    seed: int
    horizon_min: int
    data_label: str
    content_sha256: str
    meta: dict[str, Any] = Field(sa_type=JSON)
    counts: dict[str, int] = Field(sa_type=JSON)


class EntityRow(SQLModel):
    """Shared shape for per-entity tables (not a table itself)."""

    pk: int | None = Field(default=None, primary_key=True)
    scenario_id: str = Field(index=True)
    entity_id: str = Field(index=True)
    data: dict[str, Any] = Field(sa_type=JSON)


class BaseRow(EntityRow, table=True):
    __tablename__ = "base"


class AircraftTypeRow(EntityRow, table=True):
    __tablename__ = "aircraft_type"


class AircraftRow(EntityRow, table=True):
    __tablename__ = "aircraft"


class CrewMemberRow(EntityRow, table=True):
    __tablename__ = "crew_member"


class LoadoutRow(EntityRow, table=True):
    __tablename__ = "loadout"


class WeaponStockRow(EntityRow, table=True):
    __tablename__ = "weapon_stock"


class MissionRow(EntityRow, table=True):
    __tablename__ = "mission"


class ThreatRow(EntityRow, table=True):
    __tablename__ = "threat"


class AirspaceZoneRow(EntityRow, table=True):
    __tablename__ = "airspace_zone"


class WeatherRow(EntityRow, table=True):
    __tablename__ = "weather"


class AirfieldRow(EntityRow, table=True):
    __tablename__ = "alternate_airfield"


class MaintenanceRecordRow(EntityRow, table=True):
    __tablename__ = "maintenance_record"


class EventRow(EntityRow, table=True):
    __tablename__ = "event"


# Plan-side tables exist now; they are first written in Phases 4-5.
class PlanRow(EntityRow, table=True):
    __tablename__ = "plan"


class ProposalRow(EntityRow, table=True):
    __tablename__ = "proposal"


class AuditEntryRow(EntityRow, table=True):
    __tablename__ = "audit_entry"
