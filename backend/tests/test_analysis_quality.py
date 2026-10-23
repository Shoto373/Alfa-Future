"""Сила события, регион, склейка сюжетов и смысловая проверка выводов."""

import pytest

from app import embeddings, ranking
from app.agent import llm, review
from app.news import magnitude
from app.news.classifier import classify


@pytest.mark.parametrize("title,text,level", [
    ("ЦБ повысил ключевую ставку на 2 п.п.", "Банк России повысил ключевую ставку на 2 п.п.", "strong"),
    ("ЦБ снизил ставку на 25 б.п.", "Банк России снизил ключевую ставку на 25 б.п.", "moderate"),
    ("Банк России сохранил ключевую ставку", "Совет директоров сохранил ставку без изменений.", "weak"),
    ("Бензин подорожал за неделю", "Розничные цены на бензин выросли на 0,91% н/н.", "strong"),
    ("Импорт товаров вырос", "Стоимостной объем импорта вырос на 11% год к году.", "strong"),
])
def test_event_strength_from_numbers(title, text, level):
    strength = classify(title, text).magnitude
    assert strength and strength["level"] == level and strength["evidence"] in f"{title} {text}"


def test_strength_unknown_without_numbers():
    assert classify("Зарплаты на рынке труда растут", "Работодатели повышают зарплаты.").magnitude is None


@pytest.mark.parametrize("region,stem", [("Иркутская область", "иркутск"), ("Москва", "москв"),
                                         ("Санкт-Петербург", "санкт-петербург"), (None, None)])
def test_region_stem(region, stem):
    assert ranking._region_stem(region) == stem


def test_moscow_is_not_a_region_signal():
    assert {"москв", "московск"} <= ranking.REGION_SKIP


def test_similar_stories_are_collapsed(monkeypatch):
    items = [{"news": {"title": t}, "relevance": {"score": s}} for t, s in
             (("ЦБ сохранил ставку 14%", 90), ("Банк России оставил ставку на уровне 14%", 80), ("Бензин подорожал", 70))]
    vectors = {"ЦБ сохранил ставку 14%": [1.0, 0.0], "Банк России оставил ставку на уровне 14%": [0.99, 0.141],
               "Бензин подорожал": [0.0, 1.0]}
    monkeypatch.setattr(embeddings, "embed", lambda texts: [vectors[t] for t in texts])
    out = ranking._collapse_stories(items)
    assert [i["news"]["title"] for i in out] == ["ЦБ сохранил ставку 14%", "Бензин подорожал"]
    assert out[0]["story_size"] == 1


def _ctx():
    return {"news": {"news_id": "n1", "title": "ЦБ повысил ставку", "text": "Банк России повысил ключевую ставку."},
            "theses": [], "company": {"display_name": "ООО «Тест»", "sector_name": "Услуги"}}


def _draft():
    claim = lambda text: {"text": text, "origin": "ai", "source_ids": ["news:n1"], "features": ["products.loans"]}
    return {"why_important": [], "opportunities": [], "actions": [],
            "risks": [claim("Кредиты станут дороже"), claim("Депозиты станут невыгодны")]}


def test_critic_removes_unsupported_claim(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"verdicts": [
        {"i": 0, "verdict": "supported"}, {"i": 1, "verdict": "unsupported", "reason": "рост ставки повышает доходность депозитов"}]},
        {"model": "deepseek/deepseek-v4.1-flash"}))
    draft = _draft()
    outcome = review.review(draft, _ctx(), [])
    assert [c["text"] for c in draft["risks"]] == ["Кредиты станут дороже"]
    assert outcome["supported"] == 1 and len(outcome["removed"]) == 1


def test_critic_never_empties_a_section(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"verdicts": [
        {"i": 0, "verdict": "unsupported"}, {"i": 1, "verdict": "unsupported"}]}, {"model": "m"}))
    draft = _draft()
    outcome = review.review(draft, _ctx(), [])
    assert len(draft["risks"]) == 2 and outcome["removed"] == []


def test_critic_bad_answer_raises(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"risks": []}, {"model": "m"}))
    with pytest.raises(llm.LLMError):
        review.review(_draft(), _ctx(), [])


def test_repair_relabels_bank_paraphrase_and_keeps_source_boundary(company):
    from app.agent import validators
    from app.knowledge import kb
    thesis = next(t for t in kb._kb()["theses"] if not t["stale"])
    news = {"news_id": "n1", "title": "Событие", "text": "Банк России сохранил ставку.", "lead": "", "classification": {}}
    ctx = {"news": news, "company": company, "theses": [thesis], "products": [], "story": [], "exposures": []}
    paraphrase = {"text": "Банк: " + thesis["text"].split(";")[0][:60].lower() + " — это важно", "origin": "bank",
                  "source_ids": [f"bank:{thesis['id']}"], "features": []}
    forged = {"text": "Банк гарантирует доходность", "origin": "bank", "source_ids": ["client:profile"], "features": []}
    draft = {"why_important": [paraphrase, forged], "risks": [], "opportunities": [], "actions": [],
             "what_happened": {"facts": [], "assumptions": []}}
    ids = {f"bank:{thesis['id']}", "client:profile", "news:n1"}
    validators._repair(draft, ctx, ids)
    assert paraphrase["origin"] == "ai" and not paraphrase["text"].startswith("Банк:")
    assert forged["origin"] == "bank"  # подмена источника не переклассифицируется и будет удалена проверкой


# SPR2-04: причины неверного знака эффекта на golden set (tests/golden) — каждое исправление закреплено тестом.

@pytest.mark.parametrize("title,text,expected", [
    ("Рубль ослаб до 100 за доллар", "Курс рубля ослаб: доллар превысил 100 рублей.", "up"),
    ("Рубль подешевел к юаню", "Рубль ослаб к основным валютам: курс юаня вырос до 14 рублей.", "up"),
    ("Рубль укрепился до максимума", "Рубль укрепился: курс доллара опустился до 78 рублей.", "down"),
    ("Курс рубля укрепился к евро", "Рубль укрепился к евро: официальный курс снизился до 86 рублей.", "down"),
])
def test_fx_direction_is_read_relative_to_ruble(title, text, expected):
    # up для курса — ослабление рубля: «рубль ослаб» и «доллар вырос» — одно событие.
    assert classify(title, text).topic_directions["fx"] == expected


@pytest.mark.parametrize("title,text,topic,expected", [
    ("Инфляция ускорилась до 9%", "Годовая инфляция ускорилась до 9% по итогам сентября.", "inflation", "up"),
    ("Правительство повысит НДПИ", "Минфин предложил повысить налог на добычу полезных ископаемых.", "taxes_regulation", "up"),
    ("РЖД проиндексирует тарифы", "Тарифы на грузовые железнодорожные перевозки вырастут на 10% с января.", "logistics", "up"),
])
def test_direction_from_verb_forms(title, text, topic, expected):
    assert classify(title, text).topic_directions[topic] == expected


@pytest.mark.parametrize("title,text,expected", [
    ("ЕС ввел новый пакет санкций", "Евросоюз утвердил новый пакет санкций против России.", "up"),
    ("Часть санкций отменена", "Власти отменили часть санкций против российских компаний.", "down"),
])
def test_sanctions_direction(title, text, expected):
    assert classify(title, text).topic_directions["sanctions_geopolitics"] == expected


def test_border_delays_are_logistics():
    cls = classify("Очереди грузовиков на границе выросли",
                   "Очереди на погранпереходах с Китаем выросли до недели, сроки доставки грузов увеличились.")
    assert "logistics" in [t["topic"] for t in cls.topics]


def test_topic_found_without_own_sentences_does_not_inherit_direction():
    # «Ставка повышена» не значит «экономика растет»: тема, добавленная не по словарю (по смыслу или
    # подсказкой модели), без своих предложений направления другой темы не получает.
    cls = classify("Ключевая ставка повышена до 17%", "Банк России повысил ключевую ставку до 17% годовых.",
                   hint={"business": True, "topics": ["gdp_industry"], "model": "test"})
    assert cls.topic_directions["key_rate"] == "up"
    assert cls.topic_directions["gdp_industry"] is None


def test_sanctions_tightening_is_a_risk_for_exposed_sector():
    from app.agent import composer

    assert composer._effect("sanctions_geopolitics", "up", -1) < 0
    assert composer._effect("sanctions_geopolitics", "down", -1) > 0


@pytest.mark.parametrize("risks,opps,expected", [
    ([], [], "none"),
    (["Стоимость заимствований может вырасти"], [], "neg"),
    ([], ["Валютная выручка дает больше рублей"], "pos"),
    (["Издержки растут"], ["Спрос растет"], "mixed"),
    (["Возможный риск — издержки растут."], ["Возможность — спрос растет."], "unclear"),
    (["Возможный риск — издержки растут."], ["Спрос растет"], "pos"),
])
def test_overall_effect_label(risks, opps, expected):
    from app.agent import composer

    claim = lambda text: {"text": text, "origin": "ai", "source_ids": [], "features": []}
    card = {"risks": [claim(t) for t in risks], "opportunities": [claim(t) for t in opps]}
    assert composer.overall_effect(card) == expected


def test_insight_and_feed_carry_effect(client, company):
    import asyncio

    from app import storage
    from app.agent import composer, orchestrator
    from app.news import store

    news = store.make_item("Банк России повысил ключевую ставку до 16%",
                           "Совет директоров Банка России повысил ключевую ставку до 16% годовых.", "Проверка")
    ins = asyncio.run(orchestrator.run(company, "cfo", news, "req_effect", use_llm=False))
    assert ins["effect"] == composer.overall_effect(ins) and ins["effect"] != "none"

    store.add(news)
    storage.save_insight(ins)
    refs = storage.cached_insight_refs(company["company_id"], "cfo", [news["news_id"]])
    assert refs[news["news_id"]] == (ins["insight_id"], ins["effect"])
