"""SQLAlchemy ORM entities. Pydantic API contracts live in app.schemas.

JSONB stores structured documents; relational columns enforce identities,
references, ordering and concurrent accounting.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    __table_args__ = (Index("insights_cache_idx", company_id, role, news_id, created_at.desc()),)


class Feedback(Base, Payload, Timestamped):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    insight_id: Mapped[str] = mapped_column(ForeignKey("insights.insight_id"))


class Event(Base, Payload, Timestamped):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)


class ToolAudit(Base, Payload, Timestamped):
    __tablename__ = "tool_audit"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    request_id: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("tool_audit_request_idx", "request_id"),)


class Answer(Base, Payload, Timestamped):
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    insight_id: Mapped[str] = mapped_column(ForeignKey("insights.insight_id"))


class LLMUsage(Base):
    __tablename__ = "llm_usage"
    day: Mapped[date] = mapped_column(primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    calls: Mapped[int] = mapped_column(Integer, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, server_default="0")
