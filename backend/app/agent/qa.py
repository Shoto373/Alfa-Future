"""Уточняющие вопросы по карточке: другой разрез данных, источники, позиция банка.

Режим правил распознает намерение вопроса и собирает ответ из карточки,
профиля компании и базы знаний. С LLM — ответ модели проходит ту же
проверку источников. Вопросы вне назначения сервиса отклоняются.
"""

import re

from app.agent import llm, prompts
from app.companies.sectors import SECTOR_NAMES
from app.knowledge import kb
from app.news.classifier import classify
from app.news import store

OFF_TOPIC = re.compile(r"(купить|продать)\s+(акци|облигац|валют)|пароль|номер карты|игнорируй\s+(инструкц|предыдущ)", re.I)

INTENTS = [
    ("sources", re.compile(r"источник|откуда|на чем основ|первоисточ|ссылк", re.I)),
    ("bank", re.compile(r"банк\w* (думает|считает|оценивает|позици|прогноз)|позиция банка|прогноз банка|альфа", re.I)),
    ("counterparties", re.compile(r"контрагент|поставщик|покупател|цепочк|платеж", re.I)),
    ("peers", re.compile(r"конкурент|отрасл|рынк|доля|сравни|место", re.I)),
    ("risks", re.compile(r"риск|угроз|опасн|потер", re.I)),
    ("opportunities", re.compile(r"возможност|выгод|плюс|заработ", re.I)),
    ("actions", re.compile(r"что делать|действ|рекоменд|шаг|предприн", re.I)),
    ("scenario", re.compile(r"если|сценари|что будет|а вдруг|прогноз", re.I)),
]


def _claim(text: str, origin: str, sources: list[str]) -> dict:
    return {"text": text, "origin": origin, "source_ids": sources, "features": []}


def _source(t: dict) -> dict:
    return {"source_id": f"bank:{t['id']}", "kind": "bank_analytics", "title": t["doc_title"], "doc_id": t["doc_id"],
            "page": t["page"], "date": t["doc_date"], "excerpt": t["text"][:300], "url": None}


def _rules_answer(insight: dict, company: dict, question: str) -> dict:
    intent = next((name for name, rx in INTENTS if rx.search(question)), "general")
    claims: list[dict] = []
    extra_sources: list[dict] = []

    if intent == "sources":
        for s in insight["sources"]:
            where = f", стр. {s['page']}" if s.get("page") else ""
            claims.append(_claim(f"{s['title']}{where}", "fact" if s["kind"] == "news" else
                                 "bank" if s["kind"] == "bank_analytics" else "client_data", [s["source_id"]]))
        answer = "Вывод опирается на следующие источники:"
    elif intent == "bank":
        claims = insight["bank_view"]["theses"][:4]
        answer = insight["bank_view"]["summary"] or "Материалы банка по этой теме не найдены."
        for c in insight["bank_view"]["conflicts"]:
            claims.append(_claim(c, "ai", [s for s in claims[0]["source_ids"]] if claims else ["client:profile"]))
    elif intent == "counterparties":
        for side, label in (("suppliers", "Поставщики"), ("customers", "Покупатели")):
            d = company[side]
            parts = ", ".join(f"{SECTOR_NAMES.get(s['sector'], 'вне выборки')} — {s['share']:.0%}" for s in d["by_sector"][:4])
            top1 = f"; крупнейший контрагент — {d['top1_share']:.0%} оборота" if d["top1_share"] else ""
            claims.append(_claim(f"{label}: {d['counterparties']} контрагентов. По отраслям: {parts or 'нет данных'}{top1}.",
                                 "client_data", ["client:payments"]))
        answer = "Структура платежей компании по данным кейса:"
    elif intent == "peers":
        m = company["market"]
        if m.get("okved_rank"):
            claims.append(_claim(f"По выручке компания №{m['okved_rank']} из {m['okved_peers']} среди компаний с ОКВЭД "
                                 f"{company['okved_code']} в выборке, доля {m['okved_share']:.1%}.", "client_data", ["client:profile"]))
        if m.get("sector_share"):
            claims.append(_claim(f"Доля в выручке отрасли «{company['sector_name']}» внутри выборки — {m['sector_share']:.1%}.",
                                 "client_data", ["client:profile"]))
        answer = "Положение компании в отрасли (только внутри набора данных кейса, не весь рынок):"
    elif intent in ("risks", "opportunities", "actions"):
        claims = insight[intent][:5]
        answer = {"risks": "Основные риски для компании:", "opportunities": "Возможности для компании:",
                  "actions": "Что можно сделать:"}[intent]
    else:
        cls = classify(question, question)
        found = kb.search(question, [t["topic"] for t in cls.topics], [company["sector"]], limit=3)
        claims = [_claim(t["text"], "bank", [f"bank:{t['id']}"]) for t in found]
        extra_sources = [_source(t) for t in found]
        if intent == "scenario":
            answer = "Сценарий зависит от прогнозов банка по теме вопроса:" if found else \
                "Для сценарного ответа не хватает материалов банка по этой теме."
        else:
            answer = "Нашел в материалах банка:" if found else \
                "В карточке и материалах банка нет ответа на этот вопрос. Попробуйте спросить про риски, источники, контрагентов или позицию банка."
    return {"answer": answer, "claims": claims, "extra_sources": extra_sources}


def answer(insight: dict, company: dict, question: str) -> dict:
    base = {"insight_id": insight["insight_id"], "question": question}
    if OFF_TOPIC.search(question):
        return base | {"answer": "Сервис объясняет влияние событий на бизнес и не дает индивидуальных инвестиционных "
                                 "рекомендаций и не работает с персональными данными.", "claims": [], "sources": [],
                       "mode": "rules", "refused": True}

    sources = {s["source_id"]: s for s in insight["sources"]}
    if llm.available():
        try:
            cls = classify(question, question)
            theses = kb.search(question, [t["topic"] for t in cls.topics], [company["sector"]], limit=4)
            data, _ = llm.chat_json(prompts.QA_SYSTEM, prompts.qa_user(insight, company, theses, question), "fast", 3000)
            for t in theses:
                sources.setdefault(f"bank:{t['id']}", _source(t))
            claims = []
            raw_claims = data.get("claims")
            if not isinstance(raw_claims, list):
                raise llm.LLMError("Ответ модели не содержит списка утверждений")
            for c in raw_claims:
                if not isinstance(c, dict):
                    continue
                ids = [s for s in c.get("source_ids", []) if isinstance(s, str) and s in sources] if isinstance(c.get("source_ids"), list) else []
                origin = c.get("origin") if c.get("origin") in ("fact", "client_data", "bank", "ai") else "ai"
                if ids and isinstance(c.get("text"), str):
                    from app.agent.validators import claim_errors
                    evidence_theses = {t["id"]: t for t in theses}
                    for sid in sources:
                        if sid.startswith("bank:"):
                            t = kb.thesis(sid[5:])
                            if t:
                                evidence_theses[t["id"]] = t
                    ctx = {"news": store.get(insight["news_id"]), "company": company,
                           "theses": list(evidence_theses.values()), "products": kb.products()}
                    cl = _claim(c["text"][:600], origin, ids)
                    if ctx["news"] and not claim_errors("answer", cl, ctx, set(sources)):
                        claims.append(cl)
            if not claims:
                raise llm.LLMError("Ответ не содержит подтвержденных утверждений")
            used = {i for c in claims for i in c["source_ids"]}
            return base | {"answer": "Ответ основан на перечисленных источниках:", "claims": claims,
                           "sources": [sources[i] for i in used], "mode": "llm", "refused": False}
        except llm.LLMError:
            pass

    result = _rules_answer(insight, company, question)
    for s in result["extra_sources"]:
        sources.setdefault(s["source_id"], s)
    used = {i for c in result["claims"] for i in c["source_ids"]}
    return base | {"answer": result["answer"], "claims": result["claims"],
                   "sources": [sources[i] for i in used if i in sources], "mode": "rules", "refused": False}
