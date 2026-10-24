"""Действующая конфигурация доменных знаний (SPR4-00): файлы репозитория или опубликованная версия в PostgreSQL.

Исходная конфигурация — backend/config/sectors/*.yaml. Аналитик публикует новую версию через админку:
она сохраняется в domain_config_versions, ревизия domain_config_rev в app_state растет, и каждый процесс
(экземпляры API, воркер) не позже чем через RECHECK_SECONDS применяет ее у себя без деплоя.
Откат — публикация копии прежней версии: история не теряется.
"""

import logging
import threading
import time
from pathlib import Path

from sqlalchemy import select

from app import database
from app.domain_config import runtime
from app.domain_config.validate import read_dir, validate_texts
from app.models import DomainConfigVersion

logger = logging.getLogger("app.domain_config")

FILES = Path(__file__).resolve().parents[2] / "config" / "sectors"
REV_KEY = "domain_config_rev"
RECHECK_SECONDS = 5.0
_lock = threading.Lock()
_checked = {"at": 0.0, "rev": None}


class ConfigError(Exception):
    def __init__(self, issues: list):
        super().__init__("Конфигурация не прошла проверку")
        self.issues = issues


def file_texts() -> dict[str, str]:
    return read_dir(FILES)


def load_files() -> str:
    """Исходная конфигурация из репозитория (импорт модулей, тесты). Ошибка — исключение: сервис не стартует с битыми словарями."""
    docs, issues = validate_texts(file_texts())
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise ConfigError(errors)
    return runtime.apply(docs)


def _published(db) -> DomainConfigVersion | None:
    return db.scalar(select(DomainConfigVersion).where(DomainConfigVersion.status == "published")
                     .order_by(DomainConfigVersion.id.desc()).limit(1))


def due() -> bool:
    """Пора сверить ревизию (без обращения к базе): проверка в каждом запросе API стоит один вызов time."""
    return time.monotonic() - _checked["at"] >= RECHECK_SECONDS


def refresh(force: bool = False) -> bool:
    """Применить опубликованную версию, если она сменилась. Дешево: ревизия читается не чаще RECHECK_SECONDS."""
    now = time.monotonic()
    if not force and now - _checked["at"] < RECHECK_SECONDS:
        return False
    with _lock:
        _checked["at"] = now
        rev = database.state(REV_KEY)
        if not force and rev == _checked["rev"]:
            return False
        with database.session() as db:
            row = _published(db)
            texts, version_id = (row.payload["texts"], row.id) if row else (file_texts(), None)
        docs, issues = validate_texts(texts)
        if any(i.level == "error" for i in issues):
            logger.error("published domain config %s is invalid, keeping current", version_id)
            _checked["rev"] = rev
            return False
        changed = runtime.digest(docs) != runtime.signature() or version_id != runtime.version()
        if changed:
            runtime.apply(docs, version_id)
            logger.info("domain config applied version=%s signature=%s", version_id, runtime.signature())
        _checked["rev"] = rev
        return changed


def current_texts() -> tuple[dict[str, str], int | None]:
    with database.session() as db:
        row = _published(db)
        return (row.payload["texts"], row.id) if row else (file_texts(), None)


def publish(texts: dict[str, str], by: str, note: str = "") -> dict:
    """Проверить и опубликовать версию. Ошибки валидатора — ConfigError (версия не сохраняется)."""
    docs, issues = validate_texts(texts)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise ConfigError(errors)
    with database.session() as db:
        db.execute(select(DomainConfigVersion.id).with_for_update().limit(1))
        for old in db.scalars(select(DomainConfigVersion).where(DomainConfigVersion.status == "published")):
            old.status = "archived"
        row = DomainConfigVersion(status="published", created_by=by, note=note[:300], signature=runtime.digest(docs),
                                  payload={"texts": texts, "warnings": [i.as_dict() for i in issues]})
        db.add(row)
        db.flush()
        database.set_state(REV_KEY, row.id, db)
        result = {"id": row.id, "signature": row.signature, "warnings": [i.as_dict() for i in issues]}
    refresh(force=True)
    return result


def rollback(version_id: int, by: str) -> dict:
    with database.session() as db:
        row = db.get(DomainConfigVersion, version_id)
        if row is None:
            raise LookupError(version_id)
        texts = row.payload["texts"]
    return publish(texts, by, f"Откат к версии {version_id}")


def reset_to_files(by: str) -> dict:
    return publish(file_texts(), by, "Возврат к конфигурации из репозитория")


def versions(limit: int = 30) -> list[dict]:
    with database.session() as db:
        rows = db.scalars(select(DomainConfigVersion).order_by(DomainConfigVersion.id.desc()).limit(limit))
        return [{"id": r.id, "status": r.status, "created_by": r.created_by, "note": r.note, "signature": r.signature,
                 "created_at": r.created_at.isoformat()} for r in rows]
