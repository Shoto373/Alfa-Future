"""Прогрев при старте: все тяжелое делается до приема запросов.

API (role="api"): профили, модель и ее векторы из хранилища, база знаний (векторы тезисов), описания тем,
новости — в память. Тяжелое и общее для всех экземпляров делает воркер (role="worker"): переклассификация
новостей при смене словарей, векторы заголовков и готовые ленты привязанных компаний в общем кэше.
Поэтому второй экземпляр API стартует быстро и ничего не пересчитывает повторно.
"""

import logging
import time

from app import config, embeddings, pipeline, ranking, vectors
from app.companies import profiles
from app.knowledge import kb
from app.news import semantic, store

logger = logging.getLogger("app.warmup")


def _step(report: dict, name: str, fn):
    t0 = time.perf_counter()
    try:
        result = fn()
        report[name] = {"ms": round((time.perf_counter() - t0) * 1000), "result": result}
    except Exception as exc:  # прогрев ускоряет, но не должен ронять сервис
        logger.exception("warmup step failed: %s", name)
        report[name] = {"ms": round((time.perf_counter() - t0) * 1000), "error": type(exc).__name__}


def _feeds() -> int:
    if not config.warm_feeds_on_start():
        return 0
    pairs = pipeline.audience()
    for company_id, role in pairs:
        ranking.company_feed(company_id, role, 500)
    return len(pairs)


def run(role: str = "api") -> dict:
    report: dict = {"role": role}
    started = time.perf_counter()
    _step(report, "profiles", lambda: profiles.meta()["profiles"])
    _step(report, "embeddings", embeddings.warm)
    _step(report, "knowledge", kb.warm)
    _step(report, "topics", semantic.warm)
    if role == "worker":
        _step(report, "news", store.warm)
        _step(report, "feeds", _feeds)
    else:
        _step(report, "news", store.load)
    report["vectors"] = vectors.stats()
    logger.info("warmup done in %.1fs: %s", time.perf_counter() - started, report)
    return report
