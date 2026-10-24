"""Разметка релевантности для аналитиков (SPR3-06): очередь пар, оценки, согласованность и выгрузка.

Пары берутся из ranking_eval.plan() (300 пар). Каждая пара размечается одним человеком; пары с overlap
(каждая пятая) — двумя разными, по ним считается κ. Разметчику не показываются оценка и причины системы —
чтобы разметка не повторяла ранжирование.
"""

from datetime import timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import database, ranking, ranking_eval
from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES
from app.models import RankingLabel
from app.news import store
from app.news.taxonomy import TOPICS

GRADES = {0: "Не про компанию", 1: "Слабо связана", 2: "Важна", 3: "Важна, нужна реакция"}
PLAN_KEY = "labeling_plan"


def plan() -> list[dict]:
    """План разметки фиксируется при первом обращении: новые новости не меняют уже начатую выборку."""
    saved = database.state(PLAN_KEY)
    if saved:
        return saved
    pairs = ranking_eval.plan()
    with database.session() as db:
        database.set_state(PLAN_KEY, pairs, db)
    return pairs


def labels() -> list[dict]:
    with database.session() as db:
        found = db.scalars(select(RankingLabel).order_by(RankingLabel.id))
        return [{"news_id": r.news_id, "company_id": r.company_id, "role": r.role, "grade": r.grade, "reason": r.reason,
                 "annotator": r.annotator, "created_at": r.created_at.astimezone(timezone.utc).isoformat()} for r in found]


def _key(x: dict) -> tuple:
    return x["news_id"], x["company_id"], x["role"]


def next_pair(annotator: str) -> dict | None:
    """Следующая пара: сначала не размеченные никем, затем пары для второго мнения (overlap)."""
    by_pair: dict[tuple, set[str]] = {}
    for label in labels():
        by_pair.setdefault(_key(label), set()).add(label["annotator"])
    pairs = plan()
    fresh = [p for p in pairs if _key(p) not in by_pair]
    second = [p for p in pairs if p["overlap"] and len(by_pair.get(_key(p), ())) == 1 and annotator not in by_pair[_key(p)]]
    pair = (fresh or second or [None])[0]
    return None if pair is None else _card(pair)


def _card(pair: dict) -> dict:
    news = store.get(pair["news_id"]) or {}
    c = profiles.get(pair["company_id"]) or {}
    sides = {side: [f"{SECTOR_NAMES.get(i['sector'], i['sector'])} {round(i['share'] * 100)}%"
                    for i in (c.get(side) or {}).get("by_sector", [])[:3] if i["sector"] != "unknown"]
             for side in ("suppliers", "customers")}
    return {**pair, "role_name": ranking.ROLES.get(pair["role"], {}).get("name", pair["role"]),
            "news": {"title": news.get("title"), "lead": news.get("lead"), "source": news.get("source"),
                     "published_at": news.get("published_at"),
                     "topics": [TOPICS[t["topic"]]["name"] for t in (news.get("classification") or {}).get("topics", [])
                                if t["topic"] in TOPICS]},
            "company": {"name": c.get("display_name"), "sector": SECTOR_NAMES.get(c.get("sector"), c.get("sector")),
                        "region": c.get("region"), "revenue": c.get("revenue"), "countries": c.get("fts_countries") or [],
                        "suppliers": sides["suppliers"], "customers": sides["customers"]}}


def save(news_id: str, company_id: str, role: str, grade: int, reason: str, annotator: str) -> None:
    """Оценка разметчика; повторная оценка той же пары тем же человеком заменяет прежнюю."""
    values = {"news_id": news_id, "company_id": company_id, "role": role, "grade": grade, "reason": reason[:500],
              "annotator": annotator}
    with database.session() as db:
        db.execute(insert(RankingLabel).values(**values).on_conflict_do_update(
            constraint="ranking_labels_pair_uq", set_={"grade": grade, "reason": reason[:500]}))


def stats() -> dict:
    """Прогресс разметки и согласованность (квадратично взвешенная κ по парам с двумя разметчиками)."""
    found = labels()
    pairs = plan()
    planned = {_key(p) for p in pairs}
    by_pair: dict[tuple, list[dict]] = {}
    for label in found:
        by_pair.setdefault(_key(label), []).append(label)
    double = [(v[0]["grade"], v[1]["grade"]) for v in by_pair.values() if len(v) >= 2]
    annotators: dict[str, int] = {}
    for label in found:
        annotators[label["annotator"]] = annotators.get(label["annotator"], 0) + 1
    k = ranking_eval.kappa(double)
    return {"planned": len(pairs), "labeled_pairs": len(planned & set(by_pair)), "labels": len(found),
            "overlap_planned": sum(p["overlap"] for p in pairs), "overlap_done": len(double),
            "kappa": round(k, 3) if k is not None else None, "annotators": annotators, "grades": GRADES}
