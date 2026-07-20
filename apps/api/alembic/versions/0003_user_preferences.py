"""user preferences jsonb column

Revision ID: 0003_user_preferences
Revises: 0002_users_subscriptions
Create Date: 2026-06-21 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_user_preferences"
down_revision = "0002_users_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
