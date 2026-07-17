"""Add durable all-resume JD match batches.

Revision ID: 20260717_0009
Revises: 20260716_0008
Create Date: 2026-07-17 10:20:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0009"
down_revision: Union[str, Sequence[str], None] = "20260716_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_match_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_version_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_match_batches_job_version_id", "job_match_batches", ["job_version_id"])
    op.create_index("ix_job_match_batches_status", "job_match_batches", ["status"])
    op.create_index("ix_job_match_batches_lease", "job_match_batches", ["status", "lease_expires_at"])

    op.create_table(
        "job_match_batch_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("fact_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("facts_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("job_match_id", sa.String(length=36), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["job_match_batches.id"]),
        sa.ForeignKeyConstraint(["fact_snapshot_id"], ["resume_fact_snapshots.id"]),
        sa.ForeignKeyConstraint(["job_match_id"], ["job_matches.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "resume_id", name="uq_job_match_batch_item_resume"),
    )
    op.create_index("ix_job_match_batch_items_batch_id", "job_match_batch_items", ["batch_id"])
    op.create_index("ix_job_match_batch_items_resume_id", "job_match_batch_items", ["resume_id"])
    op.create_index("ix_job_match_batch_items_fact_snapshot_id", "job_match_batch_items", ["fact_snapshot_id"])
    op.create_index("ix_job_match_batch_items_status", "job_match_batch_items", ["status"])
    op.create_index("ix_job_match_batch_item_claim", "job_match_batch_items", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_job_match_batch_item_claim", table_name="job_match_batch_items")
    op.drop_index("ix_job_match_batch_items_status", table_name="job_match_batch_items")
    op.drop_index("ix_job_match_batch_items_fact_snapshot_id", table_name="job_match_batch_items")
    op.drop_index("ix_job_match_batch_items_resume_id", table_name="job_match_batch_items")
    op.drop_index("ix_job_match_batch_items_batch_id", table_name="job_match_batch_items")
    op.drop_table("job_match_batch_items")
    op.drop_index("ix_job_match_batches_lease", table_name="job_match_batches")
    op.drop_index("ix_job_match_batches_status", table_name="job_match_batches")
    op.drop_index("ix_job_match_batches_job_version_id", table_name="job_match_batches")
    op.drop_table("job_match_batches")
