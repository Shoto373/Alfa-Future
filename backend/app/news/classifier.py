"""Классификация новости и извлечение ключевой информации на правилах.

Работает без LLM: темы, отрасли, страны, направление события, участники,
даты, числа и ключевые предложения. Темы ищутся по словарю и по смыслу
(локальная embedding-модель, app.news.semantic); без модели — только по словарю.
"""

import re
from bisect import bisect_left
from dataclasses import dataclass, field

from app.news import magnitude, semantic
from app.news.taxonomy import ACTORS, COUNTRY_STEMS, DIRECTION_STEMS, SECTOR_STEMS, TOPICS

# «Санкции» засчитываются только рядом с деловым контекстом — и по словарю, и по смыслу.
SANCTIONS_BUSINESS_STEMS = ["санкц", "swift", "эмбарго", "экспорт", "импорт", "платеж", "банков", "компани", "торгов",
                            "поставк", "тариф", "пошлин", "финанс"]
SEMANTIC_TOPIC_SCORE = 2  # как слабое словарное совпадение: тема по смыслу не перевешивает явную
WEAK_TOPIC_SCORE = 2      # одно упоминание в тексте — слабый сигнал темы
LLM_TOPIC_SCORE = 3       # тема от модели-классификатора: сильнее одного упоминания, слабее явной словарной
NON_BUSINESS_MARGIN = 0.15  # насколько новость должна быть ближе к «не про бизнес», чтобы снять слабые темы

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


def _index(tokens: list[str]) -> tuple[list[str], list[int], list[str]]:
    """Токены, их позиции в порядке сортировки и сами отсортированные токены (поиск по префиксу)."""
    order = sorted(range(len(tokens)), key=tokens.__getitem__)
    return tokens, order, [tokens[i] for i in order]


_MAX_CHAR = "􏿿"


def _count_stem(tokens: list[str], stem: str, index=None) -> int:
    """Число позиций, где подряд идущие токены начинаются с частей стема.

    Токены с нужным префиксом — непрерывный диапазон отсортированного списка (bisect),
    поэтому стем не сравнивается с каждым токеном текста.
    """
    parts = stem.split()
    if not parts:
        return len(tokens) + 1
    toks, order, ordered = index or _index(tokens)
    lo = bisect_left(ordered, parts[0])
    hi = bisect_left(ordered, parts[0] + _MAX_CHAR, lo)
    n = len(parts)
    if n == 1:
        return hi - lo
    limit = len(toks) - n
    return sum(1 for i in order[lo:hi] if i <= limit and all(toks[i + j].startswith(parts[j]) for j in range(1, n)))


def _score(tokens: list[str], stems: list[str]) -> tuple[int, list[str]]:
    total, matched = 0, []
    index = _index(tokens)
    for stem in stems:
        c = _count_stem(tokens, stem, index)
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
    magnitude: dict | None = None                           # сила события по главной теме
    uncertain: bool = False                                 # словари и смысл не уверены — стоит спросить модель
    llm_hint: dict | None = None                            # ответ модели-классификатора, если спрашивали

    def topic_keys(self) -> list[str]:
        return [t["topic"] for t in self.topics]

    def as_dict(self) -> dict:
        return {
            "topics": self.topics, "sectors": self.sectors, "countries": self.countries,
            "direction": self.direction, "topic_directions": self.topic_directions, "actors": self.actors, "dates": self.dates,
            "numbers": self.numbers, "key_sentences": self.key_sentences, "importance": round(self.importance, 3),
            "magnitude": self.magnitude,
            **({"llm_hint": self.llm_hint} if self.llm_hint else {}),
        }


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split((text or "").strip()) if len(s.strip()) > 20]


def classify(title: str, text: str, hint: dict | None = None) -> Classification:
    """hint — ответ модели-классификатора (app.news.llm_classify) для неуверенных случаев."""
    full = f"{title}. {text}"
    tokens = tokenize(full)
    title_tokens = tokenize(title)

    topics = []
    for key, spec in TOPICS.items():
        score, matched = _score(tokens, spec["stems"])
        score += 2 * _score(title_tokens, spec["stems"])[0]  # заголовок важнее
        if key == "sanctions_geopolitics" and not _score(tokens, SANCTIONS_BUSINESS_STEMS)[0]:
            continue
        if score:
            topics.append({"topic": key, "name": spec["name"], "score": score, "matched": matched})
    # Смысловые темы (embedding-модель): находят тему без слов из словаря,
    # например «мегарегулятор оставил стоимость заимствований» — ключевая ставка.
    meaning = semantic.analyze(title, text, {t["topic"] for t in topics})
    if meaning:
        for t in topics:
            t["semantic"] = meaning["sims"][t["topic"]]
        for key in meaning["added"]:
            if key == "sanctions_geopolitics" and not _score(tokens, SANCTIONS_BUSINESS_STEMS)[0]:
                continue
            topics.append({"topic": key, "name": TOPICS[key]["name"], "score": SEMANTIC_TOPIC_SCORE,
                           "matched": [f"по смыслу ({meaning['sims'][key]:.2f})"], "semantic": meaning["sims"][key]})
    # Только слабые словарные совпадения, а по смыслу новость ближе к «не про бизнес» (спорт, политика,
    # происшествия): «зарплаты футболистов» не делают матч новостью о рынке труда.
    if meaning and topics and max(t["score"] for t in topics) <= WEAK_TOPIC_SCORE:
        best = max((meaning["sims"].get(t["topic"], -1.0) for t in topics), default=-1.0)
        if meaning["non_business"] - best >= NON_BUSINESS_MARGIN:
            topics = []
    # Неуверенность: тем нет, но по смыслу новость не явно «не про бизнес», или тема одна и слабая.
    best_meaning = max(meaning["sims"].values(), default=-1.0) if meaning else -1.0
    uncertain = (not topics and (meaning is None or meaning["non_business"] - best_meaning < NON_BUSINESS_MARGIN)) \
        or (len(topics) == 1 and topics[0]["score"] <= WEAK_TOPIC_SCORE)
    if hint:
        if not hint.get("business"):
            topics = []
        else:
            have = {t["topic"] for t in topics}
            for key in hint.get("topics", []):
                if key in TOPICS and key not in have:
                    topics.append({"topic": key, "name": TOPICS[key]["name"], "score": LLM_TOPIC_SCORE,
                                   "matched": [f"модель-классификатор ({hint.get('model', 'LLM')})"]})
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
    sentence_tokens = [tokenize(s) for s in sentences_all]
    topic_directions = {}
    for t in topics:
        stems = TOPICS[t["topic"]]["stems"]
        local = [tk for tk in sentence_tokens if _score(tk, stems)[0]]
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

    # Сила события — по предложениям о главной теме; если их нет, по заголовку и началу текста.
    main = topics[0]["topic"] if topics else None
    about_main = [s for s, tk in zip(sentences_all, sentence_tokens) if main and _score(tk, TOPICS[main]["stems"])[0]]
    strength = magnitude.assess(main, about_main or sentences_all[:3])
    return Classification(topics, sectors, countries, direction, topic_directions, actors, dates, numbers, key_sentences,
                          importance, strength, uncertain, hint)
