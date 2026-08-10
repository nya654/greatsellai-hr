"""Platform-wide system announcements and per-user read state.

Revision ID: 20260806_0064
Revises: 20260806_0063
Create Date: 2026-08-10

Adds the global ``announcements`` table (title + plain-text body, manually
published/unpublished) and the per-user ``announcement_reads`` table so the
topbar bell can show a persistent unread count without one user's
acknowledgment hiding a notice from anyone else.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0064"
down_revision: Union[str, Sequence[str], None] = "20260806_0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_announcements_published_created",
        "announcements",
        ["is_published", "published_at", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_announcements_is_published",
        "announcements",
        ["is_published"],
        unique=False,
    )
    op.create_index(
        "ix_announcements_created_by_user_id",
        "announcements",
        ["created_by_user_id"],
        unique=False,
    )

    op.create_table(
        "announcement_reads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("announcement_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("announcement_id", "user_id", name="uq_announcement_read_user"),
    )
    op.create_index(
        "ix_announcement_reads_announcement_id",
        "announcement_reads",
        ["announcement_id"],
        unique=False,
    )
    op.create_index(
        "ix_announcement_reads_user_id",
        "announcement_reads",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_announcement_reads_user_created",
        "announcement_reads",
        ["user_id", "read_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_announcement_reads_user_created", table_name="announcement_reads")
    op.drop_index("ix_announcement_reads_user_id", table_name="announcement_reads")
    op.drop_index("ix_announcement_reads_announcement_id", table_name="announcement_reads")
    op.drop_table("announcement_reads")
    op.drop_index("ix_announcements_created_by_user_id", table_name="announcements")
    op.drop_index("ix_announcements_is_published", table_name="announcements")
    op.drop_index("ix_announcements_published_created", table_name="announcements")
    op.drop_table("announcements")
