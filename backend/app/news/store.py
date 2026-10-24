"""Хранилище новостей: демо-лента, RSS и добавленные пользователем материалы.

Каждая новость классифицируется при добавлении. Дубликаты (почти одинаковый
текст из разных источников) объединяются: остается одна запись со списком
источников. Записи и изменения хранятся транзакционно в PostgreSQL.

Чтение идет из памяти процесса: при старте (warm) все записи загружаются один
раз, при смене словарей, правил или embedding-модели переклассифицируются там же,
а не в запросе пользователя. Каждое изменение увеличивает ревизию news_rev в
app_state; другие процессы сверяют ее не чаще раза в RECHECK_SECONDS и
перечитывают записи, только если ревизия изменилась. Записи в памяти общие —
их нельзя менять на месте.
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import func, select

from app import config, database, embeddings, vector_store, vectors
from app.models import News
from app.news import llm_classify, semantic
from app.news.classifier import classify, tokenize
from app.text import safe_text

logger = logging.getLogger("app.news.store")

SEED_FILE = Path(__file__).with_name("seed_news.json")
DUPLICATE_THRESHOLD = 0.55
RECHECK_SECONDS = 2.0
# Сюжет: одно событие из разных источников и его продолжения. Новость присоединяется к самой близкой
# по смыслу новости за последние STORY_WINDOW_DAYS дней, если сходство не ниже STORY_SIMILARITY
# (порог подобран на реальной ленте: «Brent выше $115» из Интерфакса, Коммерсанта и ТАСС — один сюжет).
STORY_SIMILARITY = 0.78
STORY_WINDOW_DAYS = 10
STORY_LABELS_KEY = "story_labels"
VERSION_KEY, REV_KEY = "news_seed", "news_rev"
NEWS_LOCK = 72810403

_lock = threading.RLock()


@dataclass
class _State:
    items: dict[str, dict]
    rev: int
    checked: float = field(default_factory=time.monotonic)
    ordered: list[dict] = field(default_factory=list)
    shingles: dict[str, set[str]] = field(default_factory=dict)
    stories: dict[str, str] = field(default_factory=dict)      # news_id -> story_id (id самой ранней новости)
    members: dict[str, list[str]] = field(default_factory=dict)  # story_id -> news_id от ранних к поздним

    def __post_init__(self):
        self.reindex()
        self.stories = _assign_stories(sorted(self.items.values(), key=lambda i: i["published_at"]))
        self.members = {}
        for news_id, story_id in sorted(self.stories.items(), key=lambda kv: self.items[kv[0]]["published_at"]):
            self.members.setdefault(story_id, []).append(news_id)

    def attach(self, item: dict) -> None:
        """Новая новость — в сюжет без пересчета остальных."""
        window = [self.items[i] for i in self.items if i != item["news_id"]]
        story_id = _nearest_story(item, window, self.stories)
        self.stories[item["news_id"]] = story_id
        self.members.setdefault(story_id, []).append(item["news_id"])
        self.members[story_id].sort(key=lambda i: self.items[i]["published_at"])

    def reindex(self) -> None:
        self.ordered = sorted(self.items.values(), key=lambda i: i["published_at"], reverse=True)
        known = self.shingles
        self.shingles = {k: known.get(k) or _shingles(_probe(v)) for k, v in self.items.items()}


_state: _State | None = None


def _shingles(text: str, n: int = 3) -> set[str]:
    words = tokenize(text)
    return {" ".join(words[i:i + n]) for i in range(max(len(words) - n + 1, 1))}


def _jaccard(sa: set[str], sb: set[str]) -> float:
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def similarity(a: str, b: str) -> float:
    return _jaccard(_shingles(a), _shingles(b))


def _probe(item: dict) -> str:
    return f"{item['title']} {item['text'][:600]}"


def clean(title: str, text: str) -> tuple[str, str]:
    return safe_text(title.strip()), safe_text(text.strip())


def _digest(title: str, text: str) -> str:
    return hashlib.sha1(f"{title}|{text[:400]}".encode()).hexdigest()[:12]


def make_item(title: str, text: str, source: str, url: str | None = None,
              published_at: str | None = None, kind: str = "external", news_id: str | None = None,
              llm: bool = False, hint: dict | None = None) -> dict:
    """llm=True — для неуверенной классификации спросить модель (новая новость); hint — уже полученный ответ."""
    original = (title.strip(), text.strip())
    title, text = clean(title, text)
    cls = classify(title, text, hint)
    if llm and hint is None and cls.uncertain and config.classify_llm_enabled():
        answer = llm_classify.hint(title, text)
        if answer:
            cls = classify(title, text, answer)
    return {
        "news_id": news_id or f"n-{_digest(title, text)}",
        "title": title,
        "text": text,
        "lead": (cls.key_sentences[0] if cls.key_sentences else text[:280]),
        "source": source,
        "url": url,
        "kind": kind,  # seed | rss | user | external
        "published_at": published_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "classification": cls.as_dict(),
        "duplicates": [],
        "content_filtered": original != (title, text),
    }


def _story_text(item: dict) -> str:
    return f"{item['title']}. {(item.get('lead') or '')[:200]}"


def _time(item: dict) -> float:
    try:
        dt = datetime.fromisoformat(item["published_at"])
    except (ValueError, KeyError):
        return 0.0
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _assign_stories(items_asc: list[dict]) -> dict[str, str]:
    """Сюжеты для всех новостей (по времени, скользящее окно). Без модели — каждая новость сама по себе."""
    vectors = embeddings.embed([_story_text(i) for i in items_asc]) if items_asc else None
    if vectors is None or len(items_asc) == 0:
        return {i["news_id"]: i["news_id"] for i in items_asc}
    matrix = embeddings.as_matrix(vectors)
    times = [_time(i) for i in items_asc]
    window = STORY_WINDOW_DAYS * 86400
    stories: dict[str, str] = {}
    start = 0
    for idx, item in enumerate(items_asc):
        while times[idx] - times[start] > window:
            start += 1
        story = item["news_id"]
        if start < idx:
            sims = matrix[start:idx] @ matrix[idx]
            best = int(np.argmax(sims))
            if sims[best] >= STORY_SIMILARITY:
                story = stories[items_asc[start + best]["news_id"]]
        stories[item["news_id"]] = story
    return stories


def _nearest_story(item: dict, others: list[dict], stories: dict[str, str]) -> str:
    t = _time(item)
    window = [o for o in others if abs(t - _time(o)) <= STORY_WINDOW_DAYS * 86400 and o["news_id"] in stories]
    if not window:
        return item["news_id"]
    vectors = embeddings.embed([_story_text(item)] + [_story_text(o) for o in window])
    if vectors is None:
        return item["news_id"]
    matrix = embeddings.as_matrix(vectors)
    sims = matrix[1:] @ matrix[0]
    best = int(np.argmax(sims))
    return stories[window[best]["news_id"]] if sims[best] >= STORY_SIMILARITY else item["news_id"]


def _version() -> str:
    """Подпись словарей, правил и модели: при ее смене все новости переклассифицируются."""
    here = Path(__file__).parent
    parts = [SEED_FILE.read_bytes()] + [(here / f).read_bytes() for f in
                                        ("classifier.py", "taxonomy.py", "semantic.py", "magnitude.py")]
    return hashlib.sha256(b"".join(parts) + embeddings.signature().encode()).hexdigest()


def _bump(db) -> int:
    rev = int(database.state(REV_KEY, db) or 0) + 1
    database.set_state(REV_KEY, rev, db)
    return rev


def _reclassify(db, version: str) -> None:
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))["items"]
    records = list(db.scalars(select(News)))
    # Векторы для смысловых тем считаются одной пачкой, а не по новости за раз.
    semantic.prime([clean(s["title"], s["text"]) for s in seed] + [(r.payload["title"], r.payload["text"]) for r in records])
    by_id = {r.news_id: r for r in records}
    for s in seed:
        it = make_item(s["title"], s["text"], s["source"], None, s["published_at"], "seed", s["news_id"])
        previous = by_id.get(it["news_id"])
        if previous:
            it["duplicates"] = previous.payload.get("duplicates") or []
            previous.payload = it
            previous.published_at = datetime.fromisoformat(it["published_at"])
        else:
            db.add(News(news_id=it["news_id"], published_at=datetime.fromisoformat(it["published_at"]),
                        kind=it["kind"], payload=it))
    seed_ids = {s["news_id"] for s in seed}
    for record in records:
        if record.news_id in seed_ids:
            continue
        previous = record.payload
        updated = make_item(previous["title"], previous["text"], previous["source"], previous.get("url"),
                            previous["published_at"], previous["kind"], previous["news_id"],
                            hint=(previous.get("classification") or {}).get("llm_hint"))
        updated.update(added_at=previous["added_at"], duplicates=previous.get("duplicates") or [],
                       content_filtered=previous.get("content_filtered", False) or updated["content_filtered"])
        record.payload = updated
    db.flush()
    database.set_state(VERSION_KEY, version, db)
    _bump(db)
    logger.info("news reclassified: seed=%d stored=%d", len(seed), len(records))


def _read_all(db) -> dict[str, dict]:
    return {p["news_id"]: p for p in db.scalars(select(News.payload))}


def _state_now(db=None, force: bool = False) -> _State:
    """Актуальная копия в памяти. Вызывается под _lock."""
    global _state
    if db is None:
        if _state is not None and not force and time.monotonic() - _state.checked < RECHECK_SECONDS:
            return _state
        with database.session() as db:
            return _state_now(db, force)
    if _state is None:
        # Первая загрузка процесса: проверка версии классификатора под блокировкой новостей.
        db.execute(select(func.pg_advisory_xact_lock(NEWS_LOCK)))
        version = _version()
        if database.state(VERSION_KEY, db) != version:
            _reclassify(db, version)
        _state = _State(_read_all(db), int(database.state(REV_KEY, db) or 0))
        return _state
    rev = int(database.state(REV_KEY, db) or 0)
    if rev != _state.rev:
        # Тексты записей не меняются (объединение дописывает только источники) — шинглы переиспользуются.
        _state = _State(_read_all(db), rev, shingles=_state.shingles)
    _state.checked = time.monotonic()
    return _state


def _news_vectors(items: list[dict]) -> None:
    """Заголовки в векторном хранилище: по ним агент ищет предыдущие события сюжета."""
    vectors.sync(vector_store.NEWS, [(i["news_id"], i["title"], {
        "published_at": i["published_at"], "topics": [t["topic"] for t in i["classification"]["topics"]]})
        for i in items])


def warm() -> int:
    """Старт сервиса: переклассификация при необходимости, загрузка в память и векторы заголовков."""
    with _lock:
        state = _state_now(force=True)
        items = list(state.ordered)
    _news_vectors(items)
    return len(items)


def reset_cache() -> None:
    """Забыть копию в памяти: следующее чтение загрузит записи из PostgreSQL."""
    global _state
    with _lock:
        _state = None


def revision() -> int:
    """Ревизия ленты: меняется при каждом добавлении или объединении новостей (ключ кэша ленты)."""
    with _lock:
        return _state_now().rev


def all_items() -> list[dict]:
    """Все новости от новых к старым (общие объекты — только для чтения)."""
    with _lock:
        return list(_state_now().ordered)


def get(news_id: str) -> dict | None:
    with _lock:
        return _state_now().items.get(news_id)


def story(news_id: str) -> dict | None:
    """Сюжет новости: id, название, все сообщения (от ранних к поздним) и источники."""
    with _lock:
        state = _state_now()
        story_id = state.stories.get(news_id)
        if story_id is None:
            return None
        items = [state.items[i] for i in state.members.get(story_id, [news_id]) if i in state.items]
    sources = sorted({i["source"] for i in items} | {d["source"] for i in items for d in i.get("duplicates", [])})
    return {"story_id": story_id, "label": story_label(story_id, items), "size": len(items),
            "sources": sources, "items": items}


def story_label(story_id: str, items: list[dict] | None = None) -> str:
    """Название сюжета: от модели (конвейер), иначе — заголовок первой новости."""
    labels = _labels()
    if story_id in labels:
        return labels[story_id]
    first = (items or [get(story_id)] or [None])[0]
    title = (first or {}).get("title", "")
    return title if len(title) <= 70 else title[:67].rsplit(" ", 1)[0] + "…"


_labels_memo: tuple[float, dict] = (0.0, {})


def _labels() -> dict[str, str]:
    global _labels_memo
    if time.monotonic() - _labels_memo[0] > 30:
        _labels_memo = (time.monotonic(), database.state(STORY_LABELS_KEY) or {})
    return _labels_memo[1]


def set_story_labels(labels: dict[str, str]) -> None:
    global _labels_memo
    with database.session() as db:
        merged = {**(database.state(STORY_LABELS_KEY, db) or {}), **labels}
        database.set_state(STORY_LABELS_KEY, merged, db)
    _labels_memo = (time.monotonic(), merged)


def stories(min_size: int = 2) -> list[dict]:
    """Сюжеты из нескольких сообщений — динамические темы ленты."""
    with _lock:
        state = _state_now()
        groups = [(sid, [state.items[i] for i in ids if i in state.items]) for sid, ids in state.members.items()
                  if len(ids) >= min_size]
    return [{"story_id": sid, "label": story_label(sid, items), "size": len(items),
             "news_ids": [i["news_id"] for i in items], "last": max(i["published_at"] for i in items)}
            for sid, items in groups]


def known(title: str, text: str) -> bool:
    """Новость уже есть (тот же id или почти тот же текст) — ее не нужно классифицировать заново."""
    title, text = clean(title, text)
    probe = _shingles(f"{title} {text[:600]}")
    with _lock:
        state = _state_now()
        return f"n-{_digest(title, text)}" in state.items or any(
            _jaccard(probe, s) >= DUPLICATE_THRESHOLD for s in state.shingles.values())


def add(item: dict) -> tuple[dict, bool]:
    """Добавляет новость. Возвращает (запись, создана_ли_новая). Дубликат приклеивается к оригиналу."""
    with _lock:
        with database.session() as db:
            db.execute(select(func.pg_advisory_xact_lock(NEWS_LOCK)))
            state = _state_now(db)
            if item["news_id"] in state.items:
                return state.items[item["news_id"]], False
            probe = _shingles(_probe(item))
            original = next((state.items[k] for k, s in state.shingles.items()
                             if _jaccard(probe, s) >= DUPLICATE_THRESHOLD), None)
            if original is not None:
                saved = {**original, "duplicates": original["duplicates"] + [
                    {"source": item["source"], "url": item["url"], "title": item["title"]}]}
                db.get(News, saved["news_id"]).payload = saved
                created = False
            else:
                db.add(News(news_id=item["news_id"], published_at=datetime.fromisoformat(item["published_at"]),
                            kind=item["kind"], payload=item))
                saved, created = item, True
            rev = _bump(db)
        # Транзакция зафиксирована: копия в памяти обновляется без перечитывания базы.
        state.items[saved["news_id"]] = saved
        if created:
            state.shingles[saved["news_id"]] = probe
        state.rev = rev
        state.reindex()
        if created:
            state.attach(saved)
    if created:
        _news_vectors([saved])
    return saved, created
