"""GET /metrics — метрики Prometheus (SPR3-05) и приемник алертов Alertmanager.

Каждый экземпляр API отдает свои счетчики HTTP и агента; показатели из базы (бюджет LLM, очередь,
воркер, источники новостей, бэкап) одинаковы во всех экземплярах — в дашбордах они берутся через max().
Адрес не входит в /api/v1 и в production не публикуется nginx: его читает Prometheus внутри сети.
При заданном METRICS_TOKEN нужен заголовок Authorization: Bearer <токен>.
"""

import hmac
import ipaddress
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Request
from fastapi.responses import PlainTextResponse

from app import config, database, llm_usage, notify, observability
from app.errors import ApiError
from app.news.sources import registry as sources
from app.worker import queue as jobs
from app.worker import runner as worker

logger = logging.getLogger("app.metrics")
router = APIRouter(include_in_schema=False)
BACKUP_KEY, RESTORE_KEY = "backup_last", "restore_test_last"


def _authorized(authorization: str | None) -> None:
    token = config.metrics_token()
    if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise ApiError("UNAUTHORIZED")


def _internal(request: Request) -> bool:
    try:
        ip = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def _age(iso: str | None, now: datetime) -> float | None:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return (now - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))).total_seconds()


def _gauge(name: str, help_: str, samples: list[tuple[str, float | None]]) -> list[str]:
    lines = [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
    return lines + [f"{name}{labels} {observability.number(value)}" for labels, value in samples if value is not None]


def _llm() -> list[str]:
    u = llm_usage.usage()
    return (_gauge("alfa_llm_cost_rub", "Расход LLM за день, ₽", [("", u["cost"])])
            + _gauge("alfa_llm_reserved_cost_rub", "Резерв идущих вызовов LLM, ₽", [("", u["reserved_cost"])])
            + _gauge("alfa_llm_cost_limit_rub", "Дневной лимит LLM, ₽", [("", u["cost_limit"])])
            + _gauge("alfa_llm_tokens", "Токены LLM за день", [("", u["tokens"])])
            + _gauge("alfa_llm_calls", "Вызовы LLM за день", [("", u["calls"])])
            + _gauge("alfa_llm_errors", "Ошибки вызовов LLM за день", [("", u["errors"])])
            + _gauge("alfa_llm_rejected_by_budget", "Отказы по бюджету за день (откаты к правилам)", [("", u["rejected_by_budget"])])
            + _gauge("alfa_llm_budget_spent_ratio", "Доля дневного бюджета: потрачено и зарезервировано",
                     [("", llm_usage.spent_share())])
            + _gauge("alfa_llm_paused", "AI выключен сотрудником банка", [("", float(llm_usage.paused()))]))


def _worker(now: datetime) -> list[str]:
    q = jobs.stats()
    beat = worker.status() or {}
    age = _age(beat.get("at"), now)
    return (_gauge("alfa_jobs", "Задачи воркера по статусу", [(f'{{status="{k}"}}', q[k]) for k in ("queued", "running", "dead")])
            + _gauge("alfa_jobs_oldest_ready_seconds", "Возраст самой старой готовой задачи", [("", q["oldest_ready_seconds"])])
            + _gauge("alfa_worker_heartbeat_age_seconds", "Сколько секунд назад воркер подавал пульс", [("", age)])
            + _gauge("alfa_workers", "Воркеров с пульсом", [("", beat.get("workers", 0))]))


def _sources(now: datetime) -> list[str]:
    stats = sources.stats()
    ok_ages = [a for a in (_age(s.get("last_ok"), now) for s in stats.values()) if a is not None]
    # id в метке: у одного издания бывает несколько лент (Ведомости, Коммерсантъ) — серии не должны совпадать.
    rows = [(f'{{source="{s.get("name", sid)}",kind="{s.get("kind", "")}",id="{sid}"}}', s) for sid, s in stats.items()]
    return (_gauge("alfa_news_lag_seconds", "Сколько секунд назад источники новостей последний раз ответили успешно",
                   [("", min(ok_ages) if ok_ages else None)])
            + _gauge("alfa_source_errors_total", "Ошибки опроса источника за все время", [(l, s.get("errors_total", 0)) for l, s in rows])
            + _gauge("alfa_source_latency_ms", "Время ответа источника при последнем опросе", [(l, s.get("latency_ms")) for l, s in rows])
            + _gauge("alfa_source_publish_lag_seconds", "От публикации до ленты (последняя новая новость)",
                     [(l, s.get("lag_seconds")) for l, s in rows]))


def _backup() -> list[str]:
    out = []
    for key, name, help_ in ((BACKUP_KEY, "alfa_backup_last_success_timestamp_seconds", "Время последнего успешного бэкапа"),
                             (RESTORE_KEY, "alfa_restore_test_last_success_timestamp_seconds",
                              "Время последней успешной проверки восстановления")):
        at = (database.state(key) or {}).get("at")
        try:
            value = datetime.fromisoformat(at).timestamp() if at else None
        except ValueError:
            value = None
        out += _gauge(name, help_, [("", value)])
    return out


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(authorization: str | None = Header(None)) -> str:
    _authorized(authorization)
    now = datetime.now(timezone.utc)
    lines = observability.render()
    for part, collect in (("llm", _llm), ("worker", lambda: _worker(now)), ("sources", lambda: _sources(now)),
                          ("backup", _backup)):
        try:
            lines += collect()
        except Exception:  # база недоступна — метрики процесса все равно отдаются  # noqa: BLE001
            logger.exception("metrics part failed: %s", part)
            lines += _gauge("alfa_metrics_collect_errors", "Ошибка сбора части метрик", [(f'{{part="{part}"}}', 1)])
    return "\n".join(lines) + "\n"


@router.post("/internal/alerts")
async def alerts(request: Request, authorization: str | None = Header(None)) -> dict:
    """Webhook Alertmanager: алерт уходит в канал команды (Telegram) и в лог."""
    _authorized(authorization)
    if not config.metrics_token() and not _internal(request):
        raise ApiError("FORBIDDEN")  # без токена алерты принимаются только из внутренней сети (Alertmanager)
    body = await request.json()
    sent = 0
    for alert in body.get("alerts", []):
        labels, notes = alert.get("labels", {}), alert.get("annotations", {})
        status = "🔴" if alert.get("status") == "firing" else "✅"
        text = f"{status} {labels.get('alertname', 'alert')}: {notes.get('summary', '')}"
        logger.warning("alert %s %s", alert.get("status"), labels.get("alertname"))
        sent += bool(notify.send(text))
    return {"received": len(body.get("alerts", [])), "sent": sent}
