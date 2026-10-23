"""Составление интерпретации без LLM (режим правил) из собранного агентом контекста.

Логика: эффект = знак чувствительности компании × направление события.
Отрицательный эффект — риск, положительный — возможность, неоднозначный —
и то и другое с условием. Каждое утверждение несет origin и source_ids;
цифры берутся только из новости, тезисов банка и данных компании.
"""

from app.companies.sectors import SECTOR_NAMES
from app.news.taxonomy import TOPICS
from app.ranking import ROLES

# Как направление события влияет на «положительную» сторону темы.
# hold по ставке = деньги остаются дорогими (как в примере кейса).
DIRECTION_VALUE = {
    "key_rate": {"up": 1, "hold": 0.6, "down": -1},
    "inflation": {"up": 1, "hold": 0.3, "down": -1},
    "fx": {"up": 1, "hold": 0, "down": -1},          # up = ослабление рубля
    "fuel_oil": {"up": 1, "hold": 0, "down": -1},
    "gold": {"up": 1, "hold": 0, "down": -1},
    "metals_steel": {"up": 1, "hold": 0, "down": -1},
    "credit_market": {"up": 1, "hold": 0, "down": -1},   # up = кредит доступнее, down = ужесточение
    "consumer_demand": {"up": 1, "hold": 0, "down": -1},
    "gdp_industry": {"up": 1, "hold": 0, "down": -1},
    "labor": {"up": 1, "hold": 0.3, "down": -1},       # up = рост зарплат/дефицит
    "budget": {"up": 1, "hold": 0, "down": -1},
    "construction_realestate": {"up": 1, "hold": 0, "down": -1},
    "bonds": {"up": 1, "hold": 0.3, "down": -1},       # up = рост доходностей
    "deposits": {"up": 1, "hold": 0.5, "down": -1},
    "taxes_regulation": {"up": 1, "hold": 0, "down": -1},   # up = нагрузка и требования растут
    "logistics": {"up": 1, "hold": 0, "down": -1},          # up = перевозки дорожают или усложняются
    "sanctions_geopolitics": {"up": 1, "hold": 0, "down": -1},  # up = ограничения вводятся или расширяются
}

TOPIC_EFFECT = {
    "key_rate": ("обслуживание долга и новые заимствования остаются дорогими", "доходность размещения свободной ликвидности остается высокой"),
    "inflation": ("издержки растут быстрее, чем их удается переложить в цены", "номинальная выручка растет вместе с ценами"),
    "fx": ("расчеты и закупки в валюте дорожают в рублях", "валютная выручка дает больше рублей"),
    "fuel_oil": ("растут транспортные и производственные издержки", "растет выручка от реализации нефти и топлива"),
    "gold": ("снижается выручка от драгметаллов", "растет выручка и стоимость запасов драгметаллов"),
    "metals_steel": ("дорожает металл в себестоимости", "растут цены реализации металлопродукции"),
    "credit_market": ("доступ к кредиту и рефинансирование усложняются", "кредит становится доступнее"),
    "consumer_demand": ("спрос клиентов замедляется", "спрос клиентов поддерживает выручку"),
    "gdp_industry": ("замедление экономики снижает объемы заказов", "оживление экономики поддерживает объемы"),
    "labor": ("фонд оплаты труда растет, кадров не хватает", "рынок труда стабилен"),
    "budget": ("сокращение госрасходов уменьшает число контрактов", "госрасходы поддерживают заказы"),
    "construction_realestate": ("рынок строительства и недвижимости охлаждается", "рынок строительства и недвижимости растет"),
    "bonds": ("рыночная стоимость заимствований растет", "доходности долговых инструментов высоки для размещения"),
    "deposits": ("доходность размещения снижается", "доходность размещения высокая"),
    "imports_exports": ("меняются условия поставок и расчетов с иностранными партнерами", "открываются новые каналы поставок"),
    "sanctions_geopolitics": ("ограничения затрудняют платежи и логистику", "появляются ниши после ухода конкурентов"),
    "energy": ("растут расходы на энергию", "растут тарифы и выручка"),
    "corporate_finance": ("ухудшаются финансовые показатели контрагентов", "финансы отрасли улучшаются"),
    "taxes_regulation": ("налоговая и регуляторная нагрузка растет", "нагрузка снижается или появляются льготы"),
    "logistics": ("перевозки дорожают или задерживаются", "растут тарифы и спрос на перевозки"),
}

ACTIONS = {
    "key_rate": {
        "cfo": [("Пересчитать график обслуживания долга при текущих условиях финансирования и проверить запас по ковенантам", "loans"),
                ("Сравнить плавающую и фиксированную ставку для новых траншей; оценить хеджирование части долга", "loans"),
                ("Пересчитать стоимость лизинговых платежей и сравнить с покупкой оборудования за собственные средства", "leasing"),
                ("Сравнить варианты размещения свободной ликвидности с учетом текущих ставок и сроков", "deposits"),
                ("Оценить, выгодно ли сейчас привлекать заемное финансирование или отложить проекты до снижения ставки", None)],
        "treasurer": [("Разместить временно свободную ликвидность на срок до конца года, пока ставки высоки", None),
                      ("Проверить лимиты и стоимость кредитных линий на ближайший период", "loans")],
        "ceo": [("Пересмотреть сроки инвестпроектов, финансируемых заемными средствами", "loans"),
                ("Сопоставить план инвестиций со сценариями изменения стоимости финансирования", None)],
        "owner": [("Оценить долговую нагрузку при текущих условиях финансирования", "loans"),
                  ("Решить, направлять ли свободный денежный поток на депозиты или в развитие", None)],
        "default": [("Оценить чувствительность денежного потока к сохранению ставки на текущем уровне", None)],
    },
    "inflation": {
        "cfo": ["Обновить бюджет с учетом прогноза инфляции банка и проверить индексацию в договорах"],
        "ceo": ["Пересмотреть ценовую политику и условия индексации с ключевыми покупателями"],
        "accountant": ["Проверить условия индексации цен и авансов в договорах с поставщиками"],
        "default": ["Оценить, какую часть роста издержек можно переложить в цены"],
    },
    "fx": {
        "treasurer": ["Сопоставить валютную позицию с прогнозом курса банка и решить, какую часть закупок захеджировать"],
        "cfo": ["Оценить влияние курса на маржу по импортным закупкам и валютной выручке"],
        "accountant": ["Проверить валюту и сроки расчетов по внешнеторговым контрактам"],
        "default": ["Оценить валютные риски по контрактам с иностранными контрагентами"],
    },
    "fuel_oil": {"default": ["Пересчитать логистические издержки и проверить условия топливных надбавок в договорах перевозки"]},
    "credit_market": {"cfo": ["Заранее согласовать лимиты финансирования на следующий бюджетный период"],
                      "default": ["Проверить зависимость продаж от кредитования клиентов"]},
    "consumer_demand": {"ceo": ["Скорректировать план продаж и запасы на ближайший квартал с учетом динамики спроса"],
                        "default": ["Пересмотреть план продаж и уровень запасов"]},
    "imports_exports": {"ceo": ["Проверить устойчивость цепочки поставок и альтернативных маршрутов"],
                        "accountant": ["Сверить документы ВЭД и валютный контроль по текущим контрактам"],
                        "default": ["Оценить, как событие влияет на поставки и расчеты с иностранными партнерами"]},
    "sanctions_geopolitics": {"default": ["Проверить контрагентов и платежные маршруты на подверженность ограничениям"]},
    "labor": {"ceo": ["Пересмотреть бюджет ФОТ и программу удержания ключевых сотрудников"],
              "default": ["Оценить рост фонда оплаты труда на следующий год"]},
    "budget": {"default": ["Отслеживать параметры нового бюджета: они повлияют на госзаказ и ставку"]},
    "bonds": {"cfo": ["Если планируется выпуск облигаций — сравнить флоатер (КС + спред) и фиксированный купон"],
              "default": ["Учесть рост доходностей ОФЗ при планировании заимствований"]},
    "construction_realestate": {"default": ["Оценить спрос на объекты и условия проектного финансирования"]},
    "gold": {"default": ["Оценить, как цена золота влияет на выручку и стоимость запасов"]},
    "taxes_regulation": {"accountant": ["Оценить изменение налоговой нагрузки и сроки вступления изменений; обновить налоговый календарь"],
                         "cfo": ["Пересчитать бюджет и денежный поток с учетом новых налоговых и регуляторных требований"],
                         "owner": ["Оценить влияние изменений на дивидендную политику и стоимость бизнеса"],
                         "default": ["Проверить, какие требования затрагивают компанию и с какой даты они действуют"]},
    "logistics": {"ceo": ["Проверить альтернативные маршруты и сроки поставок; заложить запас по критичным позициям"],
                  "cfo": ["Пересчитать логистическую составляющую себестоимости и условия поставки в договорах"],
                  "default": ["Оценить, как изменение тарифов и сроков перевозки влияет на поставки"]},
    "default": {"default": ["Обсудить влияние события с менеджером банка и определить, нужна ли корректировка планов"]},
}

QUESTIONS = {
    "key_rate": "Какая доля долга компании привязана к плавающей ставке и когда ближайшие погашения?",
    "fx": "Какая доля закупок и выручки номинирована в валюте и в какой именно?",
    "inflation": "Есть ли в договорах механизмы индексации цен?",
    "fuel_oil": "Какую долю себестоимости составляют топливо и логистика?",
    "consumer_demand": "Как менялись продажи компании в последние месяцы по сравнению с рынком?",
    "imports_exports": "Есть ли альтернативные поставщики и маршруты при сбоях?",
    "labor": "Какой рост ФОТ заложен в бюджет на следующий год?",
    "credit_market": "Какие лимиты финансирования согласованы на ближайшие 6 месяцев?",
    "taxes_regulation": "Какие налоги и требования составляют наибольшую часть нагрузки компании?",
    "logistics": "Какая доля поставок идет железной дорогой, через порты или транзитом?",
}

ORIGIN_SOURCE = {"client_data": "client:profile", "payments": "client:payments", "sector_model": "client:profile"}

# Оговорки, когда знак влияния зависит от операций компании: такие выводы не задают общий знак события.
HEDGED_RISK, HEDGED_OPP = "Возможный риск —", "Возможность —"


def overall_effect(card: dict) -> str:
    """Общий знак события для компании по итоговым разделам разбора (метка в ленте и шапке разбора).

    neg — скорее риск, pos — скорее возможность, mixed — и то и другое, unclear — зависит от операций
    компании (только оговорки), none — влияния на бизнес не найдено.
    """
    if not card["risks"] and not card["opportunities"]:
        return "none"
    risk = any(not c["text"].startswith(HEDGED_RISK) for c in card["risks"])
    opp = any(not c["text"].startswith(HEDGED_OPP) for c in card["opportunities"])
    return "mixed" if risk and opp else "neg" if risk else "pos" if opp else "unclear"


def _claim(text: str, origin: str, sources: list[str], features: list[str] | None = None) -> dict:
    return {"text": text, "origin": origin, "source_ids": sources, "features": features or []}


def _effect(topic: str, direction: str | None, sign: int) -> float:
    if sign == 0 or direction is None:
        return 0.0
    return sign * DIRECTION_VALUE.get(topic, {}).get(direction, 0)


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
        return (f"сохранение ставки само по себе не снижает стоимость {funding}",
                "условия доходности нового размещения ликвидности сохраняют поддержку текущей ставки")
    if direction == "down":
        return {
            "key_rate": ("доходность нового размещения ликвидности может снизиться", "стоимость новых заимствований может снизиться; эффект для действующего долга зависит от договоров"),
            "inflation": ("темп роста цен реализации замедляется", "давление роста издержек может ослабнуть"),
            "fx": ("валютная выручка дает меньше рублей при укреплении рубля", "валютные закупки могут стать дешевле в рублях"),
            "fuel_oil": ("снижаются цены реализации нефти и топлива", "могут снизиться топливные и транспортные издержки"),
            "gold": ("снижаются выручка и стоимость запасов драгметаллов", "снижаются затраты на закупку драгметаллов"),
            "metals_steel": ("снижаются цены реализации металлопродукции", "металл в себестоимости может стать дешевле"),
            "credit_market": TOPIC_EFFECT["credit_market"],
            "consumer_demand": TOPIC_EFFECT["consumer_demand"],
            "gdp_industry": TOPIC_EFFECT["gdp_industry"],
            "labor": ("ослабление рынка труда может сигнализировать о снижении спроса", "может ослабнуть давление на фонд оплаты труда"),
            "budget": TOPIC_EFFECT["budget"],
            "bonds": ("снижается доходность новых размещений ликвидности", "стоимость новых рыночных заимствований может снизиться"),
            "deposits": TOPIC_EFFECT["deposits"],
            "construction_realestate": TOPIC_EFFECT["construction_realestate"],
            "sanctions_geopolitics": ("с ослаблением ограничений на рынок могут вернуться конкуренты",
                                      "ослабление ограничений упрощает платежи и логистику"),
        }.get(topic, TOPIC_EFFECT[topic])
    return TOPIC_EFFECT[topic]


def compose(ctx: dict) -> dict:
    news, cls, company = ctx["news"], ctx["news"]["classification"], ctx["company"]
    role, news_src = ctx["role"], f"news:{ctx['news']['news_id']}"
    topics = [t["topic"] for t in cls["topics"]] or ["default"]
    direction = cls["direction"]
    exposures = ctx["exposures"]
    theses = ctx["theses"]

    facts = [_claim(s, "fact", [news_src]) for s in (cls["key_sentences"] or [news["lead"]])[:4]]
    assumptions = []
    if direction is None:
        assumptions.append(_claim("Направление события из текста однозначно не определяется — оценка влияния дана в виде сценариев.", "ai", [news_src]))
    # История сюжета: тренд или разовое событие — по последним предыдущим новостям того же сюжета.
    story = ctx.get("story") or []
    if story:
        latest = story[0]
        tail = ", до этого были и другие события по теме" if len(story) > 1 else ""  # без цифр: число не из источника
        assumptions.append(_claim(f"Событие продолжает сюжет: {latest['published_at']} — «{latest['title']}»{tail}.", "ai",
                                  [f"news:{n['news_id']}" for n in story[:3]]))
    strength = cls.get("magnitude")
    if strength and strength.get("evidence"):
        # Сила события: цитата из новости, поэтому числа в утверждении подтверждаются ее текстом.
        assumptions.append(_claim(f"Масштаб изменения — {strength['label']}: в новости «{strength['evidence']}».", "ai", [news_src]))

    # Почему важно: самые весомые экспозиции по темам новости, по одному признаку на тему.
    why, used_features, seen = [], [], set()
    for e in sorted(exposures, key=lambda x: x["weight"], reverse=True):
        key = (e["topic"], e["feature"])
        if key in seen or len(why) >= 5:
            continue
        seen.add(key)
        why.append(_claim(e["why"], "ai" if e["origin"] == "sector_model" else "client_data",
                          [ORIGIN_SOURCE.get(e["origin"], "client:profile")], [e["feature"]]))
        used_features.append(e["feature"])
    if exposures and company["market"].get("okved_rank") and company["market"].get("okved_peers"):
        m = company["market"]
        why.append(_claim(
            f"Компания — №{m['okved_rank']} из {m['okved_peers']} по выручке среди компаний с ОКВЭД {company['okved_code']} в выборке "
            f"(доля {pct(m['okved_share'])}). Это положение внутри выборки, а не доля всего рынка.",
            "client_data", ["client:profile"], ["market"]))
    if not why:
        why.append(_claim(f"Прямых признаков чувствительности компании к теме не найдено. По доступным данным отрасли «{company['sector_name']}» нельзя уверенно оценить влияние.",
                          "ai", ["client:profile"], ["sector"]))

    # Риски и возможности: по каждой теме новости — один вывод, объединяющий признаки компании.
    risks, opps = [], []
    by_topic: dict[str, list[dict]] = {}
    for e in exposures:
        by_topic.setdefault(e["topic"], []).append(e)
    topic_dirs = cls.get("topic_directions") or {}
    for t in topics[:4]:
        exps = sorted(by_topic.get(t, []), key=lambda x: x["weight"], reverse=True)
        if not exps or t not in TOPIC_EFFECT:
            continue
        d = topic_dirs.get(t, direction)
        neg, pos = effect_terms(t, d, {e["feature"] for e in exps})
        groups = {"neg": [], "pos": [], "amb": []}
        for e in exps:
            eff = _effect(t, d, e["sign"])
            groups["neg" if eff < 0 else "pos" if eff > 0 else "amb"].append(e)
        forecast = next((th for th in sorted(theses, key=lambda x: x["doc_date"], reverse=True)
                         if t in th["topics"] and th.get("stance") == "forecast" and not th.get("stale")), None)
        horizon = f" Горизонт по прогнозу банка: {_first_sentence(forecast['text'])}" if forecast else ""
        extra = [f"bank:{forecast['id']}"] if forecast else []

        def basis(items):
            srcs = [news_src] + sorted({ORIGIN_SOURCE.get(e["origin"], "client:profile") for e in items}) + extra
            return srcs, [e["feature"] for e in items[:3]]

        def because(items):
            return "; ".join(_lower_first(e["why"].replace(": ", " — ", 1)) for e in items[:3])

        if groups["neg"]:
            srcs, feats = basis(groups["neg"])
            risks.append(_claim(f"{_cap(neg)}. Почему это касается компании: {because(groups['neg'])}.{horizon}", "ai", srcs, feats))
        if groups["pos"]:
            srcs, feats = basis(groups["pos"])
            opps.append(_claim(f"{_cap(pos)}. Почему это касается компании: {because(groups['pos'])}.{horizon}", "ai", srcs, feats))
        if groups["amb"]:
            srcs, feats = basis(groups["amb"])
            if not groups["neg"]:
                risks.append(_claim(f"{HEDGED_RISK} {neg}. Знак влияния зависит от развития ситуации и структуры операций компании: "
                                    f"{because(groups['amb'])}.", "ai", srcs, feats))
            if not groups["pos"]:
                opps.append(_claim(f"{HEDGED_OPP} {pos}, если ситуация развернется в пользу компании: "
                                   f"{because(groups['amb'])}.", "ai", srcs, feats))
    risks = _dedupe(risks)[:4]
    opps = _dedupe(opps)[:4]

    # Позиция банка.
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

    # Сводная мысль: событие -> главный плюс и минус для компании -> позиция банка.
    who = f"компании {company['display_name'].replace('Компания ', '')} ({company['sector_name'].lower()})"
    main = next((t for t in topics if t in TOPIC_EFFECT and by_topic.get(t)), None)
    if main:
        neg, pos = effect_terms(main, topic_dirs.get(main, direction), {e["feature"] for e in by_topic[main]})
        effs = [_effect(main, topic_dirs.get(main, direction), e["sign"]) for e in by_topic[main]]
        if any(x < 0 for x in effs) and any(x > 0 for x in effs):
            headline = f"Для {who} событие разнонаправленное: {neg}, но {pos}."
        elif any(x < 0 for x in effs):
            headline = f"Для {who}: {neg}."
        elif any(x > 0 for x in effs):
            headline = f"Для {who}: {pos}."
        else:
            headline = f"Для {who}: {neg} или {pos} — зависит от структуры операций."
    else:
        headline = f"Для {who} не найдена подтвержденная связь с событием; нужны дополнительные данные."
    if theses and not theses[0].get("stale"):
        headline += " Банк учитывает это в своих прогнозах — см. раздел «Как оценивает банк»."

    # Действия по роли.
    actions = []
    for t in topics[:3]:
        lib = ACTIONS.get(t, {})
        options = [a if isinstance(a, tuple) else (a, None) for a in (lib.get(role) or lib.get("default") or [])]
        for text, needs in [o for o in options if _eligible(o[1], company)][:2]:
            actions.append(_claim(text, "ai", [news_src, "client:profile"] + ([f"bank:{theses[0]['id']}"] if theses else [])))
    if not actions:
        actions = [_claim(ACTIONS["default"]["default"][0], "ai", [news_src])]
    actions = _dedupe(actions)[:4]
    questions = [QUESTIONS[t] for t in topics if t in QUESTIONS][:3]

    products = [{"product_id": p["id"], "title": p["title"], "text": p["text"],
                 "reason": f"Связано с темой «{TOPICS.get(p['topics'][0], {}).get('name', p['topics'][0])}»"}
                for p in ctx.get("products", [])]

    return {
        "title": news["title"],
        "headline": headline,
        "what_happened": {"summary": news["lead"], "facts": facts, "actors": cls["actors"], "dates": cls["dates"],
                          "assumptions": assumptions},
        "why_important": why,
        "risks": risks,
        "opportunities": opps,
        "actions": actions,
        "questions": questions,
        "bank_view": {"available": bool(theses), "summary": bank_summary, "theses": bank_claims, "conflicts": conflicts},
        "products": products,
        "role_name": ROLES.get(role, ROLES["ceo"])["name"],
        "sector_name": SECTOR_NAMES.get(company["sector"], company["sector"]),
    }


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
