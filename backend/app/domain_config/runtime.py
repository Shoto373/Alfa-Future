"""Действующие словари доменных знаний (SPR4-00) — единые объекты для всего процесса.

app.news.taxonomy, app.companies.sectors и app.agent.composer реэкспортируют эти объекты, поэтому код,
который делает `from app.news.taxonomy import TOPICS`, видит опубликованную аналитиком версию:
apply() обновляет словари на месте (сначала новые ключи, потом удаление лишних — без пустого окна).
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Sensitivity:
    sign: int
    why: str


TOPICS: dict[str, dict] = {}
TOPIC_MEANINGS: dict[str, list[str]] = {}
SECTOR_STEMS: dict[str, list[str]] = {}
COUNTRY_STEMS: dict[str, list[str]] = {}
DIRECTION_STEMS: dict[str, list[str]] = {}
RUBLE_DIRECTION: dict[str, list[str]] = {}
FOREIGN_CURRENCY: list[str] = []
FOREIGN_DIRECTION: dict[str, list[str]] = {}
SANCTIONS_DIRECTION: dict[str, list[str]] = {}
ACTORS: list[str] = []
FOREIGN_CENTRAL_BANKS: list[str] = []
CENTRAL_BANK_WORDS: list[str] = []
BANK_OF_RUSSIA: list[str] = []
SECTOR_NAMES: dict[str, str] = {}
OKVED_PREFIXES: dict[str, str] = {}
SECTOR_SENSITIVITY: dict[str, dict[str, Sensitivity]] = {}
DIRECTION_VALUE: dict[str, dict[str, float]] = {}
TOPIC_EFFECT: dict[str, tuple[str, str]] = {}
TOPIC_EFFECT_DOWN: dict[str, tuple[str, str]] = {}
ACTIONS: dict[str, dict[str, list[tuple[str, str | None]]]] = {}
QUESTIONS: dict[str, str] = {}

_state = {"signature": "", "version": None}
_on_change: list[Callable[[], None]] = []


def signature() -> str:
    """Подпись действующей конфигурации: входит в ключи кэша ленты и разборов и в переклассификацию новостей."""
    return _state["signature"]


def version() -> int | None:
    """Номер опубликованной версии из базы; None — исходные файлы из репозитория."""
    return _state["version"]


def on_change(callback: Callable[[], None]) -> None:
    """Сброс производных кэшей (признаки профилей, векторы тем) при смене конфигурации."""
    _on_change.append(callback)


def digest(docs: dict) -> str:
    return hashlib.sha256(json.dumps(docs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _replace(target: dict, new: dict) -> None:
    target.update(new)
    for key in [k for k in target if k not in new]:
        del target[key]


def _actions(lib: dict) -> dict:
    return {role: [(a["text"], a.get("needs")) for a in items] for role, items in lib.items()}


def build(docs: dict) -> dict:
    """Словари времени выполнения из проверенных документов (dict после model_dump)."""
    topics, sectors, lang = docs["topics"]["topics"], docs["sectors"]["sectors"], docs["language"]
    return {
        "TOPICS": {k: {"name": t["name"], "importance": t["importance"], "stems": list(t["stems"])} for k, t in topics.items()},
        "TOPIC_MEANINGS": {k: list(t["meanings"]) for k, t in topics.items()},
        "SECTOR_STEMS": {k: list(s["stems"]) for k, s in sectors.items() if s["stems"]},
        "COUNTRY_STEMS": lang["countries"], "DIRECTION_STEMS": lang["direction_stems"],
        "RUBLE_DIRECTION": lang["ruble_direction"], "FOREIGN_DIRECTION": lang["foreign_direction"],
        "SANCTIONS_DIRECTION": lang["sanctions_direction"],
        "SECTOR_NAMES": {k: s["name"] for k, s in sectors.items()},
        "OKVED_PREFIXES": {p: k for k, s in sectors.items() for p in s["okved"]},
        "SECTOR_SENSITIVITY": {t: {k: Sensitivity(s["sensitivity"][t]["sign"], s["sensitivity"][t]["why"])
                                   for k, s in sectors.items() if t in s["sensitivity"]}
                               for t in docs["sectors"]["topic_order"]},
        "DIRECTION_VALUE": {k: dict(t["direction_value"]) for k, t in topics.items() if t.get("direction_value")},
        "TOPIC_EFFECT": {k: (t["effect"]["risk"], t["effect"]["opportunity"]) for k, t in topics.items() if t.get("effect")},
        "TOPIC_EFFECT_DOWN": {k: (t["effect_down"]["risk"], t["effect_down"]["opportunity"])
                              for k, t in topics.items() if t.get("effect_down")},
        "ACTIONS": {**{k: _actions(t["actions"]) for k, t in topics.items() if t.get("actions")},
                    "default": _actions(docs["topics"]["default_actions"])},
        "QUESTIONS": {k: t["question"] for k, t in topics.items() if t.get("question")},
        "FOREIGN_CURRENCY": list(lang["foreign_currency"]), "ACTORS": list(lang["actors"]),
        "FOREIGN_CENTRAL_BANKS": list(lang["foreign_central_banks"]), "CENTRAL_BANK_WORDS": list(lang["central_bank_words"]),
        "BANK_OF_RUSSIA": list(lang["bank_of_russia"]),
    }


def apply(docs: dict, version_id: int | None = None) -> str:
    """Сделать документы действующими во всем процессе. Возвращает подпись."""
    built = build(docs)
    for name, value in built.items():
        target = globals()[name]
        if isinstance(target, list):
            target[:] = value
        else:
            _replace(target, value)
    _state.update(signature=digest(docs), version=version_id)
    for callback in _on_change:
        callback()
    return _state["signature"]
