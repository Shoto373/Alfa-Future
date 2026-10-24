"""Публичный контракт 1.2.0, формат разбора 1.0.0 (contracts/schemas/common.json генерируется из этих моделей).

Ключевой принцип — происхождение каждого утверждения (Claim.origin):
    fact        — подтверждено текстом новости;
    client_data — следует из данных о компании (CSV кейса);
    bank        — позиция/аналитика Альфа-Банка (тезис базы знаний);
    ai          — вывод модели или правил агента на основе перечисленных источников.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Формат разбора (Insight.schema_version): меняется, только если меняются поля разбора.
SCHEMA_VERSION = "1.0.0"
# Версия контракта API (openapi.json, заголовок X-API-Version); изменения только аддитивные.
# История и политика — docs/api-versioning.md.
API_VERSION = "1.2.0"

Role = Literal["owner", "ceo", "cfo", "accountant", "treasurer", "clevel"]
Origin = Literal["fact", "client_data", "bank", "ai"]
SourceKind = Literal["news", "bank_analytics", "client_data", "bank_product"]
# Общий знак события для компании: скорее риск, скорее возможность, и то и другое, зависит от операций, нет влияния.
Effect = Literal["neg", "pos", "mixed", "unclear", "none"]


class Strict(BaseModel):
    # В ответах API поле со значением по умолчанию всегда присутствует (model_dump) — так и в контракте:
    # сгенерированные типы интерфейса не считают его необязательным.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class InsightRequest(Strict):
    company_id: str = Field(..., min_length=1, max_length=64)
    news_id: str = Field(..., min_length=1, max_length=64)
    force_refresh: bool = False
    # Быстрый ответ: готовая карточка или разбор на правилах без LLM (~0,2 с).
    # LLM-версию клиент запрашивает следом обычным запросом: карточка на правилах ею заменяется.
    fast: bool = False
    # Другой разрез: тот же разбор глазами другой роли компании. По умолчанию — роль из членства.
    perspective: Role | None = None


class CompanyExtraShares(Strict):
    floating_debt_share: float | None = Field(None, ge=0, le=100)
    fx_revenue_share: float | None = Field(None, ge=0, le=100)
    import_share: float | None = Field(None, ge=0, le=100)


class CompanyExtraRequest(Strict):
    """Сведения, которые компания сообщает о себе: доли в процентах и свободный текст (можно из файла)."""
    shares: CompanyExtraShares = CompanyExtraShares()
    notes: str = Field("", max_length=15000)


class AISettingsRequest(Strict):
    """Готовить AI-разборы важных новостей заранее и с какой оценки важности (40–95)."""
    enabled: bool
    threshold: int = Field(85, ge=40, le=95)


class QuestionRequest(Strict):
    question: str = Field(..., min_length=2, max_length=1000)


class NewsCreateRequest(Strict):
    title: str | None = Field(None, max_length=300)
    text: str | None = Field(None, max_length=20000)
    url: str | None = Field(None, max_length=2000)


class LLMSwitchRequest(Strict):
    paused: bool


# Проверка аналитиком тезисов из распознанных PDF (SPR3-03).
class KbDraftPatch(Strict):
    topic: str | None = Field(None, max_length=40)
    sectors: list[str] | None = Field(None, max_length=8)
    metric: str | None = Field(None, max_length=300)
    value: str | None = Field(None, max_length=100)
    horizon: str | None = Field(None, max_length=20)
    quote: str | None = Field(None, max_length=1000)
    text: str | None = Field(None, max_length=1000)
    stance: Literal["forecast"] | None = None
    forecast_values: dict[str, float] | None = None


class LabelRequest(Strict):
    """Оценка аналитика для пары «новость × компания × роль» (SPR3-06)."""
    news_id: str = Field(..., min_length=1, max_length=64)
    company_id: str = Field(..., min_length=1, max_length=64)
    role: Literal["owner", "ceo", "cfo", "accountant", "treasurer", "clevel"]
    grade: int = Field(..., ge=0, le=3)
    reason: str = Field("", max_length=500)


class DomainConfigTexts(Strict):
    """YAML-тексты доменной конфигурации (SPR4-00): темы, отрасли, слова-маркеры."""
    topics: str = Field(..., min_length=1, max_length=300_000)
    sectors: str = Field(..., min_length=1, max_length=300_000)
    language: str = Field(..., min_length=1, max_length=100_000)


class DomainConfigPublish(DomainConfigTexts):
    note: str = Field("", max_length=300)


class DomainConfigPreviewRequest(DomainConfigTexts):
    company_id: str = Field(..., min_length=1, max_length=64)
    role: Literal["owner", "ceo", "cfo", "accountant", "treasurer", "clevel"] = "cfo"


class ScenarioRequest(Strict):
    """Сценарий «что если» (SPR4-02): шок и необязательные собственные значения компании вместо оценок."""
    company_id: str = Field(..., min_length=1, max_length=64)
    scenario: Literal["key_rate", "fx", "commodity"]
    shock: float = Field(..., ge=-60, le=60)  # п.п. для ставки, % для курса (плюс — рубль слабее) и цены сырья
    debt: float | None = Field(None, ge=0, le=1e14)
    floating_share: float | None = Field(None, ge=0, le=1)
    fx_revenue_share: float | None = Field(None, ge=0, le=1)
    import_share: float | None = Field(None, ge=0, le=1)
    exposure: float | None = Field(None, ge=0, le=1)


CLOCK = r"^([01]\d|2[0-3]):[0-5]\d$"


class NotificationChannels(Strict):
    inapp: bool = True
    email: bool = True
    telegram: bool = False


class NotificationSettings(Strict):
    """Подписка на компанию (SPR4-04). Поля необязательны в запросе: меняются только переданные."""
    digest: bool | None = None
    digest_time: str | None = Field(None, pattern=CLOCK)
    timezone: str | None = Field(None, min_length=3, max_length=64)
    threshold: int | None = Field(None, ge=50, le=100)
    topics: list[str] | None = Field(None, max_length=40)
    counterparties: bool | None = None
    quiet_from: str | None = Field(None, pattern=CLOCK)
    quiet_to: str | None = Field(None, pattern=CLOCK)
    alerts_per_day: int | None = Field(None, ge=0, le=10)
    channels: NotificationChannels | None = None


class NotificationReadRequest(Strict):
    company_id: str = Field(..., min_length=1, max_length=64)
    ids: list[int] | None = Field(None, max_length=200)  # пусто — прочитать все


class KbApproveRequest(Strict):
    supersedes: str | None = Field(None, max_length=64)


class KbRejectRequest(Strict):
    reason: str = Field(..., min_length=1, max_length=300)


class KbDocumentMeta(Strict):
    title: str | None = Field(None, max_length=300)
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")


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
    # Почему разбор на правилах: AI выключен банком, не подключен, лимит бюджета, модель не ответила, не прошли проверки.
    fallback_reason: Literal["paused", "disabled", "budget", "company_budget", "unavailable", "checks"] | None = None
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
