"""Общий интерфейс источника новостей (SPR3-02).

Источник отдает сырые записи (RawNews) — заголовок, текст, ссылку и время. Классификация,
дедупликация, сюжеты и сущности одинаковы для всех источников и выполняются в registry/store.
Новый источник — новый адаптер, без правки ядра.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

# Лицензия «только заголовок и лид»: полный текст не хранится, лид не длиннее LEAD_LIMIT символов.
LEAD_LIMIT = 600


@dataclass(frozen=True)
class RawNews:
    title: str
    text: str
    url: str | None
    published_at: str | None
    external_id: str | None = None
    lead: str | None = None  # лид отдельно от тела (ленты агентств): при лицензии «лид» хранится только он


class SourceAdapter(Protocol):
    id: str
    name: str
    kind: str
    trust: float
    license: str
    interval_minutes: int

    def fetch(self, since: datetime | None) -> list[RawNews]: ...

    def enrich(self, raw: RawNews) -> RawNews: ...

    def health(self) -> dict: ...


@dataclass
class Adapter:
    """Основа адаптера: настройки из реестра и учет здоровья (последний успех, ошибка, задержка)."""
    id: str
    name: str
    kind: str
    url: str = ""
    trust: float = 0.8
    license: str = "full"
    interval_minutes: int = 15
    extra: dict = field(default_factory=dict)
    # Источник отдает записи начиная с момента since (лицензированные ленты); RSS отдает последние N всегда —
    # для него since не применяется: даты в лентах бывают задним числом, а дубли и так отсекаются.
    incremental = False
    _last_ok: str | None = field(default=None, init=False, repr=False)
    _last_error: str | None = field(default=None, init=False, repr=False)
    _latency_ms: float | None = field(default=None, init=False, repr=False)

    def fetch(self, since: datetime | None) -> list[RawNews]:
        started = time.perf_counter()
        try:
            items = [self._licensed(r) for r in self._fetch() if not self.incremental or _after(r.published_at, since)]
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            raise
        finally:
            self._latency_ms = round((time.perf_counter() - started) * 1000, 1)
        self._last_ok, self._last_error = datetime.now(timezone.utc).isoformat(timespec="seconds"), None
        return items

    def enrich(self, raw: RawNews) -> RawNews:
        """Дополнить запись (например, полный текст по ссылке); по умолчанию — как есть."""
        return raw

    def health(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "ok": self._last_error is None,
                "last_ok": self._last_ok, "last_error": self._last_error, "latency_ms": self._latency_ms}

    def _fetch(self) -> list[RawNews]:
        raise NotImplementedError

    def _licensed(self, raw: RawNews) -> RawNews:
        if self.license != "lead":
            return raw
        text = raw.lead or raw.text
        lead = text if len(text) <= LEAD_LIMIT else text[:LEAD_LIMIT].rsplit(" ", 1)[0] + "…"
        return RawNews(raw.title, lead, raw.url, raw.published_at, raw.external_id, lead)


def _after(published_at: str | None, since: datetime | None) -> bool:
    if since is None or not published_at:
        return True
    try:
        dt = datetime.fromisoformat(published_at)
    except ValueError:
        return True
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)) >= since
