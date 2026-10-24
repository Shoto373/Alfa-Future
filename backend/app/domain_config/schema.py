"""Схема конфигурации доменных знаний (SPR4-00): темы, отрасли и слова-маркеры классификатора.

Конвенция знаков одна для всех тем: direction_value.up > 0 означает «темы стало больше» (ставка выше,
рубль слабее, кредит доступнее — смысл «up» записан словами в up_means). Чувствительность отрасли sign:
+1 — отрасль выигрывает при росте темы, -1 — проигрывает, 0 — неоднозначно. Эффект события для отрасли =
sign × direction_value[направление]: отрицательный — риск, положительный — возможность.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["up", "down", "hold"]
ROLES = ("owner", "ceo", "cfo", "accountant", "treasurer", "clevel")
Expectation = Literal["risk", "opportunity", "neutral"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(Strict):
    text: str = Field(..., min_length=10, max_length=400)
    needs: str | None = None  # продукт компании, без которого действие не предлагается (loans, leasing, deposits…)


class Effect(Strict):
    risk: str = Field(..., min_length=5)
    opportunity: str = Field(..., min_length=5)


class Topic(Strict):
    name: str = Field(..., min_length=2)
    importance: float = Field(..., ge=0, le=2)
    stems: list[str] = Field(..., min_length=1)
    meanings: list[str] = Field(default_factory=list)
    up_means: str | None = None
    direction_value: dict[Direction, float] | None = None
    effect: Effect | None = None
    effect_down: Effect | None = None
    actions: dict[str, list[Action]] = Field(default_factory=dict)
    question: str | None = None


class Sensitivity(Strict):
    sign: Literal[-1, 0, 1]
    why: str = Field(..., min_length=5)


class Sector(Strict):
    name: str = Field(..., min_length=2)
    okved: list[str] = Field(default_factory=list)
    stems: list[str] = Field(default_factory=list)
    sensitivity: dict[str, Sensitivity] = Field(default_factory=dict)


class ControlCase(Strict):
    """Эталон знака: «рост ставки — риск для стройки». Перевернутый знак в конфигурации ломает эталон."""
    topic: str
    sector: str
    direction: Direction
    expect: Expectation
    why: str = ""


class TopicsDoc(Strict):
    topics: dict[str, Topic]
    default_actions: dict[str, list[Action]]


class SectorsDoc(Strict):
    topic_order: list[str]
    sectors: dict[str, Sector]
    control_cases: list[ControlCase] = Field(default_factory=list)


class LanguageDoc(Strict):
    countries: dict[str, list[str]]
    direction_stems: dict[Literal["up", "down", "hold"], list[str]]
    ruble_direction: dict[Literal["up", "down"], list[str]]
    foreign_currency: list[str]
    foreign_direction: dict[Literal["up", "down"], list[str]]
    sanctions_direction: dict[Literal["up", "down"], list[str]]
    actors: list[str]


DOCS = {"topics": TopicsDoc, "sectors": SectorsDoc, "language": LanguageDoc}
