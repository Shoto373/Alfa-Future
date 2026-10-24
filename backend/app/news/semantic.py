"""Темы новости по смыслу: сравнение с описаниями тем через embedding-модель.

Дополняет словари классификатора, а не заменяет их. Порог подобран на реальной
ленте RSS: модель охотно видит «ключевую ставку» в любом заявлении чиновника,
поэтому новость сначала сравнивается с примерами «не про бизнес» (политика,
спорт, происшествия), и тема по смыслу добавляется только с запасом над ними.
"""

from functools import lru_cache

import numpy as np

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
    # Отдельный социальный объект по поручению — не изменение рынка, даже если в заголовке «строительство».
    "Президент или губернатор поручил построить школу, больницу, кампус или другой социальный объект в регионе",
    "Спортсмен завоевал медаль, назначен тренер команды, результат матча или турнира",
    "Телепередача, юбилей, премия, рейтинг университетов, выход фильма или книги",
    "Происшествие на пляже или в аэропорту, ограничения для туристов и пассажиров",
    "Бытовой случай, суд по частному спору, конфликт знаменитостей",
]

MIN_SIM = 0.50          # тема по смыслу рядом со словарными темами
NEAR_TOP = 0.04         # и не дальше этого от лучшей смысловой темы новости
MIN_MARGIN = 0.10       # запас над «не про бизнес», если словари уже нашли темы
ONLY_MIN_SIM = 0.48     # тема только по смыслу, словари ничего не нашли
ONLY_MIN_MARGIN = 0.30  # и запас над «не про бизнес» заметно больше
MAX_ADDED = 2


@lru_cache(maxsize=4)
def _prototypes(signature: str):
    """Матрицы описаний тем и примеров «не про бизнес»; строки одной темы идут подряд."""
    topics = [k for k, phrases in TOPIC_MEANINGS.items() if phrases]
    starts = np.cumsum([0] + [len(TOPIC_MEANINGS[k]) for k in topics[:-1]])
    vectors = embeddings.embed([p for k in topics for p in TOPIC_MEANINGS[k]])
    negatives = embeddings.embed(NON_BUSINESS)
    if vectors is None or negatives is None:
        return None
    return topics, starts, embeddings.as_matrix(vectors), embeddings.as_matrix(negatives)


def warm() -> bool:
    """Старт сервиса: векторы описаний тем и примеров «не про бизнес»."""
    return _prototypes(embeddings.signature()) is not None


def text_for(title: str, text: str) -> str:
    """Текст, по которому новость сравнивается с темами (заголовок и начало)."""
    return f"{title}. {(text or '')[:300]}"


def prime(pairs: list[tuple[str, str]]) -> None:
    """Считает векторы пачкой заранее (быстрее, чем по одной новости при классификации)."""
    if pairs and _prototypes(embeddings.signature()) is not None:
        embeddings.embed([text_for(t, x) for t, x in pairs])


def analyze(title: str, text: str, keyword_topics: set[str]) -> dict | None:
    """Смысловые оценки тем и предложенные новые темы; None — модель недоступна."""
    protos = _prototypes(embeddings.signature())
    if protos is None:
        return None
    vec = embeddings.embed([text_for(title, text)])
    if vec is None:
        return None
    topics, starts, vectors, negatives = protos
    news = embeddings.as_matrix(vec)[0]
    by_topic = np.maximum.reduceat(vectors @ news, starts)
    sims = {k: float(s) for k, s in zip(topics, by_topic)}
    non_business = float(np.max(negatives @ news))
    ranked = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)
    best = ranked[0][1]
    if keyword_topics:
        floor, margin = MIN_SIM, MIN_MARGIN
    else:
        floor, margin = ONLY_MIN_SIM, ONLY_MIN_MARGIN
    added = [k for k, s in ranked[:MAX_ADDED]
             if k not in keyword_topics and s >= floor and s >= best - NEAR_TOP and s - non_business >= margin]
    return {"sims": {k: round(s, 3) for k, s in sims.items()}, "non_business": round(non_business, 3),
            "added": added}
