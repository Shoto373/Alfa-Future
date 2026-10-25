"""Составление интерпретации без LLM (режим правил) из собранного агентом контекста.

Логика: эффект = знак чувствительности компании × направление события.
Отрицательный эффект — риск, положительный — возможность, неоднозначный —
и то и другое с условием. Каждое утверждение несет origin и source_ids;
цифры берутся только из новости, тезисов банка и данных компании.
"""

from app.companies import supply
from app.companies.profiles import _bn, group, group_mix
from app.companies.sectors import SECTOR_NAMES, SECTOR_SENSITIVITY
from app.domain_config.runtime import ACTIONS, DIRECTION_VALUE, QUESTIONS, TOPIC_EFFECT, TOPIC_EFFECT_DOWN
from app.scenarios.calc import mln as scenario_mln
from app.news.taxonomy import TOPICS
from app.ranking import ROLES

# Знак направления по теме (DIRECTION_VALUE), формулировки эффекта (TOPIC_EFFECT, TOPIC_EFFECT_DOWN), действия
# по ролям (ACTIONS) и уточняющие вопросы (QUESTIONS) — данные: backend/config/sectors/topics.yaml (SPR4-00).
# hold по ставке = деньги остаются дорогими (как в примере кейса): direction_value.hold = 0.6.

WHY_MAX = 3  # пунктов в «Почему это важно»

ORIGIN_SOURCE = {"client_data": "client:profile", "payments": "client:payments", "sector_model": "client:profile",
                 "company_reported": "client:extra", "group": "client:profile"}

# Оговорки, когда знак влияния зависит от операций компании: такие выводы не задают общий знак события.
HEDGED_RISK, HEDGED_OPP = ". Касается компании: ", " — если ситуация сложится в пользу компании."


def overall_effect(card: dict) -> str:
    """Общий знак события для компании по итоговым разделам разбора (метка в ленте и шапке разбора).

    neg — скорее риск, pos — скорее возможность, mixed — и то и другое, unclear — зависит от операций
    компании (только оговорки), none — влияния на бизнес не найдено.
    """
    if not card["risks"] and not card["opportunities"]:
        return "none"
    risk = any(HEDGED_RISK not in c["text"] for c in card["risks"])
    opp = any(HEDGED_OPP not in c["text"] for c in card["opportunities"])
    return "mixed" if risk and opp else "neg" if risk else "pos" if opp else "unclear"


def _claim(text: str, origin: str, sources: list[str], features: list[str] | None = None) -> dict:
    return {"text": text, "origin": origin, "source_ids": sources, "features": features or []}


def _effect(topic: str, direction: str | None, sign: int) -> float:
    if sign == 0 or direction is None:
        return 0.0
    return sign * DIRECTION_VALUE.get(topic, {}).get(direction, 0)


def side_effect(e: dict, topic: str, direction: str | None) -> float | None:
    """Эффект признака компании на событие с учетом стороны цепочки поставок; None — признак в выводах не участвует.

    Знак признака — по-прежнему чувствительность отрасли контрагента к теме: эффект = sign × DIRECTION_VALUE.
    Покупатели: их проигрыш — риск для компании (спрос и выручка падают, дебиторка растет), выигрыш — возможность.
    Поставщики: их проигрыш — риск перебоев поставок и роста закупочных цен; выигрыш отрасли поставщика
    возможностью для компании не является (рост цен на его продукцию — скорее издержка), поэтому не засчитывается."""
    eff = _effect(topic, direction, e["sign"])
    if e.get("side") == "suppliers" and eff > 0:
        return None
    return eff


def effect_terms(topic: str, direction: str | None, features: set[str] | None = None) -> tuple[str, str]:
    if topic == "key_rate":
        features = features or set()
        funding = "новых заимствований" if "products.loans" in features else "отраслевого финансирования"
        if "products.leasing" in features:
            funding = "новых заимствований и лизинга" if "products.loans" in features else "нового лизингового финансирования"
        if direction == "down":
            return ("доходность нового размещения ликвидности может снизиться",
                    f"стоимость {funding} может снизиться; эффект для действующих договоров зависит от их условий")
        if direction == "up":
            return (f"стоимость {funding} может вырасти", "доходность нового размещения ликвидности может вырасти")
        return (f"стоимость {funding} остается высокой",
                "доходность размещения свободных денег остается высокой")
    if direction == "down":
        return TOPIC_EFFECT_DOWN.get(topic, TOPIC_EFFECT[topic])
    return TOPIC_EFFECT[topic]


def _assumptions(ctx: dict, cls: dict, news_src: str) -> list[dict]:
    """Предположения: неясное направление, продолжение сюжета, масштаб изменения."""
    assumptions = []
    if cls["direction"] is None:
        assumptions.append(_claim("Из текста новости не ясно, в какую сторону изменится ситуация, поэтому ниже оба варианта: и риск, и возможность.", "ai", [news_src]))
    # История сюжета: тренд или разовое событие — по последним предыдущим новостям того же сюжета.
    story = ctx.get("story") or []
    if story:
        latest = story[0]
        tail = ", до этого были и другие события по теме" if len(story) > 1 else ""  # без цифр: число не из источника
        assumptions.append(_claim(f"Это продолжение истории: {day(latest['published_at'])} уже была новость «{latest['title']}»{tail}.", "ai",
                                  [f"news:{n['news_id']}" for n in story[:3]]))
    strength = cls.get("magnitude")
    if strength and strength.get("evidence"):
        # Сила события: цитата из новости, поэтому числа в утверждении подтверждаются ее текстом.
        assumptions.append(_claim(f"Масштаб изменения: {strength['label']}, в новости — «{strength['evidence']}».", "ai", [news_src]))
    return assumptions


def _why_important(exposures: list[dict], company: dict, event: str, news_src: str) -> list[dict]:
    """Почему важно: сначала суть новости и главная связь с компанией, затем остальные признаки — как дополнение."""
    why, seen = [], set()
    top = max(exposures, key=lambda x: x["weight"]) if exposures else None
    if top:
        why.append(_claim(f"В новости: «{event}». Для компании это важно: {_why(top)}.",
                          "ai", [news_src, ORIGIN_SOURCE.get(top["origin"], "client:profile")], [top["feature"]]))
        seen.add(top["feature"])
    # Не больше трех пунктов: остальные признаки видны в таблице «Признаки компании» ниже.
    for e in sorted(exposures, key=lambda x: x["weight"], reverse=True):
        if e["feature"] in seen or len(why) >= WHY_MAX:
            continue
        seen.add(e["feature"])
        why.append(_claim(_cap(_why(e)), "ai" if e["origin"] == "sector_model" else "client_data",
                          [ORIGIN_SOURCE.get(e["origin"], "client:profile")], [e["feature"]]))
    # Группа компаний: событие оценивается не только для юрлица, но и для группы, в которую оно входит.
    g = group(company)
    if g and exposures and "group" not in seen and len(why) < WHY_MAX:
        why.append(_claim(f"Входит в группу из {g['members']} компаний ({_bn(g['revenue'])}; {group_mix(g)}) — "
                          "эффект стоит оценивать для всей группы.", "client_data", ["client:profile"], ["group"]))
    if exposures and company["market"].get("okved_rank") and company["market"].get("okved_peers") and len(why) < WHY_MAX:
        m = company["market"]
        why.append(_claim(f"№{m['okved_rank']} из {m['okved_peers']} по выручке в отрасли (ОКВЭД {company['okved_code']}), "
                          f"доля {pct(m['okved_share'])} в выборке.", "client_data", ["client:profile"], ["market"]))
    if not why:
        why.append(_claim(f"Прямых признаков чувствительности компании к теме не найдено. По доступным данным отрасли «{company['sector_name']}» нельзя уверенно оценить влияние.",
                          "ai", ["client:profile"], ["sector"]))
    return why


def _topic_claims(t: str, exps: list[dict], d: str | None, theses: list[dict], news_src: str,
                  used_why: set[str]) -> tuple[list[dict], list[dict]]:
    """Риски и возможности одной темы: один вывод на знак эффекта, объединяющий признаки компании.

    used_why — причины, уже названные в других темах: одна и та же причина не повторяется.
    """
    risks, opps = [], []
    neg, pos = effect_terms(t, d, {e["feature"] for e in exps})
    groups = {"neg": [], "pos": [], "amb": []}
    for e in exps:
        eff = side_effect(e, t, d)
        if eff is None:
            continue
        groups["neg" if eff < 0 else "pos" if eff > 0 else "amb"].append(e)
    forecast = next((th for th in sorted(theses, key=lambda x: x["doc_date"], reverse=True)
                     if t in th["topics"] and th.get("stance") == "forecast" and not th.get("stale")), None)
    horizon = f" Горизонт по прогнозу банка: {_first_sentence(forecast['text'])}" if forecast else ""
    extra = [f"bank:{forecast['id']}"] if forecast else []

    def basis(items):
        srcs = [news_src] + sorted({ORIGIN_SOURCE.get(e["origin"], "client:profile") for e in items}) + extra
        return srcs, [e["feature"] for e in items[:3]]

    def because(items):
        # Признак компании объясняет, почему событие касается именно ее; одна и та же причина не повторяется.
        e = next((x for x in items if _why(x) not in used_why), items[0])
        used_why.add(_why(e))
        return _why(e)

    topic_name = TOPICS.get(t, {}).get("name", t)
    if groups["neg"]:
        srcs, feats = basis(groups["neg"])
        risks.append(_claim(f"{_cap(neg)}: {because(groups['neg'])}.{horizon}", "ai", srcs, feats))
    if groups["pos"]:
        srcs, feats = basis(groups["pos"])
        opps.append(_claim(f"{_cap(pos)}: {because(groups['pos'])}.{horizon}", "ai", srcs, feats))
    if groups["amb"]:
        # Направление неясно: риск — с причиной, возможность — короткой строкой, без повтора той же причины.
        srcs, feats = basis(groups["amb"])
        if not groups["neg"]:
            risks.append(_claim(f"«{topic_name}»: {neg}{HEDGED_RISK}{because(groups['amb'])}.", "ai", srcs, feats))
        if not groups["pos"]:
            opps.append(_claim(f"«{topic_name}»: {pos}{HEDGED_OPP}", "ai", srcs, feats))
    return risks, opps


def _bank_view(ctx: dict, theses: list[dict]) -> dict:
    """Позиция банка: тезисы, резюме и расхождения или пересмотры прогнозов между материалами."""
    bank_claims = [_claim(t["text"], "bank", [f"bank:{t['id']}"]) for t in theses[:4]]
    conflicts = []
    for conflict in ctx.get("forecast_conflicts", []):
        items = conflict["items"]
        if len(items) > 1:
            label = "Пересмотр прогноза" if conflict.get("kind") == "revision" else "Расхождение прогнозов"
            unit = conflict.get("unit", "")
            conflicts.append(f"{label} {conflict.get('metric_label', conflict['topic'])}: "
                             f"{items[-1].get('value')} {unit} в материале от {items[-1]['date']} → "
                             f"{items[0].get('value')} {unit} в материале от {items[0]['date']}.")
    bank_summary = theses[0]["text"] if theses else None
    if theses and any(t.get("stale") for t in theses[:2]):
        conflicts.append("Часть найденных материалов банка устарела (2021 г.) — они приведены только как пример логики оценки.")
    return {"available": bool(theses), "summary": bank_summary, "theses": bank_claims, "conflicts": conflicts}


def _headline(company: dict, topics: list[str], by_topic: dict[str, list[dict]], cls: dict, theses: list[dict]) -> str:
    """Сводная мысль: событие -> главный плюс и минус для компании -> позиция банка."""
    direction, topic_dirs = cls["direction"], cls.get("topic_directions") or {}
    who = company["display_name"].replace("Компания ", "")
    main = next((t for t in topics if t in TOPIC_EFFECT and by_topic.get(t)), None)
    if main:
        neg, pos = effect_terms(main, topic_dirs.get(main, direction), {e["feature"] for e in by_topic[main]})
        effs = [x for x in (side_effect(e, main, topic_dirs.get(main, direction)) for e in by_topic[main]) if x is not None]
        if any(x < 0 for x in effs) and any(x > 0 for x in effs):
            headline = f"{who}: есть и минус, и плюс — {neg}, но {pos}."
        elif any(x < 0 for x in effs):
            headline = f"{who}: {neg}."
        elif any(x > 0 for x in effs):
            headline = f"{who}: {pos}."
        else:
            headline = (f"{who}: эффект новости по теме «{TOPICS.get(main, {}).get('name', main)}» пока неоднозначен — "
                        f"{neg} или, наоборот, {pos}.")
    else:
        headline = f"{who}: прямой связи с событием по имеющимся данным не видно."
    return headline


def _actions(topics: list[str], role: str, company: dict, theses: list[dict], news_src: str) -> list[dict]:
    """Действия по роли: до двух на тему из библиотеки, только доступные компании по ее продуктам."""
    actions = []
    for t in topics[:3]:
        lib = ACTIONS.get(t, {})
        options = [a if isinstance(a, tuple) else (a, None) for a in (lib.get(role) or lib.get("default") or [])]
        for text, needs in [o for o in options if _eligible(o[1], company)][:2]:
            actions.append(_claim(text, "ai", [news_src, "client:profile"] + ([f"bank:{theses[0]['id']}"] if theses else [])))
    if not actions:
        actions = [_claim(ACTIONS["default"]["default"][0][0], "ai", [news_src])]
    return _dedupe(actions)[:4]


MAX_SUPPLY_CLAIMS = 2


def _news_effect_on_sector(cls: dict, sector: str) -> float:
    """Как событие меняет положение отрасли контрагента: чувствительность отрасли × направление по темам новости."""
    topic_dirs = cls.get("topic_directions") or {}
    total = 0.0
    for t in [x["topic"] for x in cls["topics"]][:3]:
        sens = SECTOR_SENSITIVITY.get(t, {}).get(sector)
        direction = topic_dirs.get(t, cls["direction"])
        if sens and direction:
            total += _effect(t, direction, sens.sign)
    return total


def _supply_chain(ctx: dict, news_src: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Риски, возможности и действия по цепочке поставок: новость про отрасль, куда уходят платежи клиента
    или откуда приходят его поступления. Только агрегаты по платежам клиента (отрасль, доля, концентрация);
    конкретные контрагенты не называются. Проблема покупателя — риск выручки и дебиторки, проблема
    поставщика — риск перебоев поставок и роста закупочных цен (правило знаков — в side_effect)."""
    company, cls = ctx["company"], ctx["news"]["classification"]
    risks, opps, actions = [], [], []
    links = sorted((x for x in supply.links(company) if x["sector"] in cls["sectors"]), key=lambda x: -x["share"])
    srcs = [news_src, "client:payments"]
    for link in links[:MAX_SUPPLY_CLAIMS]:
        eff = _news_effect_on_sector(cls, link["sector"])
        side, name = link["side"], SECTOR_NAMES.get(link["sector"], link["sector"])
        who = supply.SIDE_WORD[side]
        feature = [f"{side}.by_sector"]
        head = f"Через ваших {who}: {supply.share_text(link)} — отрасль «{name}»"
        top1 = (company.get(side) or {}).get("top1_share")
        concentration = top1 is not None and top1 > 0.5
        if side == "suppliers" and eff < 0:
            risks.append(_claim(f"{head}; ситуация в ней ухудшается — возможны перебои поставок и рост закупочных цен.",
                                "ai", srcs, feature))
            actions.append(_claim(f"Проверить альтернативных поставщиков в отрасли «{name}» и запас критичных материалов "
                                  "на ближайший период", "ai", srcs))
            if concentration:
                actions.append(_claim(f"Оценить зависимость от крупнейшего поставщика ({pct(top1, 0)} платежей поставщикам): "
                                      "проработать резервный источник поставок", "ai", srcs, ["suppliers.top1_share"]))
        elif side == "customers" and eff < 0:
            risks.append(_claim(f"{head}; ситуация в ней ухудшается — возможны снижение спроса и выручки, "
                                "рост дебиторской задолженности и задержек оплаты.", "ai", srcs, feature))
            actions.append(_claim(f"Пересмотреть лимиты и сроки отсрочки покупателям из отрасли «{name}» и проверить "
                                  "дебиторскую задолженность", "ai", srcs))
            if concentration:
                actions.append(_claim(f"Оценить зависимость от крупнейшего покупателя ({pct(top1, 0)} поступлений): "
                                      "проработать диверсификацию выручки и защиту дебиторской задолженности", "ai", srcs,
                                      ["customers.top1_share"]))
        elif side == "customers" and eff > 0:
            opps.append(_claim(f"{head}; ситуация в ней улучшается — спрос покупателей может вырасти.", "ai", srcs, feature))
            actions.append(_claim(f"Проверить, хватает ли запасов и мощностей для роста заказов от покупателей из отрасли «{name}»",
                                  "ai", srcs))
    return risks, opps, actions


CHAIN_LABEL = {"supplier": "поставщика", "customer": "покупателя", "person": "возможно связанную компанию"}


def _chain_claims(ctx: dict, news_src: str) -> list[dict]:
    """Новость о контрагенте (SPR4-01): цепочка «вы → поставщик → его поставщик» из графа платежей."""
    out = []
    for ch in (ctx.get("counterparty_chains") or [])[:2]:
        level = "второго уровня " if ch["level"] == 2 else ""
        out.append(_claim(f"Новость касается вашего {level}{CHAIN_LABEL[ch['relation']]}: {ch['text']}", "client_data",
                          [news_src, "client:graph"]))
    return out


def _scenario_claims(ctx: dict, news_src: str, gain: bool = False) -> list[dict]:
    """Чувствительность по формуле (SPR4-02) со ссылкой на расчет: рост ставки — риск (+X млн ₽ расходов),
    снижение — возможность (−X млн ₽ расходов). gain=False — утверждения для рисков, True — для возможностей."""
    out = []
    for sc in ctx.get("scenarios") or []:
        if sc["scenario"] != "key_rate" or not sc["effect_rub"] or (sc["effect_rub"] > 0) != gain:
            continue
        what = "процентных расходов в год" if not gain else "экономии на процентных расходах в год"
        out.append(_claim(f"Чувствительность к ставке: каждый {sc['shock']:+g} п.п. — это ≈ {scenario_mln(sc['effect_rub'])} "
                          f"{what} (оценка: {sc['formula']})", "client_data", [news_src, f"client:scenario:{sc['scenario']}"]))
    return out


def compose(ctx: dict) -> dict:
    """Разбор на правилах: эффект = чувствительность компании × направление события, с источником у каждого вывода."""
    news, cls, company = ctx["news"], ctx["news"]["classification"], ctx["company"]
    role, news_src = ctx["role"], f"news:{ctx['news']['news_id']}"
    topics = [t["topic"] for t in cls["topics"]] or ["default"]
    exposures, theses = ctx["exposures"], ctx["theses"]
    facts = [_claim(s, "fact", [news_src]) for s in (cls["key_sentences"] or [news["lead"]])[:4]]
    # Повод для выводов — сама новость: ее главное предложение открывает «почему важно» и риски.
    event = next((s for s in (cls["key_sentences"] or []) + [news["lead"], news["title"]] if 30 <= len(s) <= 220),
                 news["title"]).rstrip(".")

    # Риски и возможности: по каждой теме новости — один вывод, объединяющий признаки компании.
    risks, opps = [], []
    used_why: set[str] = set()
    by_topic: dict[str, list[dict]] = {}
    for e in exposures:
        by_topic.setdefault(e["topic"], []).append(e)
    topic_dirs = cls.get("topic_directions") or {}
    for t in topics[:4]:
        exps = sorted(by_topic.get(t, []), key=lambda x: x["weight"], reverse=True)
        if not exps or t not in TOPIC_EFFECT:
            continue
        neg_claims, pos_claims = _topic_claims(t, exps, topic_dirs.get(t, cls["direction"]), theses, news_src, used_why)
        risks += neg_claims
        opps += pos_claims

    sc_risks, sc_opps, sc_actions = _supply_chain(ctx, news_src)
    products = [{"product_id": p["id"], "title": p["title"], "text": p["text"],
                 "reason": f"Связано с темой «{TOPICS.get(p['topics'][0], {}).get('name', p['topics'][0])}»"}
                for p in ctx.get("products", [])]
    return {
        "title": news["title"],
        "headline": _headline(company, topics, by_topic, cls, theses),
        "what_happened": {"summary": news["lead"], "facts": facts, "actors": cls["actors"], "dates": cls["dates"],
                          "assumptions": _assumptions(ctx, cls, news_src)},
        "why_important": (_chain_claims(ctx, news_src) + _why_important(exposures, company, event, news_src))[:WHY_MAX],
        "risks": (_scenario_claims(ctx, news_src) + sc_risks + _dedupe(risks))[:4],
        "opportunities": (_scenario_claims(ctx, news_src, gain=True) + sc_opps + _dedupe(opps))[:4],
        "actions": _dedupe(sc_actions[:2] + _actions(topics, role, company, theses, news_src))[:4],
        "questions": [QUESTIONS[t] for t in topics if t in QUESTIONS][:3],
        "bank_view": _bank_view(ctx, theses),
        "products": products,
        "role_name": ROLES.get(role, ROLES["ceo"])["name"],
        "sector_name": SECTOR_NAMES.get(company["sector"], company["sector"]),
    }


def _why(e: dict) -> str:
    """Причина обычной фразой: «Отрасль «X»: …» -> «в отрасли «X» …», «Есть кредиты: …» -> «есть кредиты — …»."""
    why = e["why"]
    if e["origin"] == "sector_model" and why.startswith("Отрасль «") and "»: " in why:
        name, rest = why[len("Отрасль «"):].split("»: ", 1)
        return f"в отрасли «{name}» {_lower_first(rest)}"
    return _lower_first(why.replace(": ", " — ", 1))


def day(iso: str) -> str:
    """2026-10-23T… -> 23.10.2026."""
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if len(iso) >= 10 and iso[4] == "-" else iso


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if not text[:2].isupper() else text


def _first_sentence(text: str) -> str:
    end = text.find(". ")
    return text if end < 0 else text[:end + 1]


def _eligible(needs: str | None, company: dict) -> bool:
    if needs is None:
        return True
    if needs == "fts":
        return bool(company.get("fts_flag"))
    return bool(company["products"].get(needs))


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%".replace(".", ",")


def _dedupe(claims: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in claims:
        if c["text"] not in seen:
            seen.add(c["text"])
            out.append(c)
    return out
