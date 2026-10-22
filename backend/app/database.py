"""SQLAlchemy sessions and Alembic schema upgrades for PostgreSQL."""
import re
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from app import config
from app.models import AppState

_ready: set[tuple[str, str]] = set()
_lock = threading.Lock()


def schema() -> str:
    name = config.database_schema()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name):
        raise ValueError("Invalid DATABASE_SCHEMA")
    return name


@lru_cache(maxsize=16)
def _engine(url: str, namespace: str):
    parsed = make_url(url).set(drivername="postgresql+psycopg")
    return create_engine(parsed, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         connect_args={"connect_timeout": 5,
                                       "options": f"-c search_path={namespace} -c statement_timeout=30000"})


def engine():
    return _engine(config.database_url(), schema())


def alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def migrate() -> None:
    key = (config.database_url(), schema())
    if key in _ready:
        return
    with _lock:
        if key in _ready:
            return
        with engine().begin() as conn:
            conn.execute(select(func.pg_advisory_xact_lock(72810401)))
            conn.execute(CreateSchema(schema(), if_not_exists=True))
            cfg = alembic_config()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        _ready.add(key)


@contextmanager
def session():
    migrate()
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        yield db


def state(key: str, db: Session | None = None):
    if db is None:
        with session() as db:
            return state(key, db)
    row = db.get(AppState, key)
    return row.payload if row else None


def set_state(key: str, value, db: Session) -> None:
    stmt = insert(AppState).values(key=key, payload=value)
    db.execute(stmt.on_conflict_do_update(index_elements=[AppState.key],
               set_={"payload": stmt.excluded.payload, "updated_at": func.now()}))
    db.expire_all()


def health() -> None:
    with session() as db:
        db.execute(select(1))


if __name__ == "__main__":
    migrate()
    print("Alembic: PostgreSQL schema is up to date")
