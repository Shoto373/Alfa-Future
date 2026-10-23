"""Автоматический конвейер: сбор новостей из RSS и их разбор для компаний — в фоне, без участия пользователя.

Цикл (каждые RSS_REFRESH_MINUTES минут, первый — вскоре после старта; 0 — конвейер выключен):
1. Сбор: parser.refresh() — новые новости из RSS. Уже известные пропускаются,
   новые классифицируются, в базу попадают только деловые.
2. Сюжеты: новые сюжеты из 3+ сообщений получают короткое название от быстрой модели
   (PIPELINE_STORY_LABELS за цикл, в пределах доли бюджета конвейера).
3. Разбор на правилах: для каждой привязанной компании и каждой роли ее
   участников — самые релевантные новости ленты без готового разбора
   (PIPELINE_RULES_TOP на пару «компания — роль»). Это быстро и без LLM:
   пользователь открывает уже готовую карточку.
4. AI-версия: самые релевантные из карточек на правилах пересчитываются
   моделью — не больше PIPELINE_LLM_PER_CYCLE за цикл и только пока конвейер
   не потратил долю PIPELINE_LLM_SHARE дневного лимита LLM: остальное — пользователям.
5. Ежедневный отчет о качестве в Telegram (app/quality.py), если настроен бот.

Несколько воркеров uvicorn: цикл занимается под pg_advisory_xact_lock с отметкой в app_state,
поэтому за интервал его проходит ровно один процесс. Статус цикла общий для всех воркеров (/meta).
Сбой одного источника, шага, пары «компания — роль» или разбора не останавливает остальные.
"""

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app import config, database, llm_usage, quality, ranking, storage
from app.companies import profiles

logger = logging.getLogger("app.pipeline")

STATE_KEY = "pipeline"
LOCK_ID = 72810402  # 72810401 занят миграциями (database.migrate)
_OWNER = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"


def status() -> dict:
    """Статус конвейера для /meta: state, started_at, rss, rules_built, llm_built, llm_skipped, duration."""
    minutes = config.rss_refresh_minutes()
    saved = database.state(STATE_KEY) or {}
    result = {"state": "idle", "interval_minutes": minutes, "started_at": None, "rss": None, "stories_named": 0,
              "pairs": 0, "rules_built": 0, "llm_built": 0, "llm_skipped": None, "quality_report": False,
              "duration": None, "error": None}
    result.update({k: v for k, v in saved.items() if k in result})
    if minutes <= 0:
        result["state"] = "disabled"
    return result


def audience() -> list[tuple[str, str]]:
    """Пары «компания — роль» по участникам привязанных компаний."""
    from app.auth import store as auth_store

    pairs = {(cid, m["role"]) for cid in auth_store.claimed_ids() for m in auth_store.list_members(cid)
             if m["user_id"]}
    return sorted((cid, role) for cid, role in pairs if profiles.get(cid) is not None)


def _name_stories() -> int:
    """Динамические темы: сюжеты из 3+ сообщений получают короткое название от быстрой модели."""
    from app.agent import llm, prompts
    from app.news import store

    if not _llm_budget_left():
        return 0
    known = store._labels()
    todo = sorted((s for s in store.stories(min_size=3) if s["story_id"] not in known),
                  key=lambda s: s["last"], reverse=True)[: config.pipeline_story_labels()]
    labels = {}
    for s in todo:
        titles = [store.get(i)["title"] for i in s["news_ids"][-6:] if store.get(i)]
        try:
            data, _ = llm.chat_json(prompts.STORY_SYSTEM, json.dumps({"titles": titles}, ensure_ascii=False), "plan", 300)
        except llm.LLMError:
            break
        label = data.get("label") if isinstance(data, dict) else None
        if isinstance(label, str) and 3 <= len(label.strip()) <= 80:
            labels[s["story_id"]] = label.strip().strip('"«»')
    if labels:
        store.set_story_labels(labels)
    return len(labels)


def _llm_budget_left() -> bool:
    from app.agent import llm

    if not llm.available():
        return False
    u = llm_usage.usage()
    share = config.pipeline_llm_share()
    # С резервом идущих вызовов: доля конвейера не съедает бюджет, уже обещанный запросам пользователей.
    return u["tokens"] + u["reserved_tokens"] < u["limit"] * share and u["cost"] + u["reserved_cost"] < u["cost_limit"] * share


async def _analyze(company: dict, role: str, news: dict, use_llm: bool) -> dict | None:
    from app.agent import orchestrator

    request_id = f"req_auto_{uuid.uuid4().hex}"
    try:
        job = orchestrator.run(company, role, news, request_id, use_llm=use_llm)
        insight = await asyncio.wait_for(job, timeout=config.analysis_timeout())
        await asyncio.to_thread(storage.save_insight, insight)
    except Exception as exc:  # одна неудачная карточка не останавливает конвейер
        logger.warning("auto analysis failed company=%s news=%s llm=%s: %s",
                       company["company_id"], news["news_id"], use_llm, type(exc).__name__)
        return None
    return insight


def _save(report: dict) -> None:
    with database.session() as db:
        database.set_state(STATE_KEY, report, db)


async def _collect(report: dict) -> None:
    from app.news import parser

    if not config.rss_sources():
        return
    try:
        rss = await asyncio.to_thread(parser.refresh)
        report["rss"] = {"added": rss["added"], "duplicates": rss["duplicates"], "skipped": rss["skipped"],
                         "full_text": rss.get("full_text", 0),
                         "failed": [s["name"] for s in rss["sources"] if s["error"]]}
    except Exception as exc:  # без свежих новостей разбираем то, что уже есть в базе
        logger.exception("pipeline rss step failed")
        report["rss"] = {"added": 0, "duplicates": 0, "skipped": 0, "full_text": 0, "failed": [],
                         "error": type(exc).__name__}


async def _optional(step, name: str, default):
    """Вспомогательный шаг (названия сюжетов, отчет о качестве): сбой не мешает разборам."""
    try:
        return await asyncio.to_thread(step)
    except Exception:
        logger.exception("pipeline %s step failed", name)
        return default


async def _build_rules(report: dict, company_id: str, role: str, upgrade: list) -> None:
    """Разборы на правилах для лучших новостей ленты одной пары; кандидаты на AI-версию — в upgrade."""
    company = profiles.get(company_id)
    top = config.pipeline_rules_top()
    feed = (await asyncio.to_thread(ranking.company_feed, company_id, role, 500))[:top]
    cached = await asyncio.to_thread(storage.cached_insights, company_id, role, [r["news"]["news_id"] for r in feed])
    for item in feed:
        news = item["news"]
        insight = cached.get(news["news_id"])
        if insight is None:
            insight = await _analyze(company, role, news, use_llm=False)
            report["rules_built"] += insight is not None
        if insight is not None and insight["mode"] == "rules" and not storage.llm_attempted(insight):
            upgrade.append((item["relevance"]["score"], company, role, news))


async def cycle(started_at: str | None = None) -> dict:
    """Один проход конвейера. Возвращает отчет (он же — статус в /meta)."""
    started = time.perf_counter()
    report = {"state": "idle", "started_at": started_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "rss": None, "stories_named": 0, "pairs": 0, "rules_built": 0, "llm_built": 0, "llm_skipped": None,
              "quality_report": False, "duration": None, "error": None}
    await _collect(report)
    report["stories_named"] = await _optional(_name_stories, "stories", 0)

    pairs = await asyncio.to_thread(audience)
    report["pairs"] = len(pairs)
    upgrade: list[tuple[float, dict, str, dict]] = []
    for company_id, role in pairs:
        try:
            await _build_rules(report, company_id, role, upgrade)
        except Exception:  # сбой ленты одной компании не мешает остальным
            logger.exception("pipeline feed failed company=%s role=%s", company_id, role)

    upgrade.sort(key=lambda u: -u[0])
    for _, company, role, news in upgrade[: config.pipeline_llm_per_cycle()]:
        if not await asyncio.to_thread(_llm_budget_left):
            report["llm_skipped"] = "LLM не подключена или исчерпана доля дневного лимита конвейера"
            break
        insight = await _analyze(company, role, news, use_llm=True)
        report["llm_built"] += bool(insight and insight["mode"] == "llm")

    report["duration"] = round(time.perf_counter() - started, 1)
    await asyncio.to_thread(_save, report)
    # Отчет (раз в сутки, только при настроенном боте) читает итоги цикла из app_state — поэтому после записи.
    if await _optional(quality.maybe_send_daily, "quality report", False):
        report["quality_report"] = True
        await asyncio.to_thread(_save, report)
    logger.info("pipeline cycle: %s", report)
    return report


def _age(saved: dict, now: datetime) -> float | None:
    try:
        return (now - datetime.fromisoformat(saved["started_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return None


def claim(minutes: int) -> str | None:
    """Занимает цикл для этого процесса; None — его уже проходит или недавно прошел другой воркер.

    Проверка и отметка идут в одной транзакции под pg_advisory_xact_lock: два воркера, проснувшиеся
    одновременно, не займут цикл оба. Зависший «running» (процесс упал) считается свободным через 2 интервала.
    """
    now = datetime.now(timezone.utc)
    with database.session() as db:
        db.execute(select(func.pg_advisory_xact_lock(LOCK_ID)))
        saved = database.state(STATE_KEY, db) or {}
        age = _age(saved, now)
        busy_for = minutes * 60 * (2 if saved.get("state") == "running" else 0.5)
        if age is not None and age < busy_for:
            return None
        started_at = now.isoformat(timespec="seconds")
        database.set_state(STATE_KEY, {"state": "running", "started_at": started_at, "owner": _OWNER}, db)
    return started_at


async def loop(minutes: int) -> None:
    await asyncio.sleep(config.pipeline_start_delay())  # сначала сервис отвечает пользователям
    while True:
        started_at = None
        try:
            started_at = await asyncio.to_thread(claim, minutes)
            if started_at:
                await cycle(started_at)
        except Exception as exc:  # сбой цикла не должен останавливать сервис
            logger.exception("pipeline cycle failed")
            if started_at:
                with contextlib.suppress(Exception):  # база недоступна — отметка снимется через 2 интервала
                    await asyncio.to_thread(_save, {"state": "idle", "started_at": started_at,
                                                    "error": type(exc).__name__})
        await asyncio.sleep(minutes * 60)
