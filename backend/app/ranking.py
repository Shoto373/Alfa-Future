"""Персонализированное ранжирование новостей для компании и роли.

score = важность темы × (совпадение тем с экспозициями компании
        + прямое упоминание отрасли + совпадение стран ВЭД + регион)
        × вес роли × свежесть.
Каждое слагаемое сохраняется как причина: пользователь видит, почему новость
поднялась в ленте, а эксперт — как воспроизвести оценку.
"""

import math
from datetime import datetime, timezone

from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES

ROLES = {
    "owner": {"name": "Собственник", "focus": {"sanctions_geopolitics": 1.3, "gdp_industry": 1.2, "consumer_demand": 1.2, "corporate_finance": 1.3, "construction_realestate": 1.1}},
    "ceo": {"name": "Генеральный директор", "focus": {"consumer_demand": 1.3, "gdp_industry": 1.3, "imports_exports": 1.2, "sanctions_geopolitics": 1.2, "labor": 1.2, "key_rate": 1.0}},
    "cfo": {"name": "Финансовый директор", "focus": {"key_rate": 1.4, "credit_market": 1.3, "bonds": 1.3, "fx": 1.3, "deposits": 1.2, "inflation": 1.2, "corporate_finance": 1.2}},
    "accountant": {"name": "Главный бухгалтер", "focus": {"budget": 1.4, "imports_exports": 1.2, "labor": 1.1, "corporate_finance": 1.2}},
    "treasurer": {"name": "Руководитель казначейства", "focus": {"key_rate": 1.4, "fx": 1.4, "deposits": 1.3, "bonds": 1.3, "credit_market": 1.2}},
    "clevel": {"name": "Другой C-level руководитель", "focus": {"gdp_industry": 1.1, "consumer_demand": 1.1, "labor": 1.1}},
}

HALF_LIFE_DAYS = 45
NOW_OVERRIDE: datetime | None = None  # для тестов


def _age_days(published_at: str) -> float:
    try:
        dt = datetime.fromisoformat(published_at)
    except ValueError:
        return 30.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = NOW_OVERRIDE or datetime.now(timezone.utc)
    return max((now - dt).total_seconds() / 86400, 0.0)


def score(news: dict, company_id: str, role: str) -> dict:
    c = profiles.get(company_id)
    cls = news["classification"]
    reasons: list[dict] = []
    topic_scores = {t["topic"]: t["score"] for t in cls["topics"]}
    total_topic = sum(topic_scores.values()) or 1

    exposure_sum = 0.0
    seen = set()
    for e in profiles.exposures(company_id):
        if e["topic"] not in topic_scores:
            continue
        share = topic_scores[e["topic"]] / total_topic
        contribution = e["weight"] * (0.5 + share)
        exposure_sum += contribution
        key = (e["topic"], e["feature"])
        if key not in seen:
            seen.add(key)
            reasons.append({"kind": "exposure", "topic": e["topic"], "feature": e["feature"], "origin": e["origin"],
                            "weight": round(contribution, 3), "text": e["why"]})

    direct = 0.0
    if c and c["sector"] in cls["sectors"]:
        direct = 1.0
        reasons.append({"kind": "sector_mention", "feature": "sector", "origin": "news", "weight": 1.0,
                        "text": f"В новости прямо упоминается отрасль компании — {SECTOR_NAMES.get(c['sector'])}"})
    country_hit = 0.0
    if c:
        overlap = sorted(set(cls["countries"]) & {x.title() for x in c["fts_countries"]})
        if overlap:
            country_hit = 1.0
            reasons.append({"kind": "country", "feature": "fts_countries", "origin": "client_data", "weight": 1.0,
                            "text": f"Новость касается стран ВЭД компании: {', '.join(overlap)}"})

    role_spec = ROLES.get(role, ROLES["ceo"])
    role_mult = max((role_spec["focus"].get(t, 1.0) for t in topic_scores), default=1.0)
    if role_mult > 1.0:
        reasons.append({"kind": "role", "feature": "role", "origin": "user", "weight": round(role_mult, 2),
                        "text": f"Тема в фокусе роли «{role_spec['name']}»"})

    age = _age_days(news["published_at"])
    freshness = 0.5 ** (age / HALF_LIFE_DAYS)
    importance = 0.5 + cls["importance"]
    raw = importance * (exposure_sum + direct + country_hit) * role_mult * (0.4 + 0.6 * freshness)
    value = round(100 * (1 - math.exp(-raw / 2.5)), 1)

    reasons.sort(key=lambda r: r["weight"], reverse=True)
    return {"score": value, "raw": round(raw, 3), "freshness": round(freshness, 3), "age_days": round(age, 1),
            "reasons": reasons[:8]}


def feed(items: list[dict], company_id: str, role: str, topic: str | None = None, limit: int = 30) -> list[dict]:
    ranked = []
    for news in items:
        if topic and topic not in [t["topic"] for t in news["classification"]["topics"]]:
            continue
        ranked.append({"news": news, "relevance": score(news, company_id, role)})
    ranked.sort(key=lambda r: r["relevance"]["score"], reverse=True)
    return ranked[:limit]
