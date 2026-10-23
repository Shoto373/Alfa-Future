"""Качество классификации на синтетическом эталоне (tests/fixtures/golden_news.json).

В CI модели смысла нет — проверяется словарный путь; пороги не дают правкам словарей незаметно
ухудшить отбор новостей. Полная оценка со смыслом — python -m app.eval_classify.
"""

from app import eval_classify


def test_keyword_classification_meets_quality_bar():
    s = eval_classify.evaluate()["summary"]
    assert s["business_acc"] >= 0.9, s
    assert s["topic_recall"] >= 0.88, s
    assert s["noise_rate"] == 0.0, s   # не деловые новости не должны попадать в ленту
