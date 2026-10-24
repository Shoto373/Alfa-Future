"""Классификация новости и извлечение ключевой информации на правилах.

Работает без LLM: темы, отрасли, страны, направление события, участники,
даты, числа и ключевые предложения. Темы ищутся по словарю и по смыслу
(локальная embedding-модель, app.news.semantic); без модели — только по словарю.
"""

import re
from bisect import bisect_left
from dataclasses import dataclass, field

from app.news import magnitude, semantic
from app.news.taxonomy import (ACTORS, BANK_OF_RUSSIA, CENTRAL_BANK_WORDS, COUNTRY_STEMS, DIRECTION_STEMS,
                               FOREIGN_CENTRAL_BANKS, FOREIGN_CURRENCY, FOREIGN_DIRECTION, RUBLE_DIRECTION,
                               SANCTIONS_DIRECTION, SECTOR_STEMS, TOPICS)

# «Санкции» засчитываются только рядом с деловым контекстом — и по словарю, и по смыслу.
SANCTIONS_BUSINESS_STEMS = ["санкц", "swift", "эмбарго", "экспорт", "импорт", "платеж", "банков", "компани", "торгов",
                            "поставк", "тариф", "пошлин", "финанс"]
# Признаки делового контекста — шире словарей тем. Тема только по смыслу (словари ничего не нашли) добавляется,
# лишь если в новости есть хоть один из них: «мегарегулятор оставил стоимость заимствований» — да,
# «постпред назвал ОБСЕ окопом» или «министерство предложило удостоверение учителя» — нет: модель смысла
# путает с ключевой ставкой сам жанр «ведомство приняло решение».
# Слова сравниваются по началу, поэтому без коротких основ-ловушек: «евро» — «Европа» (валюту ловят «валют»,
# «доллар», «рубл»), «цен» — «центр»,
# «груз» — «Грузия», «долг» — «долгий», «акци» — «акция протеста».
BUSINESS_CONTEXT_STEMS = ["рубл", "доллар", "юан", "валют", "деньг", "денежн", "цена", "цены", "ценам", "ценах", "ценов",
                          "ценн бумаг", "стоимост", "подорож", "подешев", "тариф", "рын", "бирж", "акционер", "облигац",
                          "кредит", "заем", "займ", "заимств", "задолжен", "долга", "долгов", "ставк", "процент", "инфляц",
                          "банк", "бюджет", "налог", "пошлин", "экспорт", "импорт", "компани", "бизнес", "предприят",
                          "производ", "выручк", "прибыл", "убыт", "инвест", "экономик", "ввп", "зарплат", "спрос", "поставк",
                          "логистик", "перевоз", "грузов", "грузоп", "нефт", "топлив", "металл", "сырь", "товар",
                          "торгов", "отрасл", "промышлен", "млрд", "млн", "трлн", "регулятор", "мегарегулятор", "дивиденд",
                          "санкц", "финанс", "капитал", "ликвидн", "депозит", "лизинг", "ипотек"]
# Разных деловых слов не меньше: одно случайное («бюджетное учреждение» в новости об учителях) — не контекст.
BUSINESS_CONTEXT_MIN = 2
SEMANTIC_TOPIC_SCORE = 2  # как слабое словарное совпадение: тема по смыслу не перевешивает явную
WEAK_TOPIC_SCORE = 2      # одно упоминание в тексте — слабый сигнал темы
LLM_TOPIC_SCORE = 3       # тема от модели-классификатора: сильнее одного упоминания, слабее явной словарной
NON_BUSINESS_MARGIN = 0.15  # насколько новость должна быть ближе к «не про бизнес», чтобы снять слабые темы
# Даже сильное словарное совпадение не делает новость деловой, если по смыслу она ближе к «не про бизнес»:
# «гимнастка завоевала серебро» (золото), «тренер «Металлурга»» (металлургия), «пляж закрыли из-за разлива нефти».
STRONG_NON_BUSINESS_MARGIN = 0.03
# Тема по одному упоминанию в тексте остается, только если новость действительно о ней по смыслу
# («Силуанов посоветовал жить экономнее» — 0,52 к ставке, «ЦБ сохранил ставку» — 0,6+).
WEAK_TOPIC_MIN_SIM = 0.55

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


def _fx_direction(sentences: list[list[str]]) -> dict[str, int]:
    """Направление курса (up — ослабление рубля) по глаголам при рубле и при иностранной валюте."""
    out = {"up": 0, "down": 0}
    for tk in sentences:
        for currency, verbs in ((["рубл"], RUBLE_DIRECTION), (FOREIGN_CURRENCY, FOREIGN_DIRECTION)):
            if _score(tk, currency)[0]:
                for d, st in verbs.items():
                    out[d] += _score(tk, st)[0]
    return out


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


def _dictionary_topics(tokens: list[str], title_tokens: list[str]) -> list[dict]:
    """Темы по словарям; совпадение в заголовке весит вдвое больше."""
    topics = []
    for key, spec in TOPICS.items():
        score, matched = _score(tokens, spec["stems"])
        score += 2 * _score(title_tokens, spec["stems"])[0]  # заголовок важнее
        if key == "sanctions_geopolitics" and not _score(tokens, SANCTIONS_BUSINESS_STEMS)[0]:
            continue
        if score:
            topics.append({"topic": key, "name": spec["name"], "score": score, "matched": matched})
    return topics


def _semantic_topics(topics: list[dict], title: str, text: str, tokens: list[str]) -> tuple[list[dict], dict | None]:
    """Смысловые темы (embedding-модель): находят тему без слов из словаря,
    например «мегарегулятор оставил стоимость заимствований» — ключевая ставка."""
    # Опора для смысла — только значимые словарные темы: слабое совпадение («бюджетных» в новости об учителях,
    # «торговле» в новости о договоре по оружию) позже отсеивается и не должно смягчать порог смысловой темы.
    strong = {t["topic"] for t in topics if t["score"] > 1}
    meaning = semantic.analyze(title, text, strong)
    if meaning and not strong and len(_score(tokens, BUSINESS_CONTEXT_STEMS)[1]) < BUSINESS_CONTEXT_MIN:
        meaning = {**meaning, "added": []}  # ни словарных тем, ни делового контекста — смысл не добавляет тему
    if meaning:
        for t in topics:
            t["semantic"] = meaning["sims"][t["topic"]]
        have = {t["topic"] for t in topics}
        for key in meaning["added"]:
            if key in have:  # слабая словарная тема подтверждена смыслом — остается одна запись
                continue
            if key == "sanctions_geopolitics" and not _score(tokens, SANCTIONS_BUSINESS_STEMS)[0]:
                continue
            topics.append({"topic": key, "name": TOPICS[key]["name"], "score": SEMANTIC_TOPIC_SCORE,
                           "matched": [f"по смыслу ({meaning['sims'][key]:.2f})"], "semantic": meaning["sims"][key]})
    # Тема по одному упоминанию в тексте (не в заголовке) — повод, а не предмет новости, если смысл ее не подтверждает:
    # «на пресс-конференции по итогам заседания по ключевой ставке» в новости о цифровом рубле.
    if meaning:
        topics = [t for t in topics if t["score"] > WEAK_TOPIC_SCORE or _score(tokenize(title), TOPICS[t["topic"]]["stems"])[0]
                  or t.get("semantic", meaning["sims"].get(t["topic"], 0)) >= WEAK_TOPIC_MIN_SIM]
    # Только слабые словарные совпадения, а по смыслу новость ближе к «не про бизнес» (спорт, политика,
    # происшествия): «зарплаты футболистов» не делают матч новостью о рынке труда.
    if meaning and topics and max(t["score"] for t in topics) <= WEAK_TOPIC_SCORE:
        best = max((meaning["sims"].get(t["topic"], -1.0) for t in topics), default=-1.0)
        if meaning["non_business"] - best >= NON_BUSINESS_MARGIN:
            topics = []
    if meaning and topics:
        best = max((meaning["sims"].get(t["topic"], -1.0) for t in topics), default=-1.0)
        if meaning["non_business"] - best >= STRONG_NON_BUSINESS_MARGIN:
            topics = []
    return topics, meaning


def _with_hint(topics: list[dict], hint: dict | None) -> list[dict]:
    """Ответ модели-классификатора: «не про бизнес» снимает темы, новые темы добавляются."""
    if not hint:
        return topics
    if not hint.get("business"):
        return []
    have = {t["topic"] for t in topics}
    for key in hint.get("topics", []):
        if key in TOPICS and key not in have:
            topics.append({"topic": key, "name": TOPICS[key]["name"], "score": LLM_TOPIC_SCORE,
                           "matched": [f"модель-классификатор ({hint.get('model', 'LLM')})"]})
    return topics


def _topic_direction(topic: str, sentence_tokens: list[list[str]], direction: str | None) -> str | None:
    """Направление темы — по предложениям, где тема упоминается.
    Для кредитования «ужесточение» означает меньше кредита (down), «смягчение» — больше (up)."""
    stems = TOPICS[topic]["stems"]
    local = [tk for tk in sentence_tokens if _score(tk, stems)[0]]
    counts = {d: sum(_score(tk, st)[0] for tk in local) for d, st in DIRECTION_STEMS.items()}
    if topic == "credit_market":
        tight = sum(_score(tk, ["ужесточ"])[0] for tk in local)
        soft = sum(_score(tk, ["смягчени", "смягч"])[0] for tk in local)
        counts["up"] = max(counts["up"] - tight, 0) + soft
        counts["down"] = counts["down"] - soft + 2 * tight
    own = bool(local)
    if topic == "fx":
        # Валюта названа прямо («рубль», «доллар») — направление читается по любому такому предложению,
        # даже если тема найдена по смыслу, а не по словарю.
        fx = _fx_direction(sentence_tokens)
        if fx["up"] or fx["down"]:
            counts, own = {**fx, "hold": counts["hold"]}, True
    if topic == "sanctions_geopolitics":
        for d, st in SANCTIONS_DIRECTION.items():
            counts[d] += sum(_score(tk, st)[0] for tk in local)
    best = max(counts, key=counts.get)
    # Тема только «по смыслу» (нет своих предложений): направление другой темы ей не переносится —
    # «ставка повышена» не значит «экономика растет».
    return best if counts[best] > 0 else direction if own else None


def _key_sentences(text: str, topics: list[dict]) -> list[str]:
    """Три главных предложения текста (о темах, с числами и датами) — в исходном порядке."""
    sentences = split_sentences(text) or [text.strip()]
    topic_stems = [s for t in topics for s in TOPICS[t["topic"]]["stems"]]
    ranked = sorted(
        sentences,
        key=lambda s: (_score(tokenize(s), topic_stems)[0] + 2 * bool(_NUMBER.search(s)) + bool(_DATE.search(s))),
        reverse=True,
    )
    return [s for s in sentences if s in ranked[:3]]


def _foreign_monetary_policy(title_tokens: list[str]) -> bool:
    """Заголовок о ставке иностранного регулятора (ЦБ Турции, ФРС, ЕЦБ), без упоминания Банка России.
    Ключевая ставка в таксономии — ставка Банка России: чужая ставка напрямую стоимость рублевого долга не меняет."""
    if any(_count_stem(title_tokens, s) for s in BANK_OF_RUSSIA):
        return False
    if any(_count_stem(title_tokens, s) for s in FOREIGN_CENTRAL_BANKS):
        return True
    # «ЦБ Турции», «Нацбанк Казахстана»: страна — сразу после слова о центробанке («курс юаня и ставка ЦБ» — не то).
    countries = [s for stems in COUNTRY_STEMS.values() for s in stems]
    for words in (w.split() for w in CENTRAL_BANK_WORDS):
        for i in range(len(title_tokens) - len(words)):
            if all(title_tokens[i + k].startswith(w) for k, w in enumerate(words))                     and any(title_tokens[i + len(words)].startswith(c) for c in countries):
                return True
    return False


def classify(title: str, text: str, hint: dict | None = None) -> Classification:
    """hint — ответ модели-классификатора (app.news.llm_classify) для неуверенных случаев."""
    full = f"{title}. {text}"
    tokens = tokenize(full)
    title_tokens = tokenize(title)

    topics, meaning = _semantic_topics(_dictionary_topics(tokens, title_tokens), title, text, tokens)
    # Неуверенность: тем нет, но по смыслу новость не явно «не про бизнес», или тема одна и слабая.
    best_meaning = max(meaning["sims"].values(), default=-1.0) if meaning else -1.0
    uncertain = (not topics and (meaning is None or meaning["non_business"] - best_meaning < NON_BUSINESS_MARGIN)) \
        or (len(topics) == 1 and topics[0]["score"] <= WEAK_TOPIC_SCORE)
    topics = _with_hint(topics, hint)
    if _foreign_monetary_policy(title_tokens):
        topics = [t for t in topics if t["topic"] != "key_rate"]
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

    sentences_all = split_sentences(full) or [full]
    sentence_tokens = [tokenize(s) for s in sentences_all]
    topic_directions = {t["topic"]: _topic_direction(t["topic"], sentence_tokens, direction) for t in topics}

    actors = [a for a in ACTORS if re.search(rf"(?<![А-Яа-яA-Za-z]){re.escape(a)}", full)]
    dates = list(dict.fromkeys(m.group(0).strip() for m in _DATE.finditer(full)))[:6]
    numbers = list(dict.fromkeys(m.group(0).strip() for m in _NUMBER.finditer(full)))[:12]
    importance = max((TOPICS[t["topic"]]["importance"] for t in topics), default=0.0)

    # Сила события — по предложениям о главной теме; если их нет, по заголовку и началу текста.
    main = topics[0]["topic"] if topics else None
    about_main = [s for s, tk in zip(sentences_all, sentence_tokens) if main and _score(tk, TOPICS[main]["stems"])[0]]
    strength = magnitude.assess(main, about_main or sentences_all[:3])
    return Classification(topics, sectors, countries, direction, topic_directions, actors, dates, numbers,
                          _key_sentences(text, topics), importance, strength, uncertain, hint)
