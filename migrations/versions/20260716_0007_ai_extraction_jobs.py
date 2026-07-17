"""Add durable server-side AI resume extraction jobs.

Revision ID: 20260716_0007
Revises: 20260716_0006
Create Date: 2026-07-16 18:25:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0007"
down_revision: Union[str, Sequence[str], None] = "20260716_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resume_ai_extraction_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("input_facts_version", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resume_id", name="uq_resume_ai_extraction_job_resume"),
    )
    op.create_index(
        "ix_resume_ai_extraction_job_claim",
        "resume_ai_extraction_jobs",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_resume_ai_extraction_job_lease",
        "resume_ai_extraction_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_resume_ai_extraction_jobs_resume_id",
        "resume_ai_extraction_jobs",
        ["resume_id"],
    )
    op.create_index(
        "ix_resume_ai_extraction_jobs_status",
        "resume_ai_extraction_jobs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_resume_ai_extraction_jobs_status", table_name="resume_ai_extraction_jobs")
    op.drop_index("ix_resume_ai_extraction_jobs_resume_id", table_name="resume_ai_extraction_jobs")
    op.drop_index("ix_resume_ai_extraction_job_lease", table_name="resume_ai_extraction_jobs")
    op.drop_index("ix_resume_ai_extraction_job_claim", table_name="resume_ai_extraction_jobs")
    op.drop_table("resume_ai_extraction_jobs")
