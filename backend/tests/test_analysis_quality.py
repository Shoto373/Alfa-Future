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
