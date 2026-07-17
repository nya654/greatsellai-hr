"""Tie scores to immutable facts and preserve AI/raw scoring data.

Revision ID: 20260716_0003
Revises: 20260716_0002
Create Date: 2026-07-16 14:40:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0003"
down_revision: Union[str, Sequence[str], None] = "20260716_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode keeps this revision valid on SQLite (used for local development)
    # as well as PostgreSQL (the production target).
    with op.batch_alter_table("score_template_dimensions") as batch_op:
        batch_op.add_column(
            sa.Column("max_raw_score", sa.Integer(), server_default="100", nullable=False)
        )
    with op.batch_alter_table("resume_scores") as batch_op:
        batch_op.add_column(
            sa.Column("fact_snapshot_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(sa.Column("ai_total_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("analysis", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "fk_resume_scores_fact_snapshot_id",
            "resume_fact_snapshots",
            ["fact_snapshot_id"],
            ["id"],
        )
        batch_op.create_index("ix_resume_scores_fact_snapshot_id", ["fact_snapshot_id"])


def downgrade() -> None:
    with op.batch_alter_table("resume_scores") as batch_op:
        batch_op.drop_index("ix_resume_scores_fact_snapshot_id")
        batch_op.drop_constraint(
            "fk_resume_scores_fact_snapshot_id",
            type_="foreignkey",
        )
        batch_op.drop_column("analysis")
        batch_op.drop_column("ai_total_score")
        batch_op.drop_column("fact_snapshot_id")
    with op.batch_alter_table("score_template_dimensions") as batch_op:
        batch_op.drop_column("max_raw_score")
