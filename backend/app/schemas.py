"""Публичный контракт 1.0.0 (contracts/schemas/common.json генерируется из этих моделей).

Ключевой принцип — происхождение каждого утверждения (Claim.origin):
    fact        — подтверждено текстом новости;
    client_data — следует из данных о компании (CSV кейса);
    bank        — позиция/аналитика Альфа-Банка (тезис базы знаний);
    ai          — вывод модели или правил агента на основе перечисленных источников.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"

Role = Literal["owner", "ceo", "cfo", "accountant", "treasurer", "clevel"]
Origin = Literal["fact", "client_data", "bank", "ai"]
SourceKind = Literal["news", "bank_analytics", "client_data", "bank_product"]
# Общий знак события для компании: скорее риск, скорее возможность, и то и другое, зависит от операций, нет влияния.
Effect = Literal["neg", "pos", "mixed", "unclear", "none"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InsightRequest(Strict):
    company_id: str = Field(..., min_length=1, max_length=64)
    news_id: str = Field(..., min_length=1, max_length=64)
    force_refresh: bool = False
    # Быстрый ответ: готовая карточка или разбор на правилах без LLM (~0,2 с).
    # LLM-версию клиент запрашивает следом обычным запросом: карточка на правилах ею заменяется.
    fast: bool = False


class QuestionRequest(Strict):
    question: str = Field(..., min_length=2, max_length=1000)


class NewsCreateRequest(Strict):
    title: str | None = Field(None, max_length=300)
    text: str | None = Field(None, max_length=20000)
    url: str | None = Field(None, max_length=2000)


class FeedbackRequest(Strict):
    insight_id: str = Field(..., min_length=1, max_length=64)
    rating: Literal[1, -1]
    section: str | None = Field(None, max_length=40)
    comment: str | None = Field(None, max_length=1000)


class Claim(Strict):
    text: str
    origin: Origin
    source_ids: list[str]
    features: list[str] = []


class Source(Strict):
    source_id: str
    kind: SourceKind
    title: str
    url: str | None = None
    doc_id: str | None = None
    page: int | None = None
    date: str | None = None
    excerpt: str | None = None


class Feature(Strict):
    name: str
    label: str
    value: str


class RelevanceReason(Strict):
    kind: str
    feature: str
    origin: str
    weight: float
    text: str
    topic: str | None = None


class Relevance(Strict):
    score: float
    reasons: list[RelevanceReason]


class WhatHappened(Strict):
    summary: str
    facts: list[Claim]
    actors: list[str]
    dates: list[str]
    assumptions: list[Claim]


class BankView(Strict):
    available: bool
    summary: str | None
    theses: list[Claim]
    conflicts: list[str]


class ProductOffer(Strict):
    product_id: str
    title: str
    text: str
    reason: str


class QualityCheck(Strict):
    name: str
    passed: bool
    detail: str


class Quality(Strict):
    passed: bool
    attempts: int
    checks: list[QualityCheck]


class TraceStep(Strict):
    step: int
    stage: Literal["plan", "tool", "compose", "check", "adapt", "finalize"]
    name: str
    detail: str
    status: Literal["ok", "warning", "error", "skipped"]
    duration_ms: float
    output: dict | None = None


class Insight(Strict):
    schema_version: Literal["1.0.0"]
    insight_id: str
    request_id: str
    company_id: str
    role: Role
    news_id: str
    created_at: str
    mode: Literal["llm", "rules"]
    model: str | None
    # Почему разбор на правилах: модель не подключена, лимит бюджета, модель не ответила, выводы не прошли проверки.
    fallback_reason: Literal["disabled", "budget", "unavailable", "checks"] | None = None
    title: str
    headline: str
    effect: Effect | None = None  # None — карточки, созданные до появления поля
    what_happened: WhatHappened
    why_important: list[Claim]
    risks: list[Claim]
    opportunities: list[Claim]
    actions: list[Claim]
    questions: list[str]
    bank_view: BankView
    products: list[ProductOffer]
    features_used: list[Feature]
    relevance: Relevance
    sources: list[Source]
    quality: Quality
    trace: list[TraceStep]
    disclaimer: str


class Answer(Strict):
    insight_id: str
    question: str
    answer: str
    claims: list[Claim]
    sources: list[Source]
    mode: Literal["llm", "rules"]
    refused: bool = False


class ErrorDetail(Strict):
    code: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    retryable: bool


class ErrorResponse(Strict):
    error: ErrorDetail
