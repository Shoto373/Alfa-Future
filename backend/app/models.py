"""SQLAlchemy ORM entities. Pydantic API contracts live in app.schemas.

JSONB stores structured documents; relational columns enforce identities,
references, ordering and concurrent accounting.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, LargeBinary,
                        Numeric, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Размерность векторов embedding-модели (paraphrase-multilingual-MiniLM-L12-v2).
VECTOR_DIM = 384


class Base(DeclarativeBase):
    pass


class Payload:
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)


class Company(Base, Payload):
    __tablename__ = "companies"
    company_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sector: Mapped[str] = mapped_column(Text)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric)
    __table_args__ = (Index("companies_sector_idx", "sector"),)


class BankDocument(Base, Payload):
    __tablename__ = "bank_documents"
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)


class BankThesis(Base, Payload):
    __tablename__ = "bank_theses"
    thesis_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("bank_documents.doc_id"))
    page: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("page > 0", name="bank_theses_page_check"),)


class KbUpload(Base, Payload):
    """PDF аналитики банка, загруженный на распознавание (SPR3-03): файл, статус и тексты страниц в payload."""
    __tablename__ = "kb_uploads"
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text, unique=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("status IN ('queued', 'processing', 'ready', 'failed')", name="kb_uploads_status_check"),)


class ThesisDraft(Base, Payload):
    """Черновик тезиса из распознанного PDF: в базу знаний попадает только после проверки аналитиком."""
    __tablename__ = "thesis_drafts"
    draft_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("kb_uploads.doc_id", ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    thesis_id: Mapped[str | None] = mapped_column(Text, nullable=True)  # опубликованный тезис
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("status IN ('draft', 'approved', 'rejected')", name="thesis_drafts_status_check"),
                      Index("thesis_drafts_doc_idx", "doc_id", "page"))


class RankingLabel(Base):
    """Экспертная оценка релевантности пары «новость × компания × роль» (SPR3-06): 0–3 и причина."""
    __tablename__ = "ranking_labels"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    news_id: Mapped[str] = mapped_column(Text)
    company_id: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    grade: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, server_default="")
    annotator: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("news_id", "company_id", "role", "annotator", name="ranking_labels_pair_uq"),
                      CheckConstraint("grade BETWEEN 0 AND 3", name="ranking_labels_grade_check"))


class DomainConfigVersion(Base, Payload):
    """Опубликованная версия доменной конфигурации (SPR4-00): YAML-тексты тем, отраслей и слов-маркеров."""
    __tablename__ = "domain_config_versions"
    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default="published")
    created_by: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, server_default="")
    signature: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("status IN ('published', 'archived')", name="domain_config_versions_status_check"),)


class CompanyEdge(Base):
    """Ребро графа контрагентов (SPR4-01): платеж «плательщик → получатель» или возможная связь через физлиц."""
    __tablename__ = "company_edges"
    src: Mapped[str] = mapped_column(Text, primary_key=True)
    dst: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # payment | person
    share_out: Mapped[float] = mapped_column(Numeric)  # доля в исходящих платежах src (для person — вес связи)
    share_in: Mapped[float | None] = mapped_column(Numeric, nullable=True)  # доля во входящих платежах dst
    amount: Mapped[float] = mapped_column(Numeric, server_default="0")
    count: Mapped[int] = mapped_column(Integer, server_default="0")
    __table_args__ = (Index("company_edges_dst_idx", "dst"),)


class CounterpartyAlert(Base, Payload):
    """Событие у контрагента компании (SPR4-01): новость о нем, цепочка до компании и сила события."""
    __tablename__ = "counterparty_alerts"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    company_id: Mapped[str] = mapped_column(Text)
    news_id: Mapped[str] = mapped_column(Text)
    counterparty_id: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("company_id", "news_id", "counterparty_id", name="counterparty_alerts_uq"),
                      Index("counterparty_alerts_company_idx", "company_id", "created_at"))


class Subscription(Base, Payload):
    """Подписка пользователя на компанию (SPR4-04): темы, порог, контрагенты, тихие часы, каналы, сводка."""
    __tablename__ = "subscriptions"
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(Text, primary_key=True)
    unsubscribe_token: Mapped[str] = mapped_column(Text, unique=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Delivery(Base, Payload):
    """Журнал доставки сводок и алертов (SPR4-04): канал, статус, попытки; ключ не дает отправить дважды."""
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text)
    company_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)      # digest | alert
    channel: Mapped[str] = mapped_column(Text)   # inapp | email | telegram
    key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")  # queued | sent | failed | skipped
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("key", "channel", name="deliveries_key_channel_uq"),
                      Index("deliveries_user_idx", "user_id", "company_id", "created_at"),
                      CheckConstraint("status IN ('queued', 'sent', 'failed', 'skipped')", name="deliveries_status_check"))


class BankProduct(Base, Payload):
    __tablename__ = "bank_products"
    product_id: Mapped[str] = mapped_column(Text, primary_key=True)


class News(Base, Payload):
    __tablename__ = "news"
    news_id: Mapped[str] = mapped_column(Text, primary_key=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(Text)
    # Время последнего изменения записи: API подгружает только изменившиеся новости (дельта), а не весь набор.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Сюжет (SPR3-02): id самой ранней новости сюжета; хранится в базе, повторный сбор его не пересчитывает.
    story_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("news_published_idx", published_at.desc()), Index("news_updated_idx", "updated_at"),
                      Index("news_story_idx", "story_id"))


class NewsEntity(Base):
    """Организация, упомянутая в новости (SPR3-02): company_id — если она есть в профилях."""
    __tablename__ = "news_entities"
    news_id: Mapped[str] = mapped_column(ForeignKey("news.news_id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("news_entities_company_idx", "company_id"),)


class Insight(Base, Payload):
    __tablename__ = "insights"
    insight_id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"))
    news_id: Mapped[str] = mapped_column(ForeignKey("news.news_id"))
    role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cache_version: Mapped[str] = mapped_column(Text)
    # Лента ищет готовые карточки пачкой: компания, роль и версия кэша фиксированы, news_id — список.
    __table_args__ = (Index("insights_lookup_idx", company_id, role, cache_version, news_id, created_at.desc()),
                      Index("insights_news_idx", news_id))


class Feedback(Base, Payload, Timestamped):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    insight_id: Mapped[str] = mapped_column(ForeignKey("insights.insight_id"))
    __table_args__ = (Index("feedback_insight_idx", "insight_id"),)


class Event(Base, Payload, Timestamped):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("events_kind_idx", "kind"),)


class ToolAudit(Base, Payload, Timestamped):
    __tablename__ = "tool_audit"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    request_id: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("tool_audit_request_idx", "request_id"),)


class Answer(Base, Payload, Timestamped):
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    insight_id: Mapped[str] = mapped_column(ForeignKey("insights.insight_id"))
    __table_args__ = (Index("answers_insight_idx", "insight_id"),)


class AuthUser(Base):
    """Пользователь. Email хранится в нижнем регистре и уникален; пароль — scrypt с солью и параметрами в записи."""
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, unique=True)
    pw_salt: Mapped[str] = mapped_column(Text)
    pw_hash: Mapped[str] = mapped_column(Text)
    pw_params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthMembership(Base):
    """Членство в компании. user_id пуст у приглашения — привязывается при регистрации с тем же email."""
    __tablename__ = "memberships"
    member_id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default="false")
    founder: Mapped[bool] = mapped_column(Boolean, server_default="false")
    invited_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("company_id", "email", name="memberships_company_email_uq"),
                      Index("memberships_user_idx", "user_id"))


class AuthSession(Base):
    """Сессия: только SHA-256 токена; истекает через SESSION_TTL_HOURS со скользящим продлением."""
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("sessions_user_idx", "user_id"), Index("sessions_expires_idx", "expires_at"))


class LoginFailure(Base):
    """Попытка входа (запись до проверки пароля, при успехе удаляется): блокировка по паре email + адрес
    и общий потолок на email — общие для всех воркеров."""
    __tablename__ = "login_failures"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    ip: Mapped[str] = mapped_column(Text, server_default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("login_failures_email_at_idx", "email", "at"),)


class LLMUsage(Base):
    __tablename__ = "llm_usage"
    day: Mapped[date] = mapped_column(primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    calls: Mapped[int] = mapped_column(Integer, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, server_default="0")
    # Резерв идущих вызовов (оценка по max_tokens и цене модели) и отказы по бюджету — app/llm_usage.py.
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    rejected: Mapped[int] = mapped_column(Integer, server_default="0")


class LLMUsageModel(Base):
    """Дневной учет по модели: фактическая цена за 1000 токенов для сверки с оценкой config.LLM_PRICES."""
    __tablename__ = "llm_usage_models"
    day: Mapped[date] = mapped_column(ForeignKey("llm_usage.day"), primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    calls: Mapped[int] = mapped_column(Integer, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, server_default="0")


class LLMUsageCompany(Base):
    """Дневной учет по компании-клиенту: одна компания не может израсходовать общий бюджет (LLM_COMPANY_SHARE)."""
    __tablename__ = "llm_usage_companies"
    day: Mapped[date] = mapped_column(ForeignKey("llm_usage.day"), primary_key=True)
    company_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    calls: Mapped[int] = mapped_column(Integer, server_default="0")
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    rejected: Mapped[int] = mapped_column(Integer, server_default="0")


class LLMReservation(Base):
    """Резерв одного идущего вызова LLM: снимается при списании факта, ошибке или через 10 минут."""
    __tablename__ = "llm_reservations"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(ForeignKey("llm_usage.day"))
    company_id: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(BigInteger)
    cost: Mapped[Decimal] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("llm_reservations_created_idx", "created_at"),)


class VectorItem(Base, Payload):
    """Векторное хранилище (pgvector): смысловые векторы и метаданные для поиска.

    collection: cache — любой текст, который уже считала модель (ключ — хэш текста);
    news — заголовки новостей; thesis — тезисы аналитики банка. text_hash показывает,
    что вектор посчитан для текущего текста; payload — поля для фильтров поиска.
    """
    __tablename__ = "vector_items"
    collection: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    text_hash: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(VECTOR_DIM))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("vector_items_embedding_idx", embedding, postgresql_using="hnsw",
                            postgresql_ops={"embedding": "vector_cosine_ops"}),)


class Job(Base):
    """Задача фонового воркера (app/worker): очередь в PostgreSQL без отдельного брокера.

    Выборка — SELECT … FOR UPDATE SKIP LOCKED: два воркера не берут одну задачу. Упавшая задача
    повторяется с экспоненциальной задержкой; после max_attempts — status=dead (dead-letter).
    dedupe_key не дает поставить в очередь одну и ту же плановую задачу дважды.
    """
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'done', 'dead')", name="jobs_status_check"),
        Index("jobs_ready_idx", "run_at", postgresql_where="status = 'queued'"),
    )
