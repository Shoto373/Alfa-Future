"""Задачи воркера по видам. Обработчик получает payload задачи; исключение — неудачная попытка (повтор)."""

import logging
from collections.abc import Callable

from app import config, llm_usage, pipeline, ranking
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
    "warm_feeds": warm_feeds,
    "llm_sweep": llm_sweep,
    "jobs_cleanup": jobs_cleanup,
}
