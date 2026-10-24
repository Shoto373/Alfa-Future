"""Диалог с разбором (SPR4-05): уточнения с историей, расчеты и разрез по контрагентам — с источниками.

Планировщик определяет намерение вопроса: пояснить, посчитать, контрагенты, позиция банка, вне темы.
«Посчитать» и «контрагенты» отвечают инструменты агента (scenario_simulate, lookup_counterparty_chain,
search_bank_analytics) через тот же ToolRunner с бюджетом вызовов: числа — только из формул, модель их не считает.
«Пояснить» и «позиция банка» — помощник qa (с моделью, если она подключена, иначе правила).
Каждое утверждение ответа проходит validators.claim_errors; утверждение без подтвержденного источника отбрасывается.
История — до HISTORY реплик по разбору; старые реплики сворачиваются в короткое резюме.
"""

import re
import uuid

from sqlalchemy import select

from app import database
from app.agent import qa
from app.agent.tools import ToolError, ToolRunner
from app.agent.validators import claim_errors
from app.companies import graph
from app.knowledge import kb
from app.models import DialogTurn
from app.news import store
from app.scenarios import calc

HISTORY = 10
SUMMARY_MAX = 5  # в резюме — последние из свернутых реплик
TITLES = {"key_rate": "ключевая ставка", "fx": "курс рубля", "commodity": "цена сырья"}
PROFIT_TAX = 0.25  # ставка налога на прибыль в РФ с 2025 года
SCENARIO_WORDS = [
    ("key_rate", re.compile(r"ставк|процентн\w* расход|кредит|долг", re.I)),
    ("fx", re.compile(r"курс|рубл(ь|я|ю|ем)|ослабн|доллар|юан|евро|валют", re.I)),  # «в рублях» — не про курс
    ("commodity", re.compile(r"сырь|нефт|металл|стал|золот|цен\w* на", re.I)),
]
QUANTIFY = re.compile(r"сколько|во что обойд|в рублях|посчит|насколько|на сколько|налог|прибыл|п\.\s?п\.|"
                      r"\d+\s*(%|процент|п\.?п)|а если|что если|если ставк|если курс|если рубл|если цен", re.I)
OUT_OF_SCOPE = re.compile(r"погод|рецепт|анекдот|стих|футбол|гороскоп|напиши (код|письмо|эссе)|переведи|кто такой|"
                          r"сколько тебе лет|расскажи о себе", re.I)
SHOCK = re.compile(r"([+\-−–]?\s?\d+(?:[.,]\d+)?)\s*(п\.?\s?п|процентн\w* пункт|%|процент)", re.I)
DEFAULT_SHOCK = {"key_rate": 1.0, "fx": 10.0, "commodity": -10.0}
DOWN = re.compile(r"сниз|упад|подешев|укреп|уменьш|опуст", re.I)  # рубль укрепится — курс вниз
SUGGESTIONS = {
    "cfo": ["Как изменятся процентные расходы, если ставка вырастет на 1 п.п.?", "Как это повлияет на налог на прибыль?",
            "Что думает Альфа-Банк об этом событии?", "Как это затронет наших поставщиков и покупателей?"],
    "treasurer": ["Что будет, если рубль ослабнет на 10%?", "Как изменятся процентные расходы, если ставка вырастет на 1 п.п.?",
                  "Что думает Альфа-Банк о курсе и ставке?", "На чем основан этот вывод?"],
    "ceo": ["Как мы выглядим на фоне отрасли?", "Как это затронет наших поставщиков и покупателей?",
            "Какие возможности это открывает?", "Что делать в ближайшее время?"],
    "accountant": ["Как это повлияет на налог на прибыль?", "На чем основан этот вывод?",
                   "Какие риски это несет для компании?", "Что делать в ближайшее время?"],
    "owner": ["Какие риски это несет для компании?", "Как мы выглядим на фоне отрасли?",
              "Что думает Альфа-Банк об этом событии?", "Как это затронет наших поставщиков и покупателей?"],
}
CLIENT_SOURCES = {
    "client:profile": "Профиль компании (данные кейса)",
    "client:payments": "Платежи компании: поставщики и покупатели (данные кейса)",
    "client:graph": "Граф контрагентов по платежам (данные кейса)",
    "client:extra": "Сведения, которые сообщила компания",
}


def suggestions(role: str, asked: set[str] | None = None) -> list[str]:
    asked = asked or set()
    pool = SUGGESTIONS.get(role, SUGGESTIONS["owner"])
    fresh = [s for s in pool if s not in asked]
    return (fresh or pool)[:3]  # все вопросы роли уже заданы — подсказки повторяются, но не пропадают


# --- история ---

def history(insight_id: str, user_id: str) -> list[dict]:
    with database.session() as db:
        rows = db.scalars(select(DialogTurn).where(DialogTurn.insight_id == insight_id, DialogTurn.user_id == user_id)
                          .order_by(DialogTurn.id)).all()
        return [{"turn_id": r.id, "rating": r.rating, **r.payload} for r in rows]


def summary(turns: list[dict]) -> str:
    """Короткое резюме реплик старше последних HISTORY: тема и вопрос в несколько слов."""
    old = turns[:-HISTORY] if len(turns) > HISTORY else []
    return "; ".join(f"{t['intent']}: {t['question'][:60]}" for t in old[-SUMMARY_MAX:])


def _save(insight: dict, user_id: str, result: dict) -> int:
    with database.session() as db:
        row = DialogTurn(insight_id=insight["insight_id"], user_id=user_id, company_id=insight["company_id"], payload=result)
        db.add(row)
        db.flush()
        return row.id


def rate(insight_id: str, user_id: str, turn_id: int, rating: int) -> bool:
    with database.session() as db:
        row = db.get(DialogTurn, turn_id)
        if row is None or row.insight_id != insight_id or row.user_id != user_id:
            return False
        row.rating = rating
        return True


# --- планировщик ---

def plan(question: str, turns: list[dict]) -> str:
    """Намерение: off_topic | quantify | counterparties | bank | explain."""
    if qa.OFF_TOPIC.search(question) or OUT_OF_SCOPE.search(question):
        return "off_topic"
    if QUANTIFY.search(question):
        return "quantify"
    intent = next((name for name, rx in qa.INTENTS if rx.search(question)), "general")
    if intent == "counterparties":
        return "counterparties"
    if intent == "bank":
        return "bank"
    if intent == "scenario":
        return "quantify"
    # Короткое продолжение («а в рублях?», «а по году?») — то же намерение, что у прошлой реплики.
    if turns and len(question.split()) <= 4 and turns[-1]["intent"] in ("quantify", "counterparties"):
        return turns[-1]["intent"]
    return "explain"


def _scenario_kind(question: str, insight: dict, turns: list[dict]) -> str:
    for kind, rx in SCENARIO_WORDS:
        if rx.search(question):
            return kind
    previous = next((t["scenario"] for t in reversed(turns) if t.get("scenario")), None)
    if previous:
        return previous
    topics = {r.get("topic") for r in insight["relevance"]["reasons"]}
    if "fx" in topics:
        return "fx"
    if topics & {"fuel_oil", "metals_steel", "gold"}:
        return "commodity"
    return "key_rate"


def _shock(question: str, kind: str, turns: list[dict]) -> float:
    m = SHOCK.search(question)
    if m:
        value = float(m.group(1).replace(" ", "").replace(",", ".").replace("−", "-").replace("–", "-"))
        if value > 0 and DOWN.search(question):
            value = -value
        return value
    previous = next((t for t in reversed(turns) if t.get("scenario") == kind and t.get("shock") is not None), None)
    return previous["shock"] if previous else DEFAULT_SHOCK[kind]


# --- ответы инструментов ---

def _claim(text: str, origin: str, sources: list[str]) -> dict:
    return {"text": text, "origin": origin, "source_ids": sources, "features": []}


def _quantify(insight: dict, company: dict, question: str, turns: list[dict], runner: ToolRunner) -> dict:
    kind = _scenario_kind(question, insight, turns)
    low, high = calc.LIMITS[kind]
    shock = max(low, min(high, _shock(question, kind, turns)))
    result, _ = runner.call("scenario_simulate", company_id=company["company_id"], scenario=kind, shock=shock)
    if not result["ok"]:
        return {"answer": f"{result['message']}. Укажите недостающие данные в блоке «Что если» на странице компании — "
                          "и я посчитаю.", "claims": [], "refused": True, "scenario": kind, "shock": shock, "evidence": {}}
    sid = f"client:scenario:{kind}"
    claims = [_claim(result["text"], "client_data", [sid]), _claim(f"Расчет: {result['formula']}", "client_data", [sid])]
    evidence = f"{result['text']} {result['formula']}"
    if re.search(r"налог|прибыл", question, re.I) and result["effect_rub"]:
        tax = -result["effect_rub"] * PROFIT_TAX
        tax_text = (f"Налог на прибыль {'снизится' if tax < 0 else 'вырастет'} ≈ на {calc.mln(tax)} в год: "
                    f"изменение прибыли до налога {calc.mln(result['effect_rub'])} × ставка налога 25%")
        claims.append(_claim(tax_text, "client_data", [sid]))
        evidence += f" {tax_text}"
    claims += [_claim(c, "client_data", [sid]) for c in result["caveats"][:1]]
    evidence += " " + " ".join(result["caveats"][:1])
    return {"answer": "Посчитал по прозрачной формуле (оценка чувствительности, не прогноз):", "claims": claims,
            "refused": False, "scenario": kind, "shock": shock,
            "evidence": {sid: evidence}, "titles": {sid: f"Расчет «что если»: {TITLES[kind]}"}}


def _counterparties(insight: dict, company: dict, runner: ToolRunner) -> dict:
    chains, _ = runner.call("lookup_counterparty_chain", company_id=company["company_id"], news_id=insight["news_id"])
    claims = [_claim(f"В новости названа компания из вашей цепочки: {c['text']}", "client_data", ["client:graph"])
              for c in chains]
    top = graph.neighbors(company["company_id"])
    first = [n for n in top if n["level"] == 1][:3]
    second = [n for n in top if n["level"] == 2][:2]
    if first:
        claims.append(_claim("Главные контрагенты по платежам: " + "; ".join(n["text"] for n in first), "client_data",
                             ["client:graph"]))
    if second:
        claims.append(_claim("Второй уровень цепочки: " + "; ".join(n["text"] for n in second), "client_data", ["client:graph"]))
    rules = qa.rules_answer(insight, company, "контрагенты")
    claims += rules["claims"]
    text = " ".join(c["text"] for c in claims if c["source_ids"] == ["client:graph"])
    answer = ("Событие касается вашей цепочки поставок:" if chains else
              "В новости не названы ваши контрагенты. Структура платежей и цепочки поставок по данным кейса:")
    return {"answer": answer, "claims": claims, "refused": False, "evidence": {"client:graph": text}}


def _bank(insight: dict, company: dict, question: str, runner: ToolRunner) -> dict:
    topics = [r["topic"] for r in insight["relevance"]["reasons"] if r.get("topic")] or []
    found, _ = runner.call("search_bank_analytics", query=question, topics=topics, sectors=[company["sector"]])
    rules = qa.rules_answer(insight, company, "позиция банка")
    claims = rules["claims"] + [_claim(t["text"], "bank", [f"bank:{t['id']}"]) for t in found[:2]]
    return {"answer": rules["answer"], "claims": claims, "refused": False, "extra_sources": [qa.source_of(t) for t in found[:2]],
            "theses": found}


# --- сборка ответа ---

def _sources(insight: dict, result: dict) -> dict[str, dict]:
    sources = {s["source_id"]: s for s in insight["sources"]}
    for s in result.get("extra_sources", []):
        sources.setdefault(s["source_id"], s)
    for sid, text in result.get("evidence", {}).items():
        sources.setdefault(sid, {"source_id": sid, "kind": "client_data", "title": result.get("titles", {}).get(sid, CLIENT_SOURCES.get(sid, sid)),
                                 "url": None, "doc_id": None, "page": None, "date": None, "excerpt": text[:300]})
    for sid, title in CLIENT_SOURCES.items():
        sources.setdefault(sid, {"source_id": sid, "kind": "client_data", "title": title, "url": None, "doc_id": None,
                                 "page": None, "date": None, "excerpt": None})
    return sources


def _verified(insight: dict, company: dict, result: dict, sources: dict[str, dict]) -> list[dict]:
    """Утверждения инструментов — через те же проверки, что разбор: источник, числа, происхождение."""
    theses = {t["id"]: t for t in result.get("theses", [])}
    for sid in sources:
        if sid.startswith("bank:") and sid[5:] not in theses:
            t = kb.thesis(sid[5:])
            if t:
                theses[t["id"]] = t
    evidence = result.get("evidence", {})
    ctx = {"news": store.get(insight["news_id"]), "company": company, "theses": list(theses.values()), "products": kb.products(),
           "scenarios": [{"scenario": sid.split(":")[-1], "text": text, "formula": ""}
                         for sid, text in evidence.items() if sid.startswith("client:scenario:")],
           "counterparty_chains": [{"text": evidence["client:graph"]}] if evidence.get("client:graph") else []}
    if ctx["news"] is None:
        return []
    return [c for c in result["claims"] if not claim_errors("answer", c, ctx, set(sources))]


def answer(insight: dict, company: dict, question: str, user_id: str, role: str) -> dict:
    turns = history(insight["insight_id"], user_id)
    intent = plan(question, turns)
    asked = {t["question"] for t in turns} | {question}
    base = {"insight_id": insight["insight_id"], "question": question, "intent": intent}
    runner = ToolRunner(f"dialog_{uuid.uuid4().hex[:12]}")
    if intent == "off_topic":
        result = {"answer": "Я отвечаю только на вопросы об этом событии и его влиянии на компанию: риски, расчеты, "
                            "контрагенты, позиция банка. Попробуйте один из вопросов ниже.", "claims": [], "sources": [], "refused": True,
                  "mode": "rules"}
    elif intent == "explain":
        result = qa.answer(insight, company, question)
    else:
        try:
            step = {"quantify": lambda: _quantify(insight, company, question, turns, runner),
                    "counterparties": lambda: _counterparties(insight, company, runner),
                    "bank": lambda: _bank(insight, company, question, runner)}[intent]()
        except ToolError:
            step = {"answer": "Не удалось получить данные для ответа. Попробуйте переформулировать вопрос.", "claims": [],
                    "refused": True}
        sources = _sources(insight, step)
        claims = _verified(insight, company, step, sources)
        if not claims and not step["refused"]:
            step |= {"answer": "Не нашел подтвержденного ответа в данных компании и материалах банка.", "refused": True}
        used = {i for c in claims for i in c["source_ids"]}
        result = {"answer": step["answer"], "claims": claims, "sources": [sources[i] for i in used if i in sources],
                  "mode": "rules", "refused": step["refused"], **{k: step[k] for k in ("scenario", "shock") if k in step}}
    if intent == "explain":  # у ответов помощника тоже каждый источник — в списке источников
        sources = _sources(insight, {"extra_sources": result["sources"]})
        result["claims"] = [c for c in result["claims"] if set(c["source_ids"]) <= set(sources)]
        result["sources"] = [sources[i] for i in {i for c in result["claims"] for i in c["source_ids"]}]
        if not result["claims"] and not result["refused"]:  # ответ без подтвержденных утверждений — подсказка, а не вывод
            result |= {"answer": "В разборе этого события нет подтвержденного вывода на эту тему. "
                                 "Спросите про риски, расчет в рублях, контрагентов или позицию банка.", "refused": True}
    out = base | {k: v for k, v in result.items() if k not in ("insight_id", "question")}
    out["turn_id"] = _save(insight, user_id, out)
    out["suggestions"] = suggestions(role, asked)
    out["history_summary"] = summary(turns + [out])
    return out
