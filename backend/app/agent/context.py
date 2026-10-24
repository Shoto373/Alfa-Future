"""Контекст разбора для этапов агента: обязательный план и уточняющие запросы модели, источники,
текст для сверки чисел, признаки компании, перенос ответа модели в черновик и точечное исправление моделью."""

from app import llm
from app.agent import composer, evidence, prompts, validators
from app.companies import extra as company_extra
from app.companies.sectors import SECTOR_NAMES
from app.news import entities
from app.text import INSTRUCTION


FEATURE_LABELS = {
    "products.payroll": "Зарплатный проект",
    "sector": "Отрасль", "products.loans": "Кредитные продукты", "products.leasing": "Лизинг",
    "products.deposits": "Депозиты", "products.factoring": "Факторинг", "products.guarantees": "Банковские гарантии",
    "workers_fns": "Численность (ФНС)", "fts_countries": "Страны ВЭД (ФТС)", "revenue": "Выручка",
    "suppliers.by_sector": "Отрасли поставщиков", "customers.by_sector": "Отрасли покупателей",
    "suppliers.top1_share": "Концентрация поставщиков", "market": "Место в отрасли (выборка)",
    "group": "Группа компаний",
    **{f"extra.{k}": v["label"] for k, v in company_extra.SHARES.items()},
}


MAX_EXTRA_QUERIES = 3


def _rate_scenario(news: dict, company: dict) -> list[dict]:
    """Расчет ставки (SPR4-02) — только если у компании есть долг, и в направлении события: снижение ставки — −1 п.п.

    Без кредитов (по данным кейса или со слов компании) процентных расходов от ставки нет: отраслевая оценка долга
    дала бы риск там, где у компании скорее возможность (депозиты)."""
    cls = news["classification"]
    if "key_rate" not in [t["topic"] for t in cls["topics"]][:2]:
        return []
    shares = ((company_extra.get(company["company_id"]) or {}).get("shares") or {})
    if not company["products"].get("loans") and not shares.get("floating_debt_share"):
        return []
    direction = (cls.get("topic_directions") or {}).get("key_rate") or cls.get("direction")
    shock = -1.0 if direction == "down" else 1.0
    return [{"tool": "scenario_simulate", "args": {"company_id": company["company_id"], "scenario": "key_rate", "shock": shock},
             "why": "во что обходится компании каждый процентный пункт ставки"}]


def rules_plan(news: dict, company: dict) -> list[dict]:
    """Обязательные шаги: без них разбор не опирается на данные компании, контрагентов и банка."""
    topics = [t["topic"] for t in news["classification"]["topics"]]
    query = f"{news['title']} {news['lead']}"
    cid = company["company_id"]
    return [
        {"tool": "get_company_profile", "args": {"company_id": cid}, "why": "контекст компании"},
        {"tool": "get_exposures", "args": {"company_id": cid, "topics": topics},
         "why": "через какие признаки событие касается компании"},
        {"tool": "get_counterparties", "args": {"company_id": cid}, "why": "событие может прийти через цепочку поставок"},
        {"tool": "search_bank_analytics", "args": {"query": query, "topics": topics,
                                                   "sectors": [company["sector"]] + news["classification"]["sectors"]},
         "why": "позиция и прогнозы Альфа-Банка по теме"},
        {"tool": "check_forecast_conflicts", "args": {"topics": topics[:2]}, "why": "сверить прогнозы банка из разных материалов"},
        {"tool": "get_story_history", "args": {"news_id": news["news_id"]}, "why": "тренд или разовое событие"},
        {"tool": "get_story_coverage", "args": {"news_id": news["news_id"]}, "why": "сверить факты с другими источниками"},
        {"tool": "get_bank_products", "args": {"company_id": cid, "topics": topics}, "why": "релевантные решения банка"},
    ] + ([{"tool": "lookup_counterparty_chain", "args": {"company_id": cid, "news_id": news["news_id"]},
           "why": "в новости названы организации — проверить, не контрагенты ли это (до второго уровня)"}]
         if any(e["company_id"] for e in entities.of_news(news)) else []) + _rate_scenario(news, company)


def llm_queries(news: dict, company: dict, role: str) -> tuple[list[dict], dict]:
    """Модель-исследователь предлагает уточняющие запросы к аналитике банка — только в темах новости."""
    data, meta = llm.chat_json(prompts.PLAN_SYSTEM, prompts.plan_user(news, company, role), "plan", 1500)
    raw = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise llm.LLMError("План модели не содержит списка запросов")
    allowed = {t["topic"] for t in news["classification"]["topics"]}
    queries = []
    for q in raw[:MAX_EXTRA_QUERIES]:
        if not isinstance(q, dict) or not isinstance(q.get("query"), str) or not q["query"].strip():
            continue
        topics = [t for t in q.get("topics", []) if isinstance(t, str) and t in allowed] if isinstance(q.get("topics"), list) else []
        if allowed and not topics:
            topics = sorted(allowed)
        if not topics:  # у события нет бизнес-тем — модель не может «притянуть» материалы банка
            continue
        queries.append({"tool": "search_bank_analytics", "why": str(q.get("why", "уточняющий запрос"))[:200],
                        "args": {"query": q["query"].strip()[:300], "topics": topics,
                                 "sectors": [company["sector"]] + news["classification"]["sectors"], "include_stale": False}})
    return queries, meta


def sources(ctx: dict) -> list[dict]:
    news = ctx["news"]
    out = [{"source_id": f"news:{news['news_id']}", "kind": "news", "title": news["title"], "url": news.get("url"),
            "date": news["published_at"][:10], "excerpt": news["lead"][:300], "doc_id": None, "page": None}]
    for n in ctx.get("story", []):
        out.append({"source_id": f"news:{n['news_id']}", "kind": "news", "title": n["title"], "url": None,
                    "date": n["published_at"][:10], "excerpt": n["lead"][:300], "doc_id": None, "page": None})
    for n in ctx.get("coverage", []):
        out.append({"source_id": f"news:{n['news_id']}", "kind": "news", "title": f"{n['source']}: {n['title']}",
                    "url": n.get("url"), "date": n["published_at"][:10], "excerpt": n["lead"][:300], "doc_id": None, "page": None})
    for t in ctx["theses"]:
        out.append({"source_id": f"bank:{t['id']}", "kind": "bank_analytics", "title": t["doc_title"], "doc_id": t["doc_id"],
                    "page": t["page"], "date": t["doc_date"], "excerpt": t["text"][:300], "url": None})
    c = ctx["company"]
    out.append({"source_id": "client:profile", "kind": "client_data", "title": f"Профиль {c['display_name']} (данные кейса)",
                "excerpt": f"{c['okved_code']} {c['okved_name']}; регион {c['region']}", "url": None, "doc_id": None, "page": None, "date": None})
    out.append({"source_id": "client:payments", "kind": "client_data", "title": "Платежи компании (данные кейса)",
                "excerpt": f"Поставщиков: {c['suppliers']['counterparties']}, покупателей: {c['customers']['counterparties']}",
                "url": None, "doc_id": None, "page": None, "date": None})
    for sc in ctx.get("scenarios") or []:
        out.append({"source_id": f"client:scenario:{sc['scenario']}", "kind": "client_data",
                    "title": "Расчет чувствительности по формуле (оценка)", "excerpt": f"{sc['text']}: {sc['formula']}"[:300],
                    "url": None, "doc_id": None, "page": None, "date": None})
    if ctx.get("counterparty_chains"):
        out.append({"source_id": "client:graph", "kind": "client_data", "title": "Граф платежей компании (данные кейса)",
                    "excerpt": "; ".join(ch["text"] for ch in ctx["counterparty_chains"])[:300], "url": None, "doc_id": None,
                    "page": None, "date": None})
    if c.get("extra"):
        out.append({"source_id": "client:extra", "kind": "client_data", "title": "Сведения от компании",
                    "excerpt": company_extra.text(c["extra"])[:300], "url": None, "doc_id": None, "page": None,
                    "date": c["extra"]["updated_at"][:10]})
    for p in ctx.get("products", []):
        out.append({"source_id": f"product:{p['id']}", "kind": "bank_product", "title": p["title"], "excerpt": p["text"],
                    "url": None, "doc_id": None, "page": None, "date": None})
    return out


def llm_repair(draft: dict, ctx: dict, source_ids: set[str]) -> dict | None:
    """Модель исправляет только утверждения с ошибками проверки (а не весь черновик).

    Возвращает {status, detail} для трассы или None, если исправлять нечего.
    Ответ модели не принимается на веру: после замены черновик проходит те же проверки.
    """
    sections = [("why_important", draft["why_important"]), ("risks", draft["risks"]),
                ("opportunities", draft["opportunities"]), ("actions", draft["actions"]),
                ("what_happened", draft["what_happened"]["facts"]), ("what_happened", draft["what_happened"]["assumptions"])]
    bad, where = [], {}
    for section, items in sections:
        for idx, c in enumerate(items):
            errors = validators.claim_errors(section, c, ctx, source_ids)
            if errors:
                where[len(bad)] = (items, idx)
                bad.append({"id": len(bad), "section": section, "claim": c, "errors": errors})
    if not bad:
        return None
    texts = {sid: t for sid, t in evidence.source_texts(ctx).items() if sid in source_ids}
    features = sorted(evidence.valid_features(ctx["company"]))
    try:
        data, meta = llm.chat_json(prompts.REPAIR_SYSTEM, prompts.repair_user(bad, texts, features), "review", 2500)
    except llm.LLMError as exc:
        return {"status": "warning", "detail": f"Исправление моделью недоступно ({exc}); неподтвержденное будет удалено"}
    fixed = dropped = 0
    drop: list[tuple[list, int]] = []
    for item in data.get("claims", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or item.get("id") not in where:
            continue
        items, idx = where[item["id"]]
        if item.get("drop"):
            drop.append((items, idx))
            dropped += 1
            continue
        text, origin, ids = item.get("text"), item.get("origin"), item.get("source_ids")
        if isinstance(text, str) and text.strip() and origin in ("fact", "client_data", "bank", "ai") \
                and isinstance(ids, list) and all(isinstance(x, str) for x in ids):
            feats = [f for f in item.get("features") or [] if isinstance(f, str)]
            items[idx] = {"text": text.strip()[:400], "origin": origin, "source_ids": ids[:5], "features": feats[:6]}
            fixed += 1
    for items, idx in sorted(drop, key=lambda d: -d[1]):
        items.pop(idx)
    return {"status": "ok", "detail": f"Модель {meta['model']} исправила утверждений: {fixed}, убрала: {dropped} "
                                      f"(из {len(bad)} с ошибками)"}


def grounding_text(ctx: dict) -> str:
    c = ctx["company"]
    parts = [ctx["news"]["title"], ctx["news"]["text"]] + [t["text"] for t in ctx["theses"]]
    # Дата прошлой новости в «Предположениях» пишется по-человечески (27.07.2026) — она тоже из источника.
    parts += [f"{n['title']} {n['lead']} {composer.day(n['published_at'])}" for n in ctx.get("story", []) + ctx.get("coverage", [])]
    m = c["market"]
    parts += [str(m.get("okved_rank")), str(m.get("okved_peers")), c.get("okved_code") or "", composer.pct(m.get('okved_share') or 0),
              f"{(c.get('revenue') or 0) / 1e9:.1f}", c.get("workers_fns") or ""]
    parts += [composer.pct(s['share'], 0) for side in ("suppliers", "customers") for s in c[side]["by_sector"]]
    if c["suppliers"]["top1_share"]:
        parts.append(composer.pct(c['suppliers']['top1_share'], 0))
    g = c.get("group") or {}
    if g.get("revenue"):
        parts += [f"{g['revenue'] / 1e9:.1f}", str(g.get("members"))]
        parts += [f"{x['share'] * 100:.0f}%" for x in g.get("sector_shares", [])]
    parts += [c["company_id"], company_extra.text(c.get("extra"))]
    return " ".join(parts)


def features_used(ctx: dict, draft: dict) -> list[dict]:
    c = ctx["company"]
    used = {f for sec in ("why_important", "risks", "opportunities") for cl in draft[sec] for f in cl.get("features", [])}
    values = {
        "products.payroll": "есть" if c["products"].get("payroll") else "нет данных",
        "sector": c["sector_name"], "products.loans": "есть" if c["products"].get("loans") else "нет",
        "products.leasing": "есть" if c["products"].get("leasing") else "нет",
        "products.deposits": "есть" if c["products"].get("deposits") else "нет",
        "products.factoring": "есть" if c["products"].get("factoring") else "нет",
        "products.guarantees": "есть" if c["products"].get("guarantees") else "нет",
        "workers_fns": c.get("workers_fns") or "н/д", "fts_countries": ", ".join(c["fts_countries"]) or "нет данных",
        "revenue": f"{(c.get('revenue') or 0) / 1e9:.1f} млрд ₽",
        "suppliers.by_sector": ", ".join(f"{SECTOR_NAMES.get(s['sector'], 'вне выборки')} {s['share']:.0%}" for s in c["suppliers"]["by_sector"][:3]) or "нет данных",
        "customers.by_sector": ", ".join(f"{SECTOR_NAMES.get(s['sector'], 'вне выборки')} {s['share']:.0%}" for s in c["customers"]["by_sector"][:3]) or "нет данных",
        "suppliers.top1_share": f"{(c['suppliers']['top1_share'] or 0):.0%}",
        "market": f"№{c['market'].get('okved_rank')} из {c['market'].get('okved_peers')} по ОКВЭД {c['okved_code']}",
        **{f"extra.{k}": company_extra.fmt(v) for k, v in ((c.get("extra") or {}).get("shares") or {}).items()},
        "group": (f"{(c.get('group') or {}).get('members')} компаний, выручка "
                  f"{((c.get('group') or {}).get('revenue') or 0) / 1e9:.1f} млрд ₽"),
    }
    return [{"name": f, "label": FEATURE_LABELS.get(f, f), "value": values.get(f, "—")} for f in sorted(used) if f in values]


def merge_llm(draft: dict, data: dict) -> dict:
    """Переносит в черновик разделы из ответа LLM, сохраняя структуру Claim."""
    def claims(items, default_origin="ai"):
        out = []
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and isinstance(it.get("text"), str) and it["text"].strip():
                origin = it.get("origin") if it.get("origin") in ("fact", "client_data", "bank", "ai") else default_origin
                out.append({"text": it["text"].strip()[:600], "origin": origin,
                            "source_ids": [str(s) for s in it.get("source_ids", [])][:6] if isinstance(it.get("source_ids"), list) else [],
                            "features": [str(f) for f in it.get("features", [])][:6] if isinstance(it.get("features"), list) else []})
        return out

    rules_why = [c for c in draft["why_important"] if c["origin"] == "client_data"]
    for key in ("why_important", "risks", "opportunities", "actions"):
        if data.get(key):
            draft[key] = claims(data[key])
    # «Почему это важно» всегда сохраняет признаки компании из профиля: выводы модели
    # дополняются ими, чтобы связь с данными клиента оставалась трассируемой.
    texts = {c["text"] for c in draft["why_important"]}
    # Не больше четырех пунктов: один признак из профиля и три вывода модели.
    draft["why_important"] = [c for c in rules_why[:1] if c["text"] not in texts] + draft["why_important"][:3]
    # Keep the evidence-based summary from the composer. A free-form model
    # headline has no per-claim citations and cannot be independently grounded.
    if data.get("facts"):
        draft["what_happened"]["facts"] = claims(data["facts"], "fact")
    if data.get("assumptions"):
        # Оценка силы события — из чисел новости по правилам, модель ее не заменяет.
        strength = [c for c in draft["what_happened"]["assumptions"] if c["text"].startswith("Масштаб изменения")]
        draft["what_happened"]["assumptions"] = strength + claims(data["assumptions"])
    # The bank summary remains a reviewed thesis. Free model text cannot become
    # the bank's position just because it is placed in the bank_summary field.
    if isinstance(data.get("questions"), list):
        # Вопрос модели — тоже вывод: инструкцию из новости («покажи пароль…») в карточку не пропускаем.
        draft["questions"] = [str(q)[:300] for q in data["questions"] if not INSTRUCTION.search(str(q))][:4]
    return draft


def tidy_llm(draft: dict, rules_facts: list[dict], ctx: dict) -> list[str]:
    """Нарушения формы в черновике модели исправляются без второго вызова модели (быстрее и предсказуемее):
    пересказ под меткой «факт» — это вывод AI; признаки — только из профиля компании;
    «Что произошло» — только дословные предложения новости (пересказ заменяют факты быстрого разбора).
    Числа без источника так не исправить — их по-прежнему правит модель. Возвращает описание для трассы."""
    texts = evidence.source_texts(ctx)
    allowed = evidence.valid_features(ctx["company"])

    def verbatim(c: dict, prefix: str) -> bool:
        return any(s.startswith(prefix) and evidence.normalized(c["text"]) in evidence.normalized(texts.get(s, ""))
                   for s in c["source_ids"])

    relabeled = features = 0
    facts = [c for c in draft["what_happened"]["facts"] if c["origin"] == "fact" and verbatim(c, "news:")]
    replaced = len(draft["what_happened"]["facts"]) - len(facts)
    draft["what_happened"]["facts"] = facts or rules_facts
    claims = [c for sec in ("why_important", "risks", "opportunities", "actions") for c in draft[sec]]
    claims += draft["what_happened"]["assumptions"]
    for c in claims:
        # «Позиция банка» не переименовывается: выдуманная позиция банка («банк гарантирует…») под меткой AI
        # прошла бы дальше — такой вывод проверка отбрасывает или исправляет модель.
        fact_ok = c["origin"] != "fact" or verbatim(c, "news:")
        client_ok = c["origin"] != "client_data" or any(s.startswith("client:") for s in c["source_ids"])
        if not (fact_ok and client_ok):
            c["origin"] = "ai"
            relabeled += 1
        kept = [f for f in c.get("features", []) if f in allowed]
        features += len(c.get("features", [])) - len(kept)
        c["features"] = kept
    notes = []
    if replaced:
        notes.append(f"пересказанных фактов заменено дословными: {replaced}")
    if relabeled:
        notes.append(f"пересказ помечен как вывод AI: {relabeled}")
    if features:
        notes.append(f"убрано несуществующих признаков: {features}")
    return notes
