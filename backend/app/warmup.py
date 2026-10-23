"""Прогрев при старте: все тяжелое делается до приема запросов.

Порядок важен: модель и ее векторы из хранилища → база знаний (векторы тезисов) →
описания тем → новости (переклассификация при смене словарей и векторы заголовков) →
готовые ленты привязанных компаний. Старт дольше, зато первый запрос пользователя
не ждет загрузки модели, пересчета векторов и ранжирования.
"""

import logging
import time

from app import embeddings, vectors
from app.companies import profiles

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
    from app import config, pipeline, ranking

    if not config.warm_feeds_on_start():
        return 0
    pairs = pipeline.audience()
    for company_id, role in pairs:
        ranking.company_feed(company_id, role, 500)
    return len(pairs)


def run() -> dict:
    from app.knowledge import kb
    from app.news import semantic, store

    report: dict = {}
    started = time.perf_counter()
    _step(report, "profiles", lambda: profiles.meta()["profiles"])
    _step(report, "embeddings", embeddings.warm)
    _step(report, "knowledge", kb.warm)
    _step(report, "topics", semantic.warm)
    _step(report, "news", store.warm)
    _step(report, "feeds", _feeds)
    report["vectors"] = vectors.stats()
    logger.info("warmup done in %.1fs: %s", time.perf_counter() - started, report)
    return report
