"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("normalized_name", sa.String(512), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("primary_identifier_type", sa.String(64), nullable=False),
        sa.Column("primary_identifier_value", sa.String(128), nullable=False),
        sa.Column("all_identifiers", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("registry_data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"])
    op.create_index("ix_companies_country", "companies", ["country"])
    op.create_index("ix_companies_primary_identifier_value", "companies", ["primary_identifier_value"])
    op.create_index(
        "ix_companies_country_identifier", "companies", ["country", "primary_identifier_value"], unique=True
    )

    op.create_table(
        "financial_filings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("structured_data", postgresql.JSONB, nullable=True),
        sa.Column("document_url", sa.String(1024), nullable=True),
        sa.Column("document_format", sa.String(32), nullable=True),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_financial_filings_year", "financial_filings", ["year"])

    op.create_table(
        "risk_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("recommendation", sa.String(16), nullable=False),
        sa.Column("recommended_limit_eur", sa.Float, nullable=False),
        sa.Column("reasoning", sa.String, nullable=False),
        sa.Column("key_signals", postgresql.JSONB, server_default="[]"),
        sa.Column("red_flags", postgresql.JSONB, server_default="[]"),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("ratios", postgresql.JSONB, server_default="[]"),
        sa.Column("model_used", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "search_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("query", sa.String(512), nullable=False),
        sa.Column("result_count", sa.Integer, server_default="0"),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="queued"),
        sa.Column("payload", postgresql.JSONB, server_default="{}"),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ingestion_jobs")
    op.drop_table("search_queries")
    op.drop_table("risk_assessments")
    op.drop_table("financial_filings")
    op.drop_index("ix_companies_country_identifier", table_name="companies")
    op.drop_index("ix_companies_primary_identifier_value", table_name="companies")
    op.drop_index("ix_companies_country", table_name="companies")
    op.drop_index("ix_companies_normalized_name", table_name="companies")
    op.drop_table("companies")
