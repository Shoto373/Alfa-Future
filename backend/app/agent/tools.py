"""Инструменты агента: только чтение, явный реестр, аудит каждого вызова.

Агент (и LLM в режиме планирования) может вызвать лишь инструменты из
реестра с проверенными аргументами; вызовы ограничены бюджетом на запуск.
Инструменты не меняют данные и не обращаются в сеть.
"""

from dataclasses import dataclass
from typing import Callable

from app import embeddings, vectors
from app.agent import audit
from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES
from app.knowledge import kb
from app.news import store

# Обычный разбор — 7 обязательных вызовов + до 3 поисков, предложенных моделью, + 1 расширенный поиск
# при коррекции. Бюджет защищает от зацикливания плана, а не экономит деньги.
MAX_CALLS_PER_RUN = 20
STORY_SIMILARITY = 0.55  # сходство заголовков, с которого новости считаются одним сюжетом
STORY_CANDIDATES = 24  # ближайших заголовков из векторного хранилища
COVERAGE_MAX = 4  # сообщений других источников о том же событии


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: dict[str, type]
    fn: Callable[..., object]


def _profile(company_id: str) -> dict:
    c = profiles.get(company_id)
    if c is None:
        raise ToolError("Компания не найдена")
    keep = ("company_id", "display_name", "sector", "sector_name", "okved_code", "okved_name", "ownership", "age_years",
            "stage", "workers_fns", "client_type", "products", "fts_flag", "fts_countries", "revenue", "region", "city",
            "market", "group", "linked_persons", "affiliated_companies", "data_quality", "key_owner_mark")
    return {k: c.get(k) for k in keep}


def _exposures(company_id: str, topics: list[str]) -> list[dict]:
    wanted = set(topics)
    return [e for e in profiles.exposures(company_id) if not wanted or e["topic"] in wanted]


def _search(query: str, topics: list[str], sectors: list[str], include_stale: bool = False) -> list[dict]:
    return kb.search(query, topics, sectors, limit=6, include_stale=include_stale)


def _story(news_id: str) -> list[dict]:
    """Предыдущие события того же сюжета: близкие по смыслу и более ранние новости, от новых к старым."""
    current = store.get(news_id)
    if current is None:
        raise ToolError("Новость не найдена")
    main = {t["topic"] for t in current["classification"]["topics"][:2]}
    if not main:
        return []
    earlier = _story_by_vectors(current, main)
    if earlier is None:
        earlier = [n for n in store.all_items() if n["news_id"] != news_id and n["published_at"] < current["published_at"]
                   and main & {t["topic"] for t in n["classification"]["topics"]}]
        if not earlier:
            return []
        vectors_ = embeddings.embed([current["title"]] + [n["title"] for n in earlier])
        if vectors_ is not None:
            matrix = embeddings.as_matrix(vectors_)
            sims = matrix[1:] @ matrix[0]
            order = sorted(range(len(earlier)), key=lambda i: -sims[i])
            earlier = [earlier[i] for i in order if sims[i] >= STORY_SIMILARITY][:6]
    earlier.sort(key=lambda n: n["published_at"], reverse=True)
    return [{"news_id": n["news_id"], "title": n["title"], "lead": n["lead"][:300], "published_at": n["published_at"][:10],
             "source": n["source"], "magnitude": n["classification"].get("magnitude")} for n in earlier[:4]]


def _story_by_vectors(current: dict, main: set[str]) -> list[dict] | None:
    """Поиск в векторном хранилище (pgvector, HNSW) с фильтром по дате и темам; None — хранилище недоступно."""
    query = embeddings.embed([current["title"]])
    if query is None:
        return None
    found = vectors.nearest(vectors.NEWS, embeddings.as_matrix(query)[0], k=STORY_CANDIDATES,
                            exclude=[current["news_id"]], published_before=current["published_at"],
                            topics_any=sorted(main))
    if found is None:
        return None
    items = [store.get(item_id) for item_id, sim, _ in found if sim >= STORY_SIMILARITY]
    return [n for n in items if n is not None][:6]


def _coverage(news_id: str) -> list[dict]:
    """То же событие в других источниках (сюжет хранилища): сверка фактов и расхождений между СМИ."""
    info = store.story(news_id)
    if info is None:
        raise ToolError("Новость не найдена")
    current = store.get(news_id)
    others = [n for n in info["items"] if n["news_id"] != news_id and n["source"] != (current or {}).get("source")]
    return [{"news_id": n["news_id"], "title": n["title"], "lead": n["lead"][:400], "source": n["source"],
             "published_at": n["published_at"][:10], "url": n.get("url")} for n in others[-COVERAGE_MAX:]]


def _counterparties(company_id: str) -> dict:
    c = profiles.get(company_id)
    if c is None:
        raise ToolError("Компания не найдена")

    def side(d: dict) -> dict:
        return {
            "counterparties": d["counterparties"], "total_amount": d["total_amount"], "top1_share": d["top1_share"],
            "intra_group_share": d["intra_group_share"],
            "by_sector": [{"sector": SECTOR_NAMES.get(s["sector"], "вне выборки"), "share": round(s["share"], 3)}
                          for s in d["by_sector"]],
        }
    return {"suppliers": side(c["suppliers"]), "customers": side(c["customers"])}


def _products(company_id: str, topics: list[str]) -> list[dict]:
    c = profiles.get(company_id) or {}
    p = c.get("products", {})
    wanted = set(topics)
    out = []
    for prod in kb.products():
        if not wanted & set(prod["topics"]):
            continue
        needs = set(prod["needs"])
        if "has_credit" in needs and not p.get("loans"):
            continue
        if "fts" in needs and not c.get("fts_flag"):
            continue
        out.append(prod)
    return out[:3]


def _forecasts(topics: list[str]) -> list[dict]:
    out = []
    for t in topics:
        items = kb.latest_forecasts(t)
        series = {}
        for item in items:
            for metric, value in item.get("forecast_values", {}).items():
                series.setdefault(metric, []).append({"id": item["id"], "doc_id": item["doc_id"],
                    "date": item["doc_date"], "text": item["text"], "value": value})
        for metric, observations in series.items():
            observations.sort(key=lambda x: x["date"], reverse=True)
            tolerance = 0.5 if metric.startswith("usd_rub:") else 0.001
            latest = observations[0]
            different = [i for i in observations[1:] if abs(i["value"] - latest["value"]) > tolerance]
            if different:
                kind = "conflict" if any(i["date"] == latest["date"] for i in different) else "revision"
                base, horizon = metric.split(":", 1)
                metric_label = {"key_rate": "ключевой ставки", "avg_key_rate": "средней ключевой ставки",
                                "inflation": "инфляции", "usd_rub": "курса доллара"}.get(base, base)
                out.append({"topic": t, "metric": metric, "metric_label": f"{metric_label} на {horizon}",
                            "unit": "руб./$" if base == "usd_rub" else "%", "kind": kind, "items": [latest, different[0]]})
    return out


REGISTRY: dict[str, Tool] = {t.name: t for t in [
    Tool("get_company_profile", "Профиль компании: отрасль, масштаб, продукты банка, ВЭД, группа, качество данных",
         {"company_id": str}, _profile),
    Tool("get_exposures", "Чувствительность компании к темам новостей с обоснованием по признакам",
         {"company_id": str, "topics": list}, _exposures),
    Tool("search_bank_analytics", "Поиск тезисов аналитики Альфа-Банка (слова + смысл + темы + отрасли)",
         {"query": str, "topics": list, "sectors": list, "include_stale": bool}, _search),
    Tool("get_story_history", "Предыдущие события того же сюжета: тренд или разовое событие", {"news_id": str}, _story),
    Tool("get_story_coverage", "То же событие в других СМИ: сверка фактов и расхождений", {"news_id": str}, _coverage),
    Tool("get_counterparties", "Структура платежей: поставщики и покупатели по отраслям", {"company_id": str}, _counterparties),
    Tool("get_bank_products", "Подходящие продукты банка для темы и профиля", {"company_id": str, "topics": list}, _products),
    Tool("check_forecast_conflicts", "Прогнозы банка по теме из разных документов — проверка противоречий",
         {"topics": list}, _forecasts),
]}


class ToolRunner:
    """Выполняет вызовы инструментов агента с проверкой аргументов, бюджетом и аудитом."""

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.calls = 0

    def call(self, name: str, **args):
        tool = REGISTRY.get(name)
        if tool is None:
            audit.log(self.request_id, name, args, "denied", 0, "unknown tool")
            raise ToolError(f"Инструмент {name} не разрешен")
        if self.calls >= MAX_CALLS_PER_RUN:
            audit.log(self.request_id, name, args, "denied", 0, "call budget exceeded")
            raise ToolError("Превышен бюджет вызовов инструментов")
        clean = {}
        for key, typ in tool.args.items():
            if key in args:
                value = args[key]
                if not isinstance(value, typ):
                    raise ToolError(f"Аргумент {key} инструмента {name} имеет неверный тип")
                clean[key] = value
        unknown = set(args) - set(tool.args)
        if unknown:
            audit.log(self.request_id, name, args, "denied", 0, f"unknown args {sorted(unknown)}")
            raise ToolError(f"Лишние аргументы инструмента {name}: {sorted(unknown)}")
        self.calls += 1
        with audit.Timer() as t:
            try:
                result = tool.fn(**clean)
            except ToolError as exc:
                audit.log(self.request_id, name, clean, "error", 0, str(exc))
                raise
        audit.log(self.request_id, name, clean, "ok", t.ms)
        return result, t.ms
