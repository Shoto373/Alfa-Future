"""Смысловой слой: темы по смыслу, гибридный поиск и откат на словари без модели."""

from app import embeddings
from app.companies import names
from app.knowledge import kb
from app.news import classifier, semantic

# Новость без слов из словаря темы «Ключевая ставка».
PARAPHRASE = "Мегарегулятор оставил стоимость заимствований без изменений"
DIM = ["key_rate", "fx", "labor", "biz", "neg"]


def _vec(**w):
    v = [float(w.get(k, 0.0)) for k in DIM]
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


def _fake(texts):
    """Детерминированная «модель»: вектор по ключевым словам смысла."""
    out = []
    for t in texts:
        low = t.lower()
        if "заимствован" in low or "ключевой ставке" in low or "стоимость денег" in low:
            out.append(_vec(key_rate=1, biz=0.2))
        elif "спорт" in low or "футбол" in low or "матч" in low:
            out.append(_vec(neg=1))
        elif low.startswith(("политик", "военн", "культура", "криминал", "дипломат", "чиновник", "новости науки")):
            out.append(_vec(neg=1))
        else:
            out.append(_vec(biz=1))
    return out


def _enable(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "1")
    monkeypatch.setattr(embeddings, "_load", lambda: object())
    monkeypatch.setattr(embeddings, "embed", _fake)
    semantic._prototypes.cache_clear()


def test_without_model_classifier_uses_keywords_only():
    cls = classifier.classify(PARAPHRASE, "")
    assert "key_rate" not in cls.topic_keys()


def test_semantic_topic_found_without_keywords(monkeypatch):
    _enable(monkeypatch)
    cls = classifier.classify(PARAPHRASE, "")
    topic = next(t for t in cls.topics if t["topic"] == "key_rate")
    assert topic["matched"][0].startswith("по смыслу") and topic["score"] == classifier.SEMANTIC_TOPIC_SCORE


def test_non_business_news_gets_no_semantic_topics(monkeypatch):
    _enable(monkeypatch)
    cls = classifier.classify("Футбольный матч закончился вничью", "Спортивный матч прошел при полных трибунах.")
    assert cls.topics == []


def test_kb_search_finds_thesis_by_meaning(monkeypatch):
    target = next(t for t in kb._kb()["theses"] if "key_rate" in t["topics"] and not t["stale"])
    _enable(monkeypatch)
    monkeypatch.setattr(kb, "_dense", lambda q: {t["id"]: embeddings.cosine(
        _vec(key_rate=1) if t["id"] == target["id"] else _vec(fx=1), _vec(key_rate=1)) for t in kb._kb()["theses"]})
    found = kb.search(PARAPHRASE, ["key_rate"], [], limit=3)
    assert found and found[0]["id"] == target["id"] and found[0]["match"]["semantic"] > 0.9


def test_company_names_are_unique_and_stable():
    companies = [{"company_id": f"U_{i}", "sector": "fuel_trade"} for i in range(200)]
    names.assign(companies)
    first = [c["display_name"] for c in companies]
    assert len(set(first)) == 200 and all("Компания №" not in n for n in first)
    again = [{"company_id": f"U_{i}", "sector": "fuel_trade"} for i in range(200)]
    names.assign(again)
    assert [c["display_name"] for c in again] == first
