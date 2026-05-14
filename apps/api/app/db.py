"""SQLAlchemy 2 async session + models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from apps.api.app.config import get_settings


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    country: Mapped[str] = mapped_column(String(2), index=True)
    primary_identifier_type: Mapped[str] = mapped_column(String(64))
    primary_identifier_value: Mapped[str] = mapped_column(String(128), index=True)
    all_identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    registry_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    filings: Mapped[list["FinancialFiling"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="company", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_companies_country_identifier", "country", "primary_identifier_value", unique=True),
    )


class FinancialFiling(Base):
    __tablename__ = "financial_filings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(64))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    structured_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    document_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="filings")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(16))
    recommended_limit_eur: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(String)
    key_signals: Mapped[list[str]] = mapped_column(JSONB, default=list)
    red_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    ratios: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="assessments")


class SearchQuery(Base):
    __tablename__ = "search_queries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    query: Mapped[str] = mapped_column(String(512))
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(64))  # "risk_analysis", "financials_refresh"
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued|running|done|error
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, echo=False, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncSession:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


async def init_db_if_needed() -> None:
    """Create tables on startup if they don't exist (dev convenience).

    Production should use Alembic migrations — see apps/api/alembic/.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
