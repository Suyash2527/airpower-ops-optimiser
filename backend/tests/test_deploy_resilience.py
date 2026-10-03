"""Deployment resilience (D-70): hosted-Postgres URLs and presets that survive a reset database."""

from sqlmodel import Session

from app.core.config import database_url
from app.core.db import init_db, make_engine
from app.models import store
from app.sim.generate import generate_scenario
from app.sim.presets import PRESETS


def test_database_url_prefers_explicit_then_hosting_vars(monkeypatch) -> None:
    for k in ("AIRPOWER_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL", "VERCEL"):
        monkeypatch.delenv(k, raising=False)
    assert database_url() == "sqlite:///./airpower.db"
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:p@h/db")
    assert database_url() == "postgresql+psycopg://u:p@h/db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h2/db?sslmode=require")
    assert database_url() == "postgresql+psycopg://u:p@h2/db?sslmode=require"
    monkeypatch.setenv("AIRPOWER_DATABASE_URL", "sqlite:///x.db")
    assert database_url() == "sqlite:///x.db"


def test_vercel_without_database_falls_back_to_tmp_sqlite(monkeypatch) -> None:
    for k in ("AIRPOWER_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert database_url() == "sqlite:////tmp/airpower.db"


def test_known_preset_is_rebuilt_in_an_empty_database() -> None:
    engine = make_engine("sqlite://")
    init_db(engine)
    demo = generate_scenario(PRESETS["demo"])
    sid = store.scenario_id_for(demo)
    with Session(engine) as session:
        rebuilt = store.load_scenario_rows(session, sid)
        assert rebuilt is not None
        assert rebuilt.to_canonical_json() == demo.to_canonical_json()
        assert store.load_scenario_rows(session, "sc_doesnotexist") is None
