"""Real PostgreSQL migration and transaction regressions."""
import hashlib
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, MetaData, Table, Text, insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema

from app import database
from app.models import Base, Event, Feedback


def legacy_schema(checksum=None):
    source = Path(__file__).with_name("fixtures") / "legacy_schema.sql"
    sql = source.read_text(encoding="utf-8")
    marker = Table("schema_migrations", MetaData(), Column("version", Text, primary_key=True),
                   Column("checksum", Text, nullable=False))
    with database.engine().begin() as conn:
        conn.execute(CreateSchema(database.schema(), if_not_exists=True))
        conn.exec_driver_sql(sql)
        marker.create(conn)
        conn.execute(insert(marker).values(version="001_initial.sql", checksum=checksum or hashlib.sha256(sql.encode()).hexdigest()))
        conn.execute(insert(Event).values(kind="before_alembic", payload={"preserve": [1, "original"]}))


def test_legacy_adoption_keeps_records_and_removes_custom_versioning():
    legacy_schema()
    database.migrate()
    with database.session() as db:
        assert db.scalar(select(Event.payload)) == {"preserve": [1, "original"]}
        assert "schema_migrations" not in inspect(db.connection()).get_table_names()
        assert MigrationContext.configure(db.connection(), opts={"version_table_schema": database.schema()}).get_current_revision() == "0006"


def test_unknown_legacy_schema_is_not_stamped():
    legacy_schema(checksum="unexpected")
    with pytest.raises(RuntimeError, match="Unknown legacy"):
        database.migrate()
    with database.engine().connect() as conn:
        assert conn.scalar(select(Event.payload)) == {"preserve": [1, "original"]}
        assert "schema_migrations" in inspect(conn).get_table_names()


def test_alembic_upgrade_matches_orm_and_downgrade_roundtrip():
    database.migrate()
    with database.engine().connect() as conn:
        context = MigrationContext.configure(conn, opts={"version_table_schema": database.schema(),
            "include_object": lambda obj, name, type_, reflected, compare_to: name != "alembic_version"})
        assert compare_metadata(context, Base.metadata) == []
    cfg = database.alembic_config()
    command.downgrade(cfg, "base")
    with database.engine().connect() as conn:
        assert set(inspect(conn).get_table_names()) == {"alembic_version"}
    command.upgrade(cfg, "head")
    with database.session() as db:
        db.add(Event(kind="after_upgrade", payload={"ok": True}))
    assert len(database.state("missing") or []) == 0


def test_orm_foreign_key_failure_rolls_back_entire_session():
    with pytest.raises(IntegrityError):
        with database.session() as db:
            db.add(Event(kind="must_roll_back", payload={"ok": False}))
            db.flush()
            db.add(Feedback(insight_id="nonexistent", payload={"rating": 1}))
    with database.session() as db:
        assert db.scalar(select(Event.id)) is None
