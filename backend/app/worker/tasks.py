"""Задачи воркера по видам. Обработчик получает payload задачи; исключение — неудачная попытка (повтор)."""

import logging
from collections.abc import Callable

from app import config, llm_usage, pipeline, ranking
from app.domain_config import loader as domain_config
from app.domain_config import preview as config_preview
from app.knowledge import ingest
from app.news import store
from app.worker import queue

logger = logging.getLogger("app.worker")


def news_cycle(payload: dict) -> dict:
    """Сбор RSS, разборы на правилах и AI-версии для привязанных компаний, отчет о качестве."""
    report = pipeline.run_cycle(config.rss_refresh_minutes() or 15)
    return {"skipped": report is None} if report is None else {k: report.get(k) for k in ("rules_built", "llm_built", "duration")}


def news_reclassify(payload: dict) -> dict:
    """Переклассификация новостей при смене словарей и правил (после выкладки) и векторы заголовков."""
    return {"news": store.warm()}


def news_index(payload: dict) -> dict:
    """Сюжеты в базе и организации в новостях (news_entities): после сбора, добавления и переклассификации."""
    return pipeline.index_news()


def kb_ingest(payload: dict) -> dict:
    """Распознать загруженный PDF аналитики банка и сохранить черновики тезисов (SPR3-03)."""
    return ingest.process(payload["doc_id"])


def domain_config_apply(payload: dict) -> dict:
    """Новая версия доменной конфигурации (SPR4-00): применить, переклассифицировать новости и обновить индекс."""
    domain_config.refresh(force=True)
    store.reset_cache()
    news = store.warm()  # подпись словарей сменилась — новости классифицируются заново под блокировкой
    return {"news": news, **pipeline.index_news()}


def domain_config_preview(payload: dict) -> dict:
    """Предпросмотр «как изменится лента компании» без публикации."""
    result = config_preview.run(payload["texts"], payload["company_id"], payload["role"], store, ranking.feed)
    config_preview.save(payload["id"], result)
    return {"status": result["status"]}


def warm_feeds(payload: dict) -> dict:
    """Ленты привязанных компаний — в общий кэш (Redis): первое открытие ленты в любом экземпляре API быстрое."""
    pairs = pipeline.audience()
    for company_id, role in pairs:
        ranking.company_feed(company_id, role, 500)
    return {"pairs": len(pairs)}


def llm_sweep(payload: dict) -> dict:
    """Снять зависшие резервы бюджета LLM (процесс упал посреди вызова)."""
    return {"released": llm_usage.sweep()}


def jobs_cleanup(payload: dict) -> dict:
    return {"removed": queue.cleanup()}


HANDLERS: dict[str, Callable[[dict], dict]] = {
    "news_cycle": news_cycle,
    "news_reclassify": news_reclassify,
    "news_index": news_index,
    "kb_ingest": kb_ingest,
    "domain_config_apply": domain_config_apply,
    "domain_config_preview": domain_config_preview,
    "warm_feeds": warm_feeds,
    "llm_sweep": llm_sweep,
    "jobs_cleanup": jobs_cleanup,
}
