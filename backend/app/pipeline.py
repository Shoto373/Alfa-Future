"""Автоматический конвейер: сбор новостей из RSS и их разбор для компаний — в фоне, без участия пользователя.

Цикл (каждые RSS_REFRESH_MINUTES минут, первый — вскоре после старта):
1. Сбор: parser.refresh() — новые новости из RSS. Уже известные пропускаются,
   новые классифицируются, в базу попадают только деловые.
2. Разбор на правилах: для каждой привязанной компании и каждой роли ее
   участников — самые релевантные новости ленты без готового разбора
   (PIPELINE_RULES_TOP на пару «компания — роль»). Это быстро и без LLM:
   пользователь открывает уже готовую карточку.
3. AI-версия: самые релевантные из карточек на правилах пересчитываются
   моделью — не больше PIPELINE_LLM_PER_CYCLE за цикл и только пока конвейер
   не потратил долю PIPELINE_LLM_SHARE дневного лимита LLM: остальное — пользователям.

Если в базе уже есть отметка недавнего цикла (другой процесс), цикл пропускается.
Сбой одного источника или разбора не останавливает остальные.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from app import config, database, ranking, storage
from app.companies import profiles

logger = logging.getLogger("app.pipeline")

STATE_KEY = "pipeline"
_status: dict = {"state": "idle"}


def status() -> dict:
    """Итог последнего цикла (для /meta)."""
    return dict(_status)


def audience() -> list[tuple[str, str]]:
    """Пары «компания — роль» по участникам привязанных компаний."""
    from app.auth import store as auth_store

    pairs = {(cid, m["role"]) for cid in auth_store.claimed_ids() for m in auth_store.list_members(cid)
             if m["user_id"]}
    return sorted((cid, role) for cid, role in pairs if profiles.get(cid) is not None)


def _llm_budget_left() -> bool:
    from app.agent import llm

    if not llm.available():
        return False
    u = llm.usage()
    share = config.pipeline_llm_share()
    return u["tokens"] < u["limit"] * share and u["cost"] < u["cost_limit"] * share


async def _analyze(company: dict, role: str, news: dict, use_llm: bool) -> dict | None:
    from app.agent import orchestrator

    request_id = f"req_auto_{uuid.uuid4().hex}"
    try:
        job = orchestrator.run(company, role, news, request_id, use_llm=use_llm)
        insight = await asyncio.wait_for(job, timeout=config.analysis_timeout())
    except Exception as exc:  # одна неудачная карточка не останавливает конвейер
        logger.warning("auto analysis failed company=%s news=%s llm=%s: %s",
                       company["company_id"], news["news_id"], use_llm, type(exc).__name__)
        return None
    await asyncio.to_thread(storage.save_insight, insight)
    return insight


async def cycle() -> dict:
    """Один проход конвейера. Возвращает отчет."""
    from app.news import parser

    started = time.perf_counter()
    report = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rss": None,
              "pairs": 0, "rules_built": 0, "llm_built": 0, "llm_skipped": None}
    _status.update(state="running", started_at=report["started_at"])

    if config.rss_sources():
        try:
            rss = await asyncio.to_thread(parser.refresh)
            report["rss"] = {"added": rss["added"], "duplicates": rss["duplicates"], "skipped": rss["skipped"],
                             "failed": [s["name"] for s in rss["sources"] if s["error"]]}
        except Exception:
            logger.exception("pipeline rss step failed")

    pairs = await asyncio.to_thread(audience)
    report["pairs"] = len(pairs)
    upgrade: list[tuple[float, dict, str, dict]] = []
    top = config.pipeline_rules_top()
    for company_id, role in pairs:
        company = profiles.get(company_id)
        feed = await asyncio.to_thread(ranking.company_feed, company_id, role, 500)
        ids = [r["news"]["news_id"] for r in feed[:top]]
        cached = await asyncio.to_thread(storage.cached_insights, company_id, role, ids)
        for item in feed[:top]:
            news = item["news"]
            insight = cached.get(news["news_id"])
            if insight is None:
                insight = await _analyze(company, role, news, use_llm=False)
                report["rules_built"] += insight is not None
            if insight is not None and insight["mode"] == "rules" and not storage.llm_attempted(insight):
                upgrade.append((item["relevance"]["score"], company, role, news))

    upgrade.sort(key=lambda u: -u[0])
    for _, company, role, news in upgrade[: config.pipeline_llm_per_cycle()]:
        if not await asyncio.to_thread(_llm_budget_left):
            report["llm_skipped"] = "LLM не подключена или исчерпана доля дневного лимита конвейера"
            break
        insight = await _analyze(company, role, news, use_llm=True)
        report["llm_built"] += bool(insight and insight["mode"] == "llm")

    report["duration_s"] = round(time.perf_counter() - started, 1)
    _status.clear()
    _status.update(state="idle", last=report)
    with database.session() as db:
        database.set_state(STATE_KEY, report, db)
    logger.info("pipeline cycle: %s", report)
    return report


def _recently_ran(minutes: int) -> bool:
    """Другой процесс уже прошел цикл недавно — этот пропускает свой."""
    last = database.state(STATE_KEY) or {}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last["started_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    return age < minutes * 60 / 2


async def loop(minutes: int) -> None:
    await asyncio.sleep(config.pipeline_start_delay())  # сначала сервис отвечает пользователям
    while True:
        try:
            if not await asyncio.to_thread(_recently_ran, minutes):
                await cycle()
        except Exception:  # сбой цикла не должен останавливать сервис
            logger.exception("pipeline cycle failed")
            _status.update(state="idle")
        await asyncio.sleep(minutes * 60)
