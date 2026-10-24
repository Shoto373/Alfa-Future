"""Сила события: насколько велико изменение, о котором пишет новость.

«ЦБ сохранил ставку» и «ЦБ поднял ставку на 2 п.п.» — одно направление темы,
но разный масштаб. Оценка строится по числам в предложениях о главной теме:
п.п./б.п. для ставок и доходностей, проценты для цен и курса, «в N раз»,
плюс маркеры «рекордный», «впервые с» (сильное — только при сравнении за годы). Порог зависит от темы: 0,5% за неделю
для цен — много, 0,5% за год для курса — мало. Если чисел нет, сила неизвестна
(None), и ранжирование ее не учитывает.
"""

import re

_NUM = r"(\d+(?:[.,]\d+)?)"
_PP = re.compile(rf"на\s+{_NUM}\s*(п\.\s?п\.|б\.\s?п\.|процентн\w*\s+пункт\w*|базисн\w*\s+пункт\w*)", re.I)
_PCT = re.compile(rf"на\s+{_NUM}\s*%", re.I)
_RUB = re.compile(rf"на\s+{_NUM}\s*(руб\w*|коп\w*)", re.I)
_TIMES = re.compile(rf"в\s+{_NUM}\s+раз", re.I)
_WEEKLY = re.compile(r"н/н|за неделю|недел", re.I)
_HOLD = re.compile(r"сохранил\w*|без изменени\w*|не изменил\w*|оставил\w*", re.I)
_RECORD = re.compile(r"рекордн\w*|максимальн\w*\s+с\s+\d{4}|впервые\s+(?:с|за)\s|обвал\w*|резк\w*", re.I)
# Маркер говорит о сильном изменении, только если сравнение — за годы: «впервые с 2022 года», «впервые за 3 года»,
# «максимум с 2023». «Впервые с августа» или «резко» без цифры изменения — заметное, не сильное.
_LONG_RUN = re.compile(r"(?:впервые|максимальн\w*|минимальн\w*|максимум\w*|минимум\w*)\s+(?:с|за)\s+"
                       r"(?:(?:19|20)\d{2}|\d+\s+(?:год|лет)|(?:несколько|много)\s+лет|десятилети)", re.I)

RATE_TOPICS = {"key_rate", "credit_market", "deposits", "bonds"}
PRICE_TOPICS = {"inflation", "fuel_oil", "metals_steel", "gold", "energy"}

LEVELS = ("weak", "moderate", "strong")
LABELS = {"weak": "слабое", "moderate": "заметное", "strong": "сильное"}
# Сила события — уточнение, а не основа ранжирования: влияние на оценку небольшое.
FACTOR = {"weak": 0.9, "moderate": 1.0, "strong": 1.1}


def _around(s: str, m: re.Match, width: int = 60) -> str:
    """Фрагмент предложения вокруг маркера — понятнее, чем одно слово."""
    start, end = max(0, m.start() - width), min(len(s), m.end() + width)
    return ("…" if start else "") + s[start:end].strip() + ("…" if end < len(s) else "")


def _f(value: str) -> float:
    return float(value.replace(",", "."))


def _level(value: float, moderate: float, strong: float) -> str:
    return "strong" if value >= strong else "moderate" if value >= moderate else "weak"


def assess(topic: str | None, sentences: list[str]) -> dict | None:
    """{'level', 'label', 'evidence'} по предложениям о теме; None — масштаб не указан."""
    if not topic or not sentences:
        return None
    best: tuple[int, str] | None = None

    def keep(level: str, evidence: str):
        nonlocal best
        rank = LEVELS.index(level)
        if best is None or rank > best[0]:
            best = (rank, evidence)

    for s in sentences:
        for m in _PP.finditer(s):
            value = _f(m.group(1)) / (100 if m.group(2).lower().startswith("б") else 1)
            keep(_level(value, 0.25, 1.0), m.group(0))
        for m in _PCT.finditer(s):
            value = _f(m.group(1))
            if topic in RATE_TOPICS:
                continue  # «на 10%» рядом со ставкой обычно про объемы, а не про ставку
            if topic in PRICE_TOPICS and _WEEKLY.search(s):
                keep(_level(value, 0.15, 0.5), m.group(0))
            elif topic == "fx":
                keep(_level(value, 1.0, 3.0), m.group(0))
            else:
                keep(_level(value, 3.0, 10.0), m.group(0))
        if topic == "fx":
            for m in _RUB.finditer(s):
                unit = m.group(2).lower()
                rub = _f(m.group(1)) / (100 if unit.startswith("коп") else 1)
                keep(_level(rub / 80 * 100, 1.0, 3.0), m.group(0))  # ориентир ~80 руб. за доллар
        for m in _TIMES.finditer(s):
            keep("strong" if _f(m.group(1)) >= 1.5 else "moderate", m.group(0))
        if (m := _LONG_RUN.search(s)):
            keep("strong", _around(s, m))
        elif (m := _RECORD.search(s)):
            # Слово-маркер без измеренного изменения — не больше чем «заметное»: число рядом («курс 81 руб.»)
            # — это уровень, а не величина изменения.
            keep("moderate", _around(s, m))
        if topic in RATE_TOPICS and (m := _HOLD.search(s)):
            keep("weak", m.group(0))
    if best is None:
        return None
    level = LEVELS[best[0]]
    return {"level": level, "label": LABELS[level], "evidence": best[1].strip()}
