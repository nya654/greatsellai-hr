"""Add immutable-summary references and manual summary versions.

Revision ID: 20260716_0004
Revises: 20260716_0003
Create Date: 2026-07-16 15:05:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0004"
down_revision: Union[str, Sequence[str], None] = "20260716_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("resume_summaries") as batch_op:
        batch_op.add_column(
            sa.Column("fact_snapshot_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("source", sa.String(length=32), server_default="ai", nullable=False)
        )
        batch_op.add_column(
            sa.Column("supersedes_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False)
        )
        batch_op.create_foreign_key(
            "fk_resume_summaries_fact_snapshot_id",
            "resume_fact_snapshots",
            ["fact_snapshot_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_resume_summaries_supersedes_id",
            "resume_summaries",
            ["supersedes_id"],
            ["id"],
        )
        batch_op.create_index("ix_resume_summaries_fact_snapshot_id", ["fact_snapshot_id"])
        batch_op.create_index("ix_resume_summaries_is_current", ["is_current"])
    op.create_index(
        "uq_current_resume_summary",
        "resume_summaries",
        ["resume_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_current_resume_summary", table_name="resume_summaries")
    with op.batch_alter_table("resume_summaries") as batch_op:
        batch_op.drop_index("ix_resume_summaries_is_current")
        batch_op.drop_index("ix_resume_summaries_fact_snapshot_id")
        batch_op.drop_constraint(
            "fk_resume_summaries_supersedes_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_resume_summaries_fact_snapshot_id",
            type_="foreignkey",
        )
        batch_op.drop_column("is_current")
        batch_op.drop_column("supersedes_id")
        batch_op.drop_column("source")
        batch_op.drop_column("fact_snapshot_id")
