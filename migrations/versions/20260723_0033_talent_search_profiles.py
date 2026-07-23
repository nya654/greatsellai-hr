"""Add confirmed AI talent-search profile records.

Revision ID: 20260723_0033
Revises: 20260722_0032
Create Date: 2026-07-23 18:00:00

Talent search profiles are tenant-scoped recruiter work.  Their private
match-job versions reuse the established evidence-grounded JD match worker,
but `jobs.kind` keeps them out of the normal JD workspace.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0033"
down_revision: Union[str, Sequence[str], None] = "20260722_0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'job'"),
        ),
    )
    op.create_index(
        "ix_jobs_organization_kind_updated",
        "jobs",
        ["organization_id", "kind", "updated_at"],
    )

    op.create_table(
        "talent_search_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_job_version_id", sa.String(length=36), nullable=True),
        sa.Column("original_request", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_revision_number", sa.Integer(), nullable=False),
        sa.Column("confirmed_revision_number", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_accounts.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["source_job_version_id"], ["job_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_talent_search_profiles_organization_updated",
        "talent_search_profiles",
        ["organization_id", "updated_at"],
    )
    op.create_index(
        "ix_talent_search_profiles_organization_status",
        "talent_search_profiles",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_talent_search_profiles_organization_id",
        "talent_search_profiles",
        ["organization_id"],
    )
    op.create_index(
        "ix_talent_search_profiles_source_type",
        "talent_search_profiles",
        ["source_type"],
    )
    op.create_index(
        "ix_talent_search_profiles_source_job_version_id",
        "talent_search_profiles",
        ["source_job_version_id"],
    )
    op.create_index(
        "ix_talent_search_profiles_status",
        "talent_search_profiles",
        ["status"],
    )
    op.create_index(
        "ix_talent_search_profiles_created_by_user_id",
        "talent_search_profiles",
        ["created_by_user_id"],
    )

    op.create_table(
        "talent_search_profile_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("hard_filters", sa.JSON(), nullable=False),
        sa.Column("verification_requirements", sa.JSON(), nullable=False),
        sa.Column("preferred_requirements", sa.JSON(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("clarifying_questions", sa.JSON(), nullable=False),
        sa.Column("match_job_version_id", sa.String(length=36), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_user_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["match_job_version_id"], ["job_versions.id"]),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["user_accounts.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["talent_search_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "revision_number",
            name="uq_talent_search_profile_revision_number",
        ),
    )
    op.create_index(
        "ix_talent_search_profile_revisions_organization_profile",
        "talent_search_profile_revisions",
        ["organization_id", "profile_id", "revision_number"],
    )
    op.create_index(
        "ix_talent_search_profile_revisions_organization_id",
        "talent_search_profile_revisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_talent_search_profile_revisions_profile_id",
        "talent_search_profile_revisions",
        ["profile_id"],
    )
    op.create_index(
        "ix_talent_search_profile_revisions_status",
        "talent_search_profile_revisions",
        ["status"],
    )
    op.create_index(
        "ix_talent_search_profile_revisions_match_job_version_id",
        "talent_search_profile_revisions",
        ["match_job_version_id"],
    )
    op.create_index(
        "ix_talent_search_profile_revisions_confirmed_by_user_id",
        "talent_search_profile_revisions",
        ["confirmed_by_user_id"],
    )

    op.create_table(
        "talent_search_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("hard_filter_snapshot", sa.JSON(), nullable=False),
        sa.Column("recalled_resume_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_recalled_count", sa.Integer(), nullable=False),
        sa.Column("job_match_batch_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_match_batch_id"], ["job_match_batches.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["talent_search_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["talent_search_profile_revisions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_talent_search_runs_organization_profile_created",
        "talent_search_runs",
        ["organization_id", "profile_id", "created_at"],
    )
    op.create_index(
        "ix_talent_search_runs_organization_status",
        "talent_search_runs",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_talent_search_runs_organization_id",
        "talent_search_runs",
        ["organization_id"],
    )
    op.create_index("ix_talent_search_runs_profile_id", "talent_search_runs", ["profile_id"])
    op.create_index("ix_talent_search_runs_revision_id", "talent_search_runs", ["revision_id"])
    op.create_index("ix_talent_search_runs_status", "talent_search_runs", ["status"])
    op.create_index(
        "ix_talent_search_runs_job_match_batch_id",
        "talent_search_runs",
        ["job_match_batch_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_talent_search_runs_job_match_batch_id", table_name="talent_search_runs")
    op.drop_index("ix_talent_search_runs_status", table_name="talent_search_runs")
    op.drop_index("ix_talent_search_runs_revision_id", table_name="talent_search_runs")
    op.drop_index("ix_talent_search_runs_profile_id", table_name="talent_search_runs")
    op.drop_index("ix_talent_search_runs_organization_id", table_name="talent_search_runs")
    op.drop_index("ix_talent_search_runs_organization_status", table_name="talent_search_runs")
    op.drop_index(
        "ix_talent_search_runs_organization_profile_created",
        table_name="talent_search_runs",
    )
    op.drop_table("talent_search_runs")

    op.drop_index(
        "ix_talent_search_profile_revisions_confirmed_by_user_id",
        table_name="talent_search_profile_revisions",
    )
    op.drop_index(
        "ix_talent_search_profile_revisions_match_job_version_id",
        table_name="talent_search_profile_revisions",
    )
    op.drop_index("ix_talent_search_profile_revisions_status", table_name="talent_search_profile_revisions")
    op.drop_index("ix_talent_search_profile_revisions_profile_id", table_name="talent_search_profile_revisions")
    op.drop_index(
        "ix_talent_search_profile_revisions_organization_id",
        table_name="talent_search_profile_revisions",
    )
    op.drop_index(
        "ix_talent_search_profile_revisions_organization_profile",
        table_name="talent_search_profile_revisions",
    )
    op.drop_table("talent_search_profile_revisions")

    op.drop_index("ix_talent_search_profiles_created_by_user_id", table_name="talent_search_profiles")
    op.drop_index("ix_talent_search_profiles_status", table_name="talent_search_profiles")
    op.drop_index("ix_talent_search_profiles_source_job_version_id", table_name="talent_search_profiles")
    op.drop_index("ix_talent_search_profiles_source_type", table_name="talent_search_profiles")
    op.drop_index("ix_talent_search_profiles_organization_id", table_name="talent_search_profiles")
    op.drop_index(
        "ix_talent_search_profiles_organization_status",
        table_name="talent_search_profiles",
    )
    op.drop_index(
        "ix_talent_search_profiles_organization_updated",
        table_name="talent_search_profiles",
    )
    op.drop_table("talent_search_profiles")

    op.drop_index("ix_jobs_organization_kind_updated", table_name="jobs")
    op.drop_column("jobs", "kind")
