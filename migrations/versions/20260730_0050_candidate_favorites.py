"""Add private, workspace-scoped candidate favorites.

Revision ID: 20260730_0050
Revises: 20260729_0049
Create Date: 2026-07-30 10:30:00

Only a candidate bookmark association is stored.  Resume versions, AI output,
scores, and original files remain in their existing tables.  The candidate
foreign key cascades on physical erasure; normal reads additionally join the
live candidate root so a soft-deleted candidate is never shown as a favorite.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0050"
down_revision: Union[str, Sequence[str], None] = "20260729_0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_favorites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "candidate_id",
            name="uq_candidate_favorite_owner",
        ),
    )
    op.create_index(
        "ix_candidate_favorites_organization_id",
        "candidate_favorites",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_favorites_user_id",
        "candidate_favorites",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_favorites_candidate_id",
        "candidate_favorites",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_favorites_organization_user_created",
        "candidate_favorites",
        ["organization_id", "user_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_favorites_organization_user_created",
        table_name="candidate_favorites",
    )
    op.drop_table("candidate_favorites")
