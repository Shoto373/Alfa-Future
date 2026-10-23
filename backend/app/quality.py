"""Мониторинг качества: сводка за сутки и ежедневный отчет в Telegram.

Метрики те же, что в офлайн-оценке (scripts/eval_quality.py), но по реальным разборам:
- llm_share      доля разборов с текстом модели (не откат на правила);
- first_pass     доля разборов, прошедших проверки с первой попытки;
- grounded       доля утверждений со ссылкой на собранный источник;
- bank_coverage  доля разборов с позицией банка;
- useful_rate    доля положительных оценок пользователей;
- latency        p50 / p90 построения разбора, с;
- pipeline       что собрал и разобрал конвейер новостей;
- budget         расход LLM за прошлый день бюджета против лимита, отказы бюджета, причины откатов
                 к правилам (fallback_reason) и расход по моделям.
Отчет уходит раз в сутки (QUALITY_REPORT_HOUR_UTC), если заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID.
"""

import logging
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import config, database, llm_usage, notify
from app.models import Event, Feedback, Insight

logger = logging.getLogger("app.quality")
REPORT_KEY = "quality_report_day"


def _claims(ins: dict) -> list[dict]:
    out = [c for sec in ("why_important", "risks", "opportunities", "actions") for c in ins.get(sec, [])]
    wh = ins.get("what_happened", {})
    return out + wh.get("facts", []) + wh.get("assumptions", []) + ins.get("bank_view", {}).get("theses", [])


def daily(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with database.session() as db:
        insights = list(db.scalars(select(Insight.payload).where(Insight.created_at >= since)))
        ratings = [p.get("rating") for p in db.scalars(select(Feedback.payload).where(Feedback.created_at >= since))]
        events = list(db.scalars(select(Event.kind).where(Event.created_at >= since)))
        pipeline_last = database.state("pipeline", db) or {}
    n = len(insights)
    llm_tried = [i for i in insights if any(s.get("name") == "llm_compose" for s in i.get("trace", []))]
    claims = [c for i in insights for c in _claims(i)]
    sources = {i["insight_id"]: {s["source_id"] for s in i.get("sources", [])} for i in insights}
    linked = sum(1 for i in insights for c in _claims(i) if c.get("source_ids") and set(c["source_ids"]) <= sources[i["insight_id"]])
    # Время и первая попытка — по разборам с моделью: разбор на правилах проходит мгновенно и всегда.
    latency = sorted(next((s["output"]["total_duration_ms"] / 1000 for s in i.get("trace", [])
                           if s.get("stage") == "finalize" and s.get("output")), 0) for i in llm_tried)
    up, down = ratings.count(1), ratings.count(-1)
    # Бюджет — за прошлый день бюджета: отчет уходит утром, когда текущий день только начался.
    yesterday = llm_usage.budget_day() - timedelta(days=1)
    spent = llm_usage.usage(yesterday)
    return {
        "hours": hours,
        "insights": n,
        "llm_attempted": len(llm_tried),
        "llm_share": round(sum(i["mode"] == "llm" for i in llm_tried) / len(llm_tried), 3) if llm_tried else None,
        "first_pass": round(sum(i["quality"]["attempts"] == 1 and i["quality"]["passed"] for i in llm_tried)
                            / len(llm_tried), 3) if llm_tried else None,
        "grounded": round(linked / len(claims), 3) if claims else None,
        "bank_coverage": round(sum(bool(i["bank_view"]["theses"]) for i in insights) / n, 3) if n else None,
        "latency_p50": round(latency[len(latency) // 2], 1) if latency else None,
        "latency_p90": round(latency[min(len(latency) - 1, int(len(latency) * 0.9))], 1) if latency else None,
        "feedback": {"up": up, "down": down, "useful_rate": round(up / (up + down), 3) if up + down else None},
        "feed_views": events.count("feed_view"),
        "insight_opens": events.count("insight_open"),
        "questions": events.count("question"),
        "pipeline": {k: pipeline_last.get(k) for k in ("started_at", "rss", "rules_built", "llm_built", "stories_named")},
        "budget": {"day": spent["date"], "cost": spent["cost"], "cost_limit": spent["cost_limit"], "calls": spent["calls"],
                   "rejected_by_budget": spent["rejected_by_budget"], "by_model": llm_usage.by_model(yesterday),
                   "fallback_reasons": dict(Counter(i.get("fallback_reason") for i in llm_tried
                                                    if i["mode"] == "rules" and i.get("fallback_reason")))},
    }


def _pct(v) -> str:
    return "—" if v is None else f"{round(v * 100)}%"


def report_text(d: dict) -> str:
    rss = (d["pipeline"] or {}).get("rss") or {}
    return "\n".join([
        f"📊 <b>Альфа.Пульс: качество за {d['hours']} ч</b>",
        f"Разборов: {d['insights']} (с моделью: {d['llm_attempted']}) · текст модели у пользователя: {_pct(d['llm_share'])}",
        f"AI-черновик прошел проверки сразу: {_pct(d['first_pass'])} · выводы с источником: {_pct(d['grounded'])}"
        f" · позиция банка: {_pct(d['bank_coverage'])}",
        f"Время AI-разбора p50/p90: {d['latency_p50'] or '—'} / {d['latency_p90'] or '—'} с",
        f"Оценки: 👍 {d['feedback']['up']} · 👎 {d['feedback']['down']} (полезно: {_pct(d['feedback']['useful_rate'])})",
        f"Лента: просмотров {d['feed_views']}, открытий разборов {d['insight_opens']}, вопросов {d['questions']}",
        f"Конвейер (последний цикл): новых новостей {rss.get('added', '—')}, отсеяно {rss.get('skipped', '—')}, "
        f"разборов на правилах {d['pipeline'].get('rules_built', '—')}, AI {d['pipeline'].get('llm_built', '—')}",
        _budget_line(d["budget"]),
    ])


FALLBACK_NAMES = {"budget": "лимит", "company_budget": "доля компании", "unavailable": "модель не ответила", "checks": "не прошли проверки"}


def _budget_line(b: dict) -> str:
    reasons = ", ".join(f"{FALLBACK_NAMES.get(k, k)} — {v}" for k, v in b["fallback_reasons"].items()) or "нет"
    top = b["by_model"][0] if b["by_model"] else None
    priciest = f" · дороже всех: {top['model']} {top['cost']} ₽" if top else ""
    return (f"LLM за {b['day']}: {b['cost']} из {b['cost_limit']} ₽, вызовов {b['calls']}, "
            f"отклонено бюджетом {b['rejected_by_budget']} · откаты к правилам: {reasons}{priciest}")


def maybe_send_daily() -> bool:
    """Отправить отчет, если настал час и сегодня он еще не уходил. True — отправлен."""
    token, chat = config.telegram_settings()
    now = datetime.now(timezone.utc)
    if not token or not chat or now.hour < config.quality_report_hour():
        return False
    day = now.date().isoformat()
    if database.state(REPORT_KEY) == day:
        return False
    if not notify.send(report_text(daily())):
        return False
    with database.session() as db:
        database.set_state(REPORT_KEY, day, db)
    return True
