"""Оценка и калибровка ранжирования по экспертной разметке (SPR3-06).

Разметка — пары «новость × компания × роль» с оценкой 0–3 (0 — не про компанию, 3 — важно, нужна реакция).
Запрос — (компания, роль): размеченные новости упорядочиваются по raw из ranking и сравниваются с оценками.

- nDCG@10 (выигрыш 2^оценка − 1), precision@10 (релевантно — оценка ≥ 2), доля нерелевантных (оценка 0) в топ-3;
  разрезы по отраслям и ролям.
- Калибровка: попарная логистическая регрессия на numpy по слагаемым score (raw = множитель × Σ вес × признак),
  L2-регуляризация к ручным весам, веса не отрицательны; кросс-валидация по компаниям — веса подбираются
  без компании и проверяются на ней. Причины в ленте остаются теми же фразами: меняются только веса.
"""

import hashlib
import math
from collections import defaultdict
from statistics import mean

import numpy as np

from app import ranking
from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES
from app.news import store

RELEVANT = 2
K = 10
# План разметки: 5 отраслей × 3 компании × 20 новостей = 300 пар; каждая пятая — двум разметчикам (κ).
PLAN_SECTORS = ("agriculture_food", "trade_wholesale", "transport", "construction", "metallurgy")
PLAN_COMPANIES_PER_SECTOR = 3
PLAN_NEWS_PER_COMPANY = 20
PLAN_ROLES = ("cfo", "ceo", "owner")
OVERLAP_EVERY = 5


# --- метрики ---

def dcg(grades: list[int], k: int = K) -> float:
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades[:k]))


def ndcg(ranked_grades: list[int], k: int = K) -> float:
    ideal = dcg(sorted(ranked_grades, reverse=True), k)
    return dcg(ranked_grades, k) / ideal if ideal > 0 else 1.0


def precision(ranked_grades: list[int], k: int = K) -> float:
    top = ranked_grades[:k]
    return sum(g >= RELEVANT for g in top) / len(top) if top else 0.0


def irrelevant_top3(ranked_grades: list[int]) -> float:
    top = ranked_grades[:3]
    return sum(g == 0 for g in top) / len(top) if top else 0.0


def kappa(pairs: list[tuple[int, int]], classes: int = 4) -> float | None:
    """Квадратично взвешенная κ Коэна для двух разметчиков (оценки 0..classes-1)."""
    if len(pairs) < 2:
        return None
    observed = np.zeros((classes, classes))
    for a, b in pairs:
        observed[a, b] += 1
    observed /= observed.sum()
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0))
    weights = np.array([[(i - j) ** 2 for j in range(classes)] for i in range(classes)]) / (classes - 1) ** 2
    denom = (weights * expected).sum()
    return float(1 - (weights * observed).sum() / denom) if denom > 0 else 1.0


# --- признаки размеченных пар ---

def consensus(labels: list[dict]) -> dict[tuple, float]:
    """Средняя оценка пары по всем разметчикам: (news_id, company_id, role) → оценка."""
    grades: dict[tuple, list[int]] = defaultdict(list)
    for label in labels:
        grades[(label["news_id"], label["company_id"], label["role"])].append(int(label["grade"]))
    return {key: mean(g) for key, g in grades.items()}


def rows(labels: list[dict]) -> list[dict]:
    """Пары с признаками ранжирования; новости, которых нет в базе, пропускаются."""
    out = []
    for (news_id, company_id, role), grade in consensus(labels).items():
        news = store.get(news_id)
        if news is None or profiles.get(company_id) is None:
            continue
        x = ranking.features(news, company_id, role)
        out.append({"news_id": news_id, "company_id": company_id, "role": role, "grade": grade,
                    "x": np.array([x["multiplier"] * x["f"][k] for k in ranking.FEATURES])})
    return out


def _vector(weights: dict) -> np.ndarray:
    return np.array([float(weights[k]) for k in ranking.FEATURES])


def evaluate(data: list[dict], weights: dict) -> dict:
    """Метрики по запросам (компания, роль) и разрезы по отраслям и ролям."""
    w = _vector(weights)
    queries: dict[tuple, list[dict]] = defaultdict(list)
    for r in data:
        queries[(r["company_id"], r["role"])].append(r)
    per_query = []
    for (company_id, role), items in queries.items():
        ranked = sorted(items, key=lambda r: (-float(r["x"] @ w), r["news_id"]))
        grades = [round(r["grade"]) for r in ranked]
        sector = (profiles.get(company_id) or {}).get("sector", "unknown")
        per_query.append({"company_id": company_id, "role": role, "sector": sector,
                          "pairs": len(items), "ndcg@10": ndcg(grades), "precision@10": precision(grades),
                          "irrelevant_top3": irrelevant_top3(grades)})
    return {"summary": _summary(per_query), "by_sector": _slices(per_query, "sector"),
            "by_role": _slices(per_query, "role"), "queries": per_query}


def _summary(per_query: list[dict]) -> dict:
    if not per_query:
        return {"queries": 0}
    return {"queries": len(per_query), "pairs": sum(q["pairs"] for q in per_query),
            **{m: round(mean(q[m] for q in per_query), 4) for m in ("ndcg@10", "precision@10", "irrelevant_top3")}}


def _slices(per_query: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for q in per_query:
        groups[q[key]].append(q)
    names = SECTOR_NAMES if key == "sector" else ranking.ROLE_FOR
    return {names.get(k, k): _summary(v) for k, v in sorted(groups.items())}


# --- калибровка ---

def _pairs(data: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Разности признаков пар новостей одного запроса, где одна оценена выше другой (с весом разницы оценок)."""
    queries: dict[tuple, list[dict]] = defaultdict(list)
    for r in data:
        queries[(r["company_id"], r["role"])].append(r)
    diffs, gaps = [], []
    for items in queries.values():
        for a in items:
            for b in items:
                if a["grade"] > b["grade"]:
                    diffs.append(a["x"] - b["x"])
                    gaps.append(a["grade"] - b["grade"])
    width = len(ranking.FEATURES)
    return (np.array(diffs) if diffs else np.zeros((0, width))), np.array(gaps, dtype=float)


def fit(data: list[dict], prior: dict, l2: float = 1.0, steps: int = 400, lr: float = 0.05) -> dict:
    """Веса попарной логистической регрессии; L2 тянет к prior (ручным весам), веса не отрицательны."""
    w0 = _vector(prior)
    w = w0.copy()
    diffs, gaps = _pairs(data)
    if len(diffs) == 0:
        return dict(prior)
    for _ in range(steps):
        margin = diffs @ w
        p = 1 / (1 + np.exp(np.clip(margin, -30, 30)))  # вероятность ошибки порядка пары
        grad = -(diffs * (p * gaps)[:, None]).sum(axis=0) / gaps.sum() + l2 * (w - w0) / len(w0)
        w = np.maximum(0.0, w - lr * grad)
    return {k: round(float(v), 4) for k, v in zip(ranking.FEATURES, w)}


def cross_validate(data: list[dict], prior: dict, l2: float = 1.0) -> dict:
    """По компаниям: веса без компании → nDCG@10 на ней; сравнение с ручными весами на тех же компаниях."""
    companies = sorted({r["company_id"] for r in data})
    folds = []
    for held in companies:
        train = [r for r in data if r["company_id"] != held]
        test = [r for r in data if r["company_id"] == held]
        fitted = fit(train, prior, l2)
        folds.append({"company_id": held, "manual": evaluate(test, prior)["summary"].get("ndcg@10"),
                      "fitted": evaluate(test, fitted)["summary"].get("ndcg@10"), "weights": fitted})
    scored = [f for f in folds if f["manual"] is not None and f["fitted"] is not None]
    return {"folds": folds, "manual_ndcg": round(mean(f["manual"] for f in scored), 4) if scored else None,
            "fitted_ndcg": round(mean(f["fitted"] for f in scored), 4) if scored else None,
            "weights": fit(data, prior, l2)}


# --- план разметки ---

def plan() -> list[dict]:
    """300 пар для разметки: по 3 компании 5 отраслей (крупнейшие по выручке), по 20 новостей — 10 лучших
    по текущей ленте и 10 других деловых новостей (иначе в разметке не будет нерелевантных). Детерминирован."""
    companies = profiles.list_companies(limit=10**6)[1]
    news = [n for n in store.all_items() if n["classification"]["topics"]]
    pairs = []
    for sector in PLAN_SECTORS:
        chosen = sorted((c for c in companies if c["sector"] == sector), key=lambda c: (-(c["revenue"] or 0), c["company_id"]))
        for n, c in enumerate(chosen[:PLAN_COMPANIES_PER_SECTOR]):
            role = PLAN_ROLES[n % len(PLAN_ROLES)]
            top = [r["news"]["news_id"] for r in ranking.feed(news, c["company_id"], role, None, PLAN_NEWS_PER_COMPANY)]
            top = top[: PLAN_NEWS_PER_COMPANY // 2]
            rest = sorted((x["news_id"] for x in news if x["news_id"] not in top),
                          key=lambda i: hash_key(i, c["company_id"]))
            for news_id in (top + rest)[:PLAN_NEWS_PER_COMPANY]:
                pairs.append({"news_id": news_id, "company_id": c["company_id"], "role": role})
    for i, p in enumerate(pairs):
        p["overlap"] = i % OVERLAP_EVERY == 0
    return pairs


def hash_key(news_id: str, company_id: str) -> str:
    """Порядок «других» новостей для компании: перемешан, но одинаков при каждом вызове."""
    return hashlib.sha1(f"{company_id}:{news_id}".encode()).hexdigest()
