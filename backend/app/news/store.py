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
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import func, select

from app import config, database, embeddings, vector_store, vectors
from app.domain_config import runtime
from app.models import News
from app.news import llm_classify, materiality, semantic
from app.news.classifier import classify, tokenize
from app.text import safe_text

logger = logging.getLogger("app.news.store")

SEED_FILE = Path(__file__).with_name("seed_news.json")
DUPLICATE_THRESHOLD = 0.55
RECHECK_SECONDS = 2.0
# Сюжет: одно событие из разных источников и его продолжения. Новость присоединяется к самой близкой
# по смыслу новости за последние STORY_WINDOW_DAYS дней, если сходство не ниже порога config.story_similarity()
# (0,78 подобран на реальной ленте: «Brent выше $115» из Интерфакса, Коммерсанта и ТАСС — один сюжет).
# Сюжет новости хранится в базе (news.story_id): перезапуск и повторный сбор не пересчитывают его.
STORY_WINDOW_DAYS = 10
# Одна и та же компания в заголовках за пару дней — один сюжет и при меньшей близости: «Выручка ФосАгро
# в III квартале…» (Интерфакс) и «Чистая прибыль «Фосагро» за девять месяцев…» (Коммерсантъ) — 0,70.
ENTITY_STORY_SIMILARITY = 0.65
ENTITY_STORY_DAYS = 3
_QUOTED = re.compile(r"«([^»]{2,40})»")
_WORD = re.compile(r"[A-Za-zА-ЯЁа-яё][\w-]*")
_ROMAN = re.compile(r"[IVXLC]+")  # «III квартал» — не компания
STORY_LABELS_KEY = "story_labels"
VERSION_KEY, REV_KEY = "news_seed", "news_rev"
# Дельта кэша: записи, измененные после прошлой проверки, с запасом на транзакции, завершившиеся не по порядку.
DELTA_OVERLAP = timedelta(seconds=30)
NEWS_LOCK = 72810403

_lock = threading.RLock()


@dataclass
class _State:
    items: dict[str, dict]
    rev: int
    seen: datetime | None = None  # самое позднее updated_at среди загруженных записей
    checked: float = field(default_factory=time.monotonic)
    ordered: list[dict] = field(default_factory=list)
    shingles: dict[str, set[str]] = field(default_factory=dict)
    stories: dict[str, str] = field(default_factory=dict)      # news_id -> story_id (id самой ранней новости)
    members: dict[str, list[str]] = field(default_factory=dict)  # story_id -> news_id от ранних к поздним

    def __post_init__(self):
        self.reindex()
        # Сюжеты из базы; если у части новостей их еще нет (первый запуск, переклассификация) — расчет
        # по всем, а сохраненные значения важнее расчетных. Воркер затем сохраняет недостающие (persist_stories).
        saved = {k: v["story_id"] for k, v in self.items.items() if v.get("story_id")}
        if len(saved) < len(self.items):
            computed = _assign_stories(sorted(self.items.values(), key=lambda i: i["published_at"]))
            saved = computed | {k: v for k, v in saved.items() if v in self.items or v == k}
        self.stories = saved
        self.members = {}
        for news_id, story_id in sorted(self.stories.items(), key=lambda kv: self.items[kv[0]]["published_at"]):
            self.members.setdefault(story_id, []).append(news_id)

    def nearest(self, item: dict) -> str:
        """Сюжет для новой новости — без пересчета остальных."""
        return _nearest_story(item, [self.items[i] for i in self.items if i != item["news_id"]], self.stories)

    def attach(self, item: dict) -> None:
        story_id = item.get("story_id") or self.nearest(item)
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
    # Существенность для крупного бизнеса — только для новой новости с темами (не демо-ленты).
    verdict = None
    if llm and cls.topics and kind != "seed":
        verdict = materiality.assess(title, text)
    return {
        **({"materiality": verdict} if verdict else {}),
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


def _companies(title: str) -> set[str]:
    """Названия компаний в заголовке: в кавычках «», с заглавной внутри слова (ФосАгро) или латиницей.
    Фамилии и страны сюда не попадают — «Новак» или «Украина» в разных событиях не делают их одним сюжетом."""
    names = {m.group(1) for m in _QUOTED.finditer(title)}
    names |= {w for w in _WORD.findall(title)
              if (any(c.isupper() for c in w[1:]) and not w.isupper()) or (w[0].isascii() and len(w) > 2)}
    return {n.lower().replace("ё", "е")[:5] for n in names if len(n) >= 3 and not _ROMAN.fullmatch(n)}


def _same_story(sim: float, a: dict, b: dict) -> bool:
    if sim >= config.story_similarity():
        return True
    return (sim >= ENTITY_STORY_SIMILARITY and abs(_time(a) - _time(b)) <= ENTITY_STORY_DAYS * 86400
            and bool(_companies(a["title"]) & _companies(b["title"])))


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
            match = next((int(k) for k in np.argsort(-sims) if sims[k] >= ENTITY_STORY_SIMILARITY
                          and _same_story(float(sims[k]), item, items_asc[start + int(k)])), None)
            if match is not None:
                story = stories[items_asc[start + match]["news_id"]]
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
    match = next((int(k) for k in np.argsort(-sims) if sims[k] >= ENTITY_STORY_SIMILARITY
                  and _same_story(float(sims[k]), item, window[int(k)])), None)
    return stories[window[match]["news_id"]] if match is not None else item["news_id"]


def _version() -> str:
    """Подпись словарей, правил и модели: при ее смене все новости переклассифицируются."""
    here = Path(__file__).parent
    parts = [SEED_FILE.read_bytes()] + [(here / f).read_bytes() for f in
                                        ("classifier.py", "taxonomy.py", "semantic.py", "magnitude.py")]
    # Словари тем — данные (SPR4-00): подпись действующей конфигурации вместо текста taxonomy.py.
    return hashlib.sha256(b"".join(parts) + embeddings.signature().encode() + runtime.signature().encode()).hexdigest()


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
            if previous.payload.get("story_id"):
                it["story_id"] = previous.payload["story_id"]
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
                       **({"story_id": previous["story_id"]} if previous.get("story_id") else {}),
                       content_filtered=previous.get("content_filtered", False) or updated["content_filtered"])
        if previous.get("materiality"):  # ответ модели не запрашивается повторно
            updated["materiality"] = previous["materiality"]
        record.payload = updated
    db.flush()
    database.set_state(VERSION_KEY, version, db)
    _bump(db)
    logger.info("news reclassified: seed=%d stored=%d", len(seed), len(records))


def _read_all(db) -> tuple[dict[str, dict], datetime | None]:
    rows = db.execute(select(News.payload, News.updated_at)).all()
    return {p["news_id"]: p for p, _ in rows}, max((u for _, u in rows), default=None)


def _read_changed(db, state: _State) -> tuple[dict[str, dict], datetime | None]:
    """Новости, измененные после прошлой загрузки: API не перечитывает весь набор при каждом изменении."""
    if state.seen is None:
        return _read_all(db)
    rows = db.execute(select(News.payload, News.updated_at).where(News.updated_at >= state.seen - DELTA_OVERLAP)).all()
    items = dict(state.items) | {p["news_id"]: p for p, _ in rows}
    return items, max([state.seen, *(u for _, u in rows)])


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
        items, seen = _read_all(db)
        _state = _State(items, int(database.state(REV_KEY, db) or 0), seen)
        return _state
    rev = int(database.state(REV_KEY, db) or 0)
    if rev != _state.rev:
        # Тексты записей не меняются (объединение дописывает только источники) — шинглы переиспользуются.
        items, seen = _read_changed(db, _state)
        _state = _State(items, rev, seen, shingles=_state.shingles)
    _state.checked = time.monotonic()
    return _state


def _news_vectors(items: list[dict]) -> None:
    """Заголовки в векторном хранилище: по ним агент ищет предыдущие события сюжета."""
    vectors.sync(vector_store.NEWS, [(i["news_id"], i["title"], {
        "published_at": i["published_at"], "topics": [t["topic"] for t in i["classification"]["topics"]]})
        for i in items])


def load() -> int:
    """Загрузка в память (API): переклассификацию при смене словарей обычно уже сделал воркер."""
    with _lock:
        return len(_state_now(force=True).items)


def warm() -> int:
    """Воркер: переклассификация при необходимости, загрузка в память и векторы заголовков."""
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
        item = _state_now().items.get(news_id)
        if item is None:
            # Новость могли только что добавить через другой экземпляр API: не ждать плановой перепроверки.
            item = _state_now(force=True).items.get(news_id)
        return item


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


def set_materiality(news_id: str, verdict: dict) -> None:
    """Сохранить ответ проверки существенности (записи в памяти общие — заменяется копией)."""
    with _lock:
        with database.session() as db:
            db.execute(select(func.pg_advisory_xact_lock(NEWS_LOCK)))
            state = _state_now(db)
            item = state.items.get(news_id)
            if item is None:
                return
            saved = {**item, "materiality": verdict}
            db.get(News, news_id).payload = saved
            rev = _bump(db)
        state.items[news_id] = saved
        state.rev = rev
        state.reindex()


def persist_stories() -> int:
    """Воркер: сохранить в базе сюжеты, рассчитанные в памяти (у новых записей и после переклассификации)."""
    with _lock:
        with database.session() as db:
            db.execute(select(func.pg_advisory_xact_lock(NEWS_LOCK)))
            state = _state_now(db, force=True)
            todo = {k: sid for k, sid in state.stories.items() if state.items[k].get("story_id") != sid}
            if not todo:
                return 0
            for record in db.scalars(select(News).where(News.news_id.in_(list(todo)))):
                record.story_id = todo[record.news_id]
                record.payload = {**record.payload, "story_id": todo[record.news_id]}
                state.items[record.news_id] = record.payload
            state.rev = _bump(db)
        state.reindex()
    logger.info("news stories persisted: %d", len(todo))
    return len(todo)


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
                saved, created = {**item, "story_id": state.nearest(item)}, True
                db.add(News(news_id=saved["news_id"], published_at=datetime.fromisoformat(saved["published_at"]),
                            kind=saved["kind"], story_id=saved["story_id"], payload=saved))
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


MATERIALITY_FAILURES_IN_ROW = 3  # единичный сбой шлюза пропускаем; несколько подряд — модель недоступна


def check_materiality(limit: int = 40, recheck_rejected: bool = False, recheck_all: bool = False,
                      checked_before: str | None = None) -> int:
    """Проверить существенность еще не проверенных новостей с темами (сначала свежие). Возвращает число проверенных.

    recheck_rejected — перепроверить и отсеянные, recheck_all — все (после уточнения критерия).
    """
    if not materiality.enabled():
        return 0
    todo = [n for n in all_items()
            if n["classification"]["topics"] and n.get("kind") != "seed"
            and ("materiality" not in n or recheck_all
                 or (recheck_rejected and n["materiality"].get("material") is False)
                 or (checked_before and n["materiality"].get("checked_at", "") < checked_before))][:limit]
    done = failures = 0
    for n in todo:
        verdict = materiality.assess(n["title"], n["text"])
        if verdict is None:
            failures += 1
            if failures >= MATERIALITY_FAILURES_IN_ROW:
                break  # модель недоступна или исчерпан лимит — продолжим в следующем цикле
            continue
        failures = 0
        set_materiality(n["news_id"], verdict)
        done += 1
    return done


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Проверить существенность уже собранных новостей")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--recheck-rejected", action="store_true", help="перепроверить отсеянные новости")
    parser.add_argument("--recheck-all", action="store_true", help="перепроверить все (после изменения критерия)")
    parser.add_argument("--checked-before", help="перепроверить проверенные раньше этого времени (ISO)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(f"проверено новостей: {check_materiality(args.limit, args.recheck_rejected, args.recheck_all, args.checked_before)}")
