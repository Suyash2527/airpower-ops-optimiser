"""Audit log: append-only, ordered, scoped per scenario (DATA_MODEL AuditEntry)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlmodel import Session

from app.audit import log as audit
from app.core.db import init_db, make_engine


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
        yield s


def _add(session: Session, sid: str, who: str, obj: str) -> audit.AuditEntry:
    return audit.append(
        session, sid, actor=who, action="test.action", object_type="thing", object_id=obj,
        details={"n": 1},
    )


def test_entries_get_sequential_ids_and_come_back_in_order(session: Session) -> None:
    ids = [_add(session, "sc_1", f"u{i}", "o").id for i in range(3)]
    assert ids == ["au_00001", "au_00002", "au_00003"]
    session.commit()
    assert [e.actor for e in audit.list_entries(session, "sc_1")] == ["u0", "u1", "u2"]


def test_entries_are_scoped_by_scenario_object_and_limit(session: Session) -> None:
    _add(session, "sc_1", "a", "x")
    _add(session, "sc_1", "b", "y")
    _add(session, "sc_2", "c", "x")
    session.commit()
    assert [e.actor for e in audit.list_entries(session, "sc_1", object_id="y")] == ["b"]
    assert [e.actor for e in audit.list_entries(session, "sc_2")] == ["c"]
    assert len(audit.list_entries(session, "sc_1", limit=1)) == 1
    assert audit.list_entries(session, "sc_2")[0].id == "au_00001"  # numbering is per scenario


def test_the_log_exposes_no_way_to_change_or_remove_entries() -> None:
    public = {n for n in dir(audit) if not n.startswith("_")}
    assert not {n for n in public if n.startswith(("update", "delete", "remove", "clear"))}


def test_entry_timestamp_is_timezone_aware_utc(session: Session) -> None:
    entry = _add(session, "sc_1", "a", "x")
    assert entry.ts.utcoffset() is not None and entry.ts.utcoffset().total_seconds() == 0
