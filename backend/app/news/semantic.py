"""Темы новости по смыслу: сравнение с описаниями тем через embedding-модель.

Дополняет словари классификатора, а не заменяет их. Порог подобран на реальной
ленте RSS: модель охотно видит «ключевую ставку» в любом заявлении чиновника,
поэтому новость сначала сравнивается с примерами «не про бизнес» (политика,
спорт, происшествия), и тема по смыслу добавляется только с запасом над ними.
"""

from functools import lru_cache

from app import embeddings
from app.news.taxonomy import TOPIC_MEANINGS

# Примеры новостей «не про бизнес»: если новость ближе к ним, темы по смыслу не добавляются.
NON_BUSINESS = [
    "Политик сделал заявление о другой стране",
    "Политик раскритиковал или высмеял другого политика",
    "Военные действия, атаки беспилотников и обстрелы",
    "Военная операция, удары по объектам, армия и вооруженные силы",
    "Спортивный матч, футбол, хоккей и спортсмены",
    "Культура, кино, искусство и религия",
    "Криминальное происшествие, суд и арест",
    "Дипломатические переговоры и встречи лидеров государств",
    "Чиновник назначен на должность или получил награду",
    "Новости науки, образования и туризма",
]

MIN_SIM = 0.50          # тема по смыслу рядом со словарными темами
NEAR_TOP = 0.04         # и не дальше этого от лучшей смысловой темы новости
MIN_MARGIN = 0.10       # запас над «не про бизнес», если словари уже нашли темы
ONLY_MIN_SIM = 0.48     # тема только по смыслу, словари ничего не нашли
ONLY_MIN_MARGIN = 0.30  # и запас над «не про бизнес» заметно больше
MAX_ADDED = 2


@lru_cache(maxsize=4)
def _prototypes(signature: str):
    keys = [k for k, phrases in TOPIC_MEANINGS.items() for _ in phrases]
    vectors = embeddings.embed([p for phrases in TOPIC_MEANINGS.values() for p in phrases])
    negatives = embeddings.embed(NON_BUSINESS)
    if vectors is None or negatives is None:
        return None
    return keys, vectors, negatives


def analyze(title: str, text: str, keyword_topics: set[str]) -> dict | None:
    """Смысловые оценки тем и предложенные новые темы; None — модель недоступна."""
    protos = _prototypes(embeddings.signature())
    if protos is None:
        return None
    vec = embeddings.embed([f"{title}. {(text or '')[:300]}"])
    if vec is None:
        return None
    keys, vectors, negatives = protos
    news = vec[0]
    sims: dict[str, float] = {}
    for key, proto in zip(keys, vectors):
        sims[key] = max(sims.get(key, -1.0), embeddings.cosine(news, proto))
    non_business = max(embeddings.cosine(news, n) for n in negatives)
    ranked = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)
    best = ranked[0][1]
    if keyword_topics:
        floor, margin = MIN_SIM, MIN_MARGIN
    else:
        floor, margin = ONLY_MIN_SIM, ONLY_MIN_MARGIN
    added = [k for k, s in ranked[:MAX_ADDED]
             if k not in keyword_topics and s >= floor and s >= best - NEAR_TOP and s - non_business >= margin]
    return {"sims": {k: round(float(s), 3) for k, s in sims.items()}, "non_business": round(float(non_business), 3),
            "added": added}
