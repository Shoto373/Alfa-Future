"""SQLAlchemy ORM entities. Pydantic API contracts live in app.schemas.

JSONB stores structured documents; relational columns enforce identities,
references, ordering and concurrent accounting.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, Numeric, Text, func
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


class BankProduct(Base, Payload):
    __tablename__ = "bank_products"
    product_id: Mapped[str] = mapped_column(Text, primary_key=True)


class News(Base, Payload):
    __tablename__ = "news"
    news_id: Mapped[str] = mapped_column(Text, primary_key=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("news_published_idx", published_at.desc()),)


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


class LLMReservation(Base):
    """Резерв одного идущего вызова LLM: снимается при списании факта, ошибке или через 10 минут."""
    __tablename__ = "llm_reservations"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(ForeignKey("llm_usage.day"))
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
