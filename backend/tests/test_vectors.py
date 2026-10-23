"""Векторное хранилище (pgvector), кэш ленты, Redis и общая копия новостей в памяти."""

import os
import zlib

import numpy as np
import pytest
from sqlalchemy import select

from app import cache, database, embeddings, ranking, vectors
from app.agent import tools
from app.models import VECTOR_DIM, News, VectorItem
from app.news import semantic, store


class BagOfWords:
    """Детерминированная «модель»: слова хэшируются в измерения вектора."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts, batch_size=64):
        texts = list(texts)
        self.calls.append(texts)
        for t in texts:
            v = np.zeros(VECTOR_DIM, dtype=np.float32)
            for w in t.lower().replace(".", " ").split():
                v[zlib.crc32(w.encode()) % VECTOR_DIM] += 1.0
            yield v


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "1")
    monkeypatch.setenv("EMBEDDINGS_MODEL", "test/bag-of-words")
    embeddings.reset()
    semantic._prototypes.cache_clear()
    fake = BagOfWords()
    monkeypatch.setattr(embeddings, "_model", fake)
    monkeypatch.setattr(embeddings, "_model_key", embeddings._key())
    yield fake
    embeddings.reset()
    semantic._prototypes.cache_clear()


def _rows(collection: str) -> list[VectorItem]:
    with database.session() as db:
        return list(db.scalars(select(VectorItem).where(VectorItem.collection == collection)))


def test_vectors_survive_restart_without_recomputing(model):
    first = embeddings.embed(["ключевая ставка", "курс рубля"])
    assert first.shape == (2, VECTOR_DIM) and np.allclose(np.linalg.norm(first, axis=1), 1.0)
    assert model.calls == [["ключевая ставка", "курс рубля"]]
    assert {r.item_id for r in _rows(vectors.CACHE)} == {vectors.text_hash("ключевая ставка"), vectors.text_hash("курс рубля")}

    embeddings._cache.clear()  # как после рестарта процесса
    again = embeddings.embed(["курс рубля"])
    assert len(model.calls) == 1, "вектор должен прийти из pgvector, а не из модели"
    assert np.allclose(again[0], first[1], atol=1e-6)


def test_warm_preloads_stored_vectors(model):
    embeddings.embed(["инфляция", "экспорт"])
    embeddings._cache.clear()
    assert embeddings.warm()
    calls = len(model.calls)
    embeddings.embed(["инфляция", "экспорт"])
    assert len(model.calls) == calls


def test_news_titles_are_indexed_and_story_uses_vector_search(model, monkeypatch):
    store.warm()
    titles = {r.item_id for r in _rows(vectors.NEWS)}
    assert titles == {n["news_id"] for n in store.all_items()}

    earlier = store.make_item("ЦБ повысил ключевую ставку до 17%", "Банк России повысил ключевую ставку до 17% годовых.",
                              "Тест", published_at="2026-09-01T10:00:00+00:00")
    later = store.make_item("ЦБ повысил ключевую ставку до 18%",
                            "Совет директоров регулятора снова принял решение: ставка 18% годовых на фоне инфляции.",
                            "Тест", published_at="2026-10-01T10:00:00+00:00")
    assert store.add(earlier)[1] and store.add(later)[1]
    assert {earlier["news_id"], later["news_id"]} <= {r.item_id for r in _rows(vectors.NEWS)}

    found = vectors.nearest(vectors.NEWS, embeddings.embed([later["title"]])[0], k=5, exclude=[later["news_id"]],
                            published_before=later["published_at"], topics_any=["key_rate"])
    assert found and found[0][0] == earlier["news_id"] and found[0][1] > 0.8

    # История сюжета берется из векторного поиска, полный перебор ленты не нужен.
    monkeypatch.setattr(tools.store, "all_items", lambda: pytest.fail("fallback scan used"))
    story = tools._story(later["news_id"])
    assert earlier["news_id"] in [s["news_id"] for s in story]


def test_thesis_vectors_are_stored_and_pruned(model):
    from app.knowledge import kb
    kb._thesis_vectors.cache_clear()
    assert kb.warm() == len(_rows(vectors.THESIS))
    with database.session() as db:
        db.add(VectorItem(collection=vectors.THESIS, model="test/bag-of-words", item_id="gone", text_hash="x",
                          embedding=np.ones(VECTOR_DIM, dtype=np.float32), payload={}))
    kb._thesis_vectors.cache_clear()
    kb.warm()
    assert "gone" not in {r.item_id for r in _rows(vectors.THESIS)}
    sims = kb._dense("ключевая ставка Банка России")
    assert sims and set(sims) == {t["id"] for t in kb._kb()["theses"]}


def test_store_reads_from_memory_and_sees_other_process_writes(monkeypatch):
    store.warm()
    monkeypatch.setattr(store, "RECHECK_SECONDS", 3600.0)
    other = store.make_item("Минфин разместил ОФЗ на 40 млрд рублей", "Минфин разместил ОФЗ на 40 млрд рублей на аукционе.", "Другой процесс")
    with database.session() as db:  # запись «другого процесса» мимо store
        db.add(News(news_id=other["news_id"], published_at=other["published_at"], kind="rss", payload=other))
        database.set_state(store.REV_KEY, int(database.state(store.REV_KEY, db) or 0) + 1, db)
    assert store.get(other["news_id"]) is None, "внутри интервала проверки чтение идет из памяти"
    monkeypatch.setattr(store, "RECHECK_SECONDS", 0.0)
    assert store.get(other["news_id"])["title"] == other["title"]


def test_feed_is_cached_per_news_revision(company, monkeypatch):
    calls = []
    real = ranking.feed
    monkeypatch.setattr(ranking, "feed", lambda *a, **k: calls.append(1) or real(*a, **k))
    first = ranking.company_feed(company["company_id"], "cfo")
    second = ranking.company_feed(company["company_id"], "cfo")
    assert len(calls) == 1
    assert [r["news"]["news_id"] for r in first] == [r["news"]["news_id"] for r in second]
    store.add(store.make_item("ЦБ снизил ключевую ставку до 13%", "Банк России снизил ключевую ставку до 13% годовых.", "Тест"))
    ranking.company_feed(company["company_id"], "cfo")
    assert len(calls) == 2, "новая новость меняет ревизию и ключ кэша"


def test_cache_works_without_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # никто не слушает
    cache.clear()
    cache.set("k", {"a": 1}, 60)
    assert cache.get("k") == {"a": 1}
    assert cache.ping() is False
    monkeypatch.delenv("REDIS_URL")
    assert cache.ping() is None


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="TEST_REDIS_URL не задан")
def test_cache_roundtrip_through_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", os.environ["TEST_REDIS_URL"])
    cache.clear()
    assert cache.ping() is True
    cache.set("roundtrip", [1, "два"], 30)
    cache._local.clear()  # другой процесс видит значение через Redis
    assert cache.get("roundtrip") == [1, "два"]
