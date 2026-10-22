"""Персонализированное ранжирование новостей для компании и роли.

score = важность × (совпадение тем с экспозициями компании
        + прямое упоминание отрасли + отрасли крупных контрагентов
        + страны ВЭД + регион компании) × вес роли × сила события × свежесть.

Важность и вес роли взвешиваются долей темы в новости: мимолетное упоминание
ставки не делает новость главной для финансового директора. Несколько
признаков одной темы складываются с убывающим весом (1, 1/2, 1/4…), чтобы
компании с богатым профилем не получали 90+ за любую новость.
Каждое слагаемое сохраняется как причина: пользователь видит, почему новость
поднялась в ленте, а эксперт — как воспроизвести оценку.
"""

import math
import re
from datetime import datetime, timezone

from app import embeddings
from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES
from app.news import magnitude
from app.news.taxonomy import TOPICS

ROLES = {
    "owner": {"name": "Собственник", "focus": {"sanctions_geopolitics": 1.3, "gdp_industry": 1.2, "consumer_demand": 1.2, "corporate_finance": 1.3, "construction_realestate": 1.1}},
    "ceo": {"name": "Генеральный директор", "focus": {"consumer_demand": 1.3, "gdp_industry": 1.3, "imports_exports": 1.2, "sanctions_geopolitics": 1.2, "labor": 1.2, "key_rate": 1.0}},
    "cfo": {"name": "Финансовый директор", "focus": {"key_rate": 1.4, "credit_market": 1.3, "bonds": 1.3, "fx": 1.3, "deposits": 1.2, "inflation": 1.2, "corporate_finance": 1.2}},
    "accountant": {"name": "Главный бухгалтер", "focus": {"budget": 1.4, "imports_exports": 1.2, "labor": 1.1, "corporate_finance": 1.2}},
    "treasurer": {"name": "Руководитель казначейства", "focus": {"key_rate": 1.4, "fx": 1.4, "deposits": 1.3, "bonds": 1.3, "credit_market": 1.2}},
    "clevel": {"name": "Другой C-level руководитель", "focus": {"gdp_industry": 1.1, "consumer_demand": 1.1, "labor": 1.1}},
}

HALF_LIFE_DAYS = 45
MAX_FEED_AGE_DAYS = 120
MIN_FEED_SCORE = 10.0
REGION_WEIGHT = 0.5
# «Москва» в новостях чаще означает государство («Москва заявила»), а «московское время» и «Мосбиржа»
# не про регион; к тому же здесь половина компаний — сигнал региона для них не различает новости.
REGION_SKIP = {"москв", "московск"}
COUNTERPARTY_MIN_SHARE = 0.15
STORY_SIMILARITY = 0.88  # заголовки ближе этого — один сюжет из разных источников
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


def _region_stem(region: str | None) -> str | None:
    """«Иркутская область» -> «иркутск», «Москва» -> «москв»: основа для поиска в тексте."""
    if not region:
        return None
    word = region.replace("г.", "").split("(")[0].split()[0].strip(" ,").lower().replace("ё", "е")
    if len(word) < 4:
        return None
    for ending in ("ая", "ий", "ой", "а", "я", "ь"):
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


def score(news: dict, company_id: str, role: str) -> dict:
    c = profiles.get(company_id)
    cls = news["classification"]
    reasons: list[dict] = []
    topic_scores = {t["topic"]: t["score"] for t in cls["topics"]}
    total_topic = sum(topic_scores.values()) or 1
    shares = {t: v / total_topic for t, v in topic_scores.items()}

    by_topic: dict[str, list[float]] = {}
    seen = set()
    for e in profiles.exposures(company_id):
        if e["topic"] not in topic_scores:
            continue
        contribution = e["weight"] * (0.5 + shares[e["topic"]])
        by_topic.setdefault(e["topic"], []).append(contribution)
        key = (e["topic"], e["feature"])
        if key not in seen:
            seen.add(key)
            reasons.append({"kind": "exposure", "topic": e["topic"], "feature": e["feature"], "origin": e["origin"],
                            "weight": round(contribution, 3), "text": e["why"]})
    # Убывающий вклад признаков одной темы: 1, 1/2, 1/4…
    exposure_sum = sum(v * 0.5 ** i for values in by_topic.values() for i, v in enumerate(sorted(values, reverse=True)))

    direct = 0.0
    if c and c["sector"] in cls["sectors"]:
        direct = 1.0
        reasons.append({"kind": "sector_mention", "feature": "sector", "origin": "news", "weight": 1.0,
                        "text": f"В новости прямо упоминается отрасль компании — {SECTOR_NAMES.get(c['sector'])}"})
    supply_chain = 0.0
    if c:
        for side, label in (("suppliers", "поставщикам"), ("customers", "от покупателей")):
            for item in c[side]["by_sector"]:
                if item["sector"] in cls["sectors"] and item["sector"] not in ("unknown", c["sector"]) \
                        and item["share"] >= COUNTERPARTY_MIN_SHARE:
                    supply_chain += item["share"]
                    reasons.append({"kind": "supply_chain", "feature": f"{side}.by_sector", "origin": "payments",
                                    "weight": round(item["share"], 3),
                                    "text": f"Новость об отрасли «{SECTOR_NAMES.get(item['sector'], item['sector'])}»: "
                                            f"на нее приходится {round(item['share'] * 100)}% платежей {label}"})
        supply_chain = min(supply_chain, 1.0)
    country_hit = 0.0
    if c:
        overlap = sorted(set(cls["countries"]) & {x.title() for x in c["fts_countries"]})
        if overlap:
            country_hit = 1.0
            reasons.append({"kind": "country", "feature": "fts_countries", "origin": "client_data", "weight": 1.0,
                            "text": f"Новость касается стран ВЭД компании: {', '.join(overlap)}"})
    region_hit = 0.0
    stem = _region_stem(c.get("region")) if c else None
    if stem and stem not in REGION_SKIP and re.search(rf"(?<![а-яa-z-]){re.escape(stem)}",
                                                      f"{news['title']} {news['text'][:1500]}".lower().replace("ё", "е")):
        region_hit = REGION_WEIGHT
        reasons.append({"kind": "region", "feature": "region", "origin": "client_data", "weight": REGION_WEIGHT,
                        "text": f"Новость касается региона компании — {c['region']}"})

    role_spec = ROLES.get(role, ROLES["ceo"])
    role_mult = sum(share * role_spec["focus"].get(t, 1.0) for t, share in shares.items()) if shares else 1.0
    if role_mult > 1.05:
        reasons.append({"kind": "role", "feature": "role", "origin": "user", "weight": round(role_mult, 2),
                        "text": f"Тема в фокусе роли «{role_spec['name']}»"})

    strength = cls.get("magnitude")
    strength_mult = magnitude.FACTOR[strength["level"]] if strength else 1.0
    if strength and strength["level"] == "strong":
        reasons.append({"kind": "magnitude", "feature": "magnitude", "origin": "news", "weight": strength_mult,
                        "text": f"Сильное изменение: «{strength['evidence']}»"})

    age = _age_days(news["published_at"])
    freshness = 0.5 ** (age / HALF_LIFE_DAYS)
    importance = 0.5 + sum(share * TOPICS[t]["importance"] for t, share in shares.items() if t in TOPICS)
    # No permanent 40% freshness floor: old external events must leave the feed.
    raw = importance * (exposure_sum + direct + supply_chain + country_hit + region_hit) * role_mult * strength_mult * freshness
    value = round(100 * (1 - math.exp(-raw / 2.5)), 1)

    reasons.sort(key=lambda r: r["weight"], reverse=True)
    return {"score": value, "raw": round(raw, 3), "freshness": round(freshness, 3), "age_days": round(age, 1),
            "reasons": reasons[:8]}


def _collapse_stories(ranked: list[dict]) -> list[dict]:
    """Один сюжет из разных источников показывается один раз: похожие заголовки склеиваются."""
    vectors = embeddings.embed([r["news"]["title"] for r in ranked]) if len(ranked) > 1 else None
    if not vectors:
        return ranked
    kept: list[tuple[dict, list[float]]] = []
    for item, vec in zip(ranked, vectors):
        twin = next((k for k, v in kept if embeddings.cosine(vec, v) >= STORY_SIMILARITY), None)
        if twin is None:
            kept.append((item, vec))
        else:
            twin["story_size"] = twin.get("story_size", 0) + 1
    return [k for k, _ in kept]


def feed(items: list[dict], company_id: str, role: str, topic: str | None = None, limit: int = 30) -> list[dict]:
    ranked = []
    for news in items:
        if topic and topic not in [t["topic"] for t in news["classification"]["topics"]]:
            continue
        relevance = score(news, company_id, role)
        has_company_basis = any(r["kind"] in ("exposure", "sector_mention", "country", "supply_chain", "region")
                                for r in relevance["reasons"])
        if not news["classification"]["topics"] or not has_company_basis or relevance["score"] < MIN_FEED_SCORE:
            continue
        if news.get("kind") != "seed" and relevance["age_days"] > MAX_FEED_AGE_DAYS:
            continue
        ranked.append({"news": news, "relevance": relevance})
    ranked.sort(key=lambda r: r["relevance"]["score"], reverse=True)
    return _collapse_stories(ranked[: limit * 2])[:limit]
