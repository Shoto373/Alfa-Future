"""Классификация новости и извлечение ключевой информации на правилах.

Работает без LLM: темы, отрасли, страны, направление события, участники,
даты, числа и ключевые предложения. При подключенной LLM агент может
уточнить результат, но правила остаются базой и проверкой.
"""

import re
from dataclasses import dataclass, field

from app.news.taxonomy import ACTORS, COUNTRY_STEMS, DIRECTION_STEMS, SECTOR_STEMS, TOPICS

_WORD = re.compile(r"[a-zа-я0-9$%.,/-]+", re.IGNORECASE)
_SENT = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯA-Z«\"0-9])")
_NUMBER = re.compile(
    r"(?:[$€]\s?)?\d[\d\s]*(?:[.,]\d+)?\s?(?:%|п\.п\.|б\.п\.|трлн|млрд|млн|тыс\.?|руб\.?(?:/\$|/юань)?|долл\.?|\$|₽)"
    r"(?:\s?(?:руб\.?|долл\.?|\$|за унцию|г/г|м/м|н/н))?",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b\d{1,2}(?:[–-]\d{1,2})?\s(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"(?:\s\d{4}\s?(?:г\.|года)?)?|\b\d{1,2}\.\d{2}\.\d{4}\b",
    re.IGNORECASE,
)


def tokenize(text: str) -> list[str]:
    return [w.strip(".,").lower().replace("ё", "е") for w in _WORD.findall(text or "") if w.strip(".,")]


def _count_stem(tokens: list[str], stem: str) -> int:
    parts = stem.split()
    n = len(parts)
    hits = 0
    for i in range(len(tokens) - n + 1):
        if all(tokens[i + j].startswith(parts[j]) for j in range(n)):
            hits += 1
    return hits


def _score(tokens: list[str], stems: list[str]) -> tuple[int, list[str]]:
    total, matched = 0, []
    for stem in stems:
        c = _count_stem(tokens, stem)
        if c:
            total += c * len(stem.split())  # многословные совпадения весомее
            matched.append(stem)
    return total, matched


@dataclass
class Classification:
    topics: list[dict] = field(default_factory=list)       # [{topic, name, score, matched}]
    sectors: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    direction: str | None = None                            # up | down | hold | None
    topic_directions: dict = field(default_factory=dict)    # направление по каждой теме
    actors: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    key_sentences: list[str] = field(default_factory=list)
    importance: float = 0.0

    def topic_keys(self) -> list[str]:
        return [t["topic"] for t in self.topics]

    def as_dict(self) -> dict:
        return {
            "topics": self.topics, "sectors": self.sectors, "countries": self.countries,
            "direction": self.direction, "topic_directions": self.topic_directions, "actors": self.actors, "dates": self.dates,
            "numbers": self.numbers, "key_sentences": self.key_sentences, "importance": round(self.importance, 3),
        }


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split((text or "").strip()) if len(s.strip()) > 20]


def classify(title: str, text: str) -> Classification:
    full = f"{title}. {text}"
    tokens = tokenize(full)
    title_tokens = tokenize(title)

    topics = []
    for key, spec in TOPICS.items():
        score, matched = _score(tokens, spec["stems"])
        score += 2 * _score(title_tokens, spec["stems"])[0]  # заголовок важнее
        if key == "sanctions_geopolitics" and not _score(tokens, [
                "санкц", "swift", "эмбарго", "экспорт", "импорт", "платеж", "банков", "компани", "торгов", "поставк", "тариф", "пошлин", "финанс"])[0]:
            continue
        if score:
            topics.append({"topic": key, "name": spec["name"], "score": score, "matched": matched})
    topics.sort(key=lambda t: t["score"], reverse=True)
    if topics:
        top = topics[0]["score"]
        # A single weak body mention ("minister arrived", "contribution to
        # culture", generic "budget") cannot turn an unrelated item into news
        # about corporate finance. No fallback to a score-one topic.
        topics = [t for t in topics if t["score"] >= max(2, top * 0.25)][:5]

    sectors = [s for s, stems in SECTOR_STEMS.items() if _score(tokens, stems)[0]]
    countries = [c for c, stems in COUNTRY_STEMS.items() if _score(tokens, stems)[0]]

    direction_scores = {d: _score(title_tokens, stems)[0] * 2 + _score(tokens[:60], stems)[0]
                        for d, stems in DIRECTION_STEMS.items()}
    best_dir = max(direction_scores, key=direction_scores.get)
    direction = best_dir if direction_scores[best_dir] else None

    # Направление по каждой теме — по предложениям, где тема упоминается.
    # Для кредитования «ужесточение» означает меньше кредита (down), «смягчение» — больше (up).
    sentences_all = split_sentences(full) or [full]
    topic_directions = {}
    for t in topics:
        stems = TOPICS[t["topic"]]["stems"]
        local = [tokenize(s) for s in sentences_all if _score(tokenize(s), stems)[0]]
        counts = {d: sum(_score(tk, st)[0] for tk in local) for d, st in DIRECTION_STEMS.items()}
        if t["topic"] == "credit_market":
            tight = sum(_score(tk, ["ужесточ"])[0] for tk in local)
            soft = sum(_score(tk, ["смягчени", "смягч"])[0] for tk in local)
            counts["up"] = max(counts["up"] - tight, 0) + soft
            counts["down"] = counts["down"] - soft + 2 * tight
        best = max(counts, key=counts.get)
        topic_directions[t["topic"]] = best if counts[best] > 0 else direction

    actors = [a for a in ACTORS if re.search(rf"(?<![А-Яа-яA-Za-z]){re.escape(a)}", full)]
    dates = list(dict.fromkeys(m.group(0).strip() for m in _DATE.finditer(full)))[:6]
    numbers = list(dict.fromkeys(m.group(0).strip() for m in _NUMBER.finditer(full)))[:12]

    sentences = split_sentences(text) or [text.strip()]
    topic_stems = [s for t in topics for s in TOPICS[t["topic"]]["stems"]]
    ranked = sorted(
        sentences,
        key=lambda s: (_score(tokenize(s), topic_stems)[0] + 2 * bool(_NUMBER.search(s)) + bool(_DATE.search(s))),
        reverse=True,
    )
    key_sentences = [s for s in sentences if s in ranked[:3]]  # в исходном порядке

    importance = max((TOPICS[t["topic"]]["importance"] for t in topics), default=0.0)
    return Classification(topics, sectors, countries, direction, topic_directions, actors, dates, numbers, key_sentences, importance)
