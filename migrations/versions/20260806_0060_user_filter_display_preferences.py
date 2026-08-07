"""Add per-user filter result column preferences.

Revision ID: 20260806_0060
Revises: 20260806_0059
Create Date: 2026-08-06 17:00:00

One lazily-created row per (organization, user) stores which columns the
user chose to show in the filter results pane. Absence means the results
pane falls back to auto-derived columns. Uniqueness is scoped per user AND
workspace so a user who belongs to several workspaces can keep different
selections in each.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0060"
down_revision: Union[str, Sequence[str], None] = "20260806_0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_filter_display_preferences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("display_field_keys", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"]),
        sa.UniqueConstraint(
            "user_id",
            "organization_id",
            name="uq_user_filter_display_preferences_user_org",
        ),
    )
    op.create_index(
        "ix_user_filter_display_preferences_organization_id",
        "user_filter_display_preferences",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_filter_display_preferences_organization_id",
        table_name="user_filter_display_preferences",
    )
    op.drop_table("user_filter_display_preferences")
