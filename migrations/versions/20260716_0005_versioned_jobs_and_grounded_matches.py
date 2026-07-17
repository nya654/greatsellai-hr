"""Add versioned JD requirements and grounded match results.

Revision ID: 20260716_0005
Revises: 20260716_0004
Create Date: 2026-07-16 15:30:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0005"
down_revision: Union[str, Sequence[str], None] = "20260716_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "version", name="uq_job_version"),
    )
    op.create_index("ix_job_versions_job_id", "job_versions", ["job_id"])
    op.create_index("ix_job_versions_status", "job_versions", ["status"])
    op.create_table(
        "job_source_clauses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_version_id", sa.String(length=36), nullable=False),
        sa.Column("clause_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_version_id", "clause_id", name="uq_job_clause_id"),
    )
    op.create_index(
        "ix_job_source_clauses_job_version_id",
        "job_source_clauses",
        ["job_version_id"],
    )
    op.create_table(
        "job_requirements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_version_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_key", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("raw_requirement", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.JSON(), nullable=False),
        sa.Column("minimum_months", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("clause_ids", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_version_id", "requirement_key", name="uq_job_requirement_key"),
    )
    op.create_index(
        "ix_job_requirements_job_version_id",
        "job_requirements",
        ["job_version_id"],
    )
    op.create_index("ix_job_requirements_priority", "job_requirements", ["priority"])
    op.create_index("ix_job_requirements_category", "job_requirements", ["category"])

    with op.batch_alter_table("job_matches") as batch_op:
        batch_op.add_column(
            sa.Column("job_version_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("fact_snapshot_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(sa.Column("evidence_coverage", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("hard_requirement_status", sa.String(length=32), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_job_matches_job_version_id",
            "job_versions",
            ["job_version_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_job_matches_fact_snapshot_id",
            "resume_fact_snapshots",
            ["fact_snapshot_id"],
            ["id"],
        )
        batch_op.create_index("ix_job_matches_job_version_id", ["job_version_id"])
        batch_op.create_index("ix_job_matches_fact_snapshot_id", ["fact_snapshot_id"])

    op.create_table(
        "job_match_requirement_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_match_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("fact_ids", sa.JSON(), nullable=False),
        sa.Column("missing_or_uncertain", sa.Text(), nullable=True),
        sa.Column("score_contribution", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["job_match_id"], ["job_matches.id"]),
        sa.ForeignKeyConstraint(["requirement_id"], ["job_requirements.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_match_id", "requirement_id", name="uq_job_match_requirement"),
    )
    op.create_index(
        "ix_job_match_requirement_results_job_match_id",
        "job_match_requirement_results",
        ["job_match_id"],
    )
    op.create_index(
        "ix_job_match_requirement_results_requirement_id",
        "job_match_requirement_results",
        ["requirement_id"],
    )
    op.create_index(
        "ix_job_match_requirement_results_outcome",
        "job_match_requirement_results",
        ["outcome"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_match_requirement_results_outcome",
        table_name="job_match_requirement_results",
    )
    op.drop_index(
        "ix_job_match_requirement_results_requirement_id",
        table_name="job_match_requirement_results",
    )
    op.drop_index(
        "ix_job_match_requirement_results_job_match_id",
        table_name="job_match_requirement_results",
    )
    op.drop_table("job_match_requirement_results")

    with op.batch_alter_table("job_matches") as batch_op:
        batch_op.drop_index("ix_job_matches_fact_snapshot_id")
        batch_op.drop_index("ix_job_matches_job_version_id")
        batch_op.drop_constraint("fk_job_matches_fact_snapshot_id", type_="foreignkey")
        batch_op.drop_constraint("fk_job_matches_job_version_id", type_="foreignkey")
        batch_op.drop_column("hard_requirement_status")
        batch_op.drop_column("evidence_coverage")
        batch_op.drop_column("fact_snapshot_id")
        batch_op.drop_column("job_version_id")

    op.drop_index("ix_job_requirements_category", table_name="job_requirements")
    op.drop_index("ix_job_requirements_priority", table_name="job_requirements")
    op.drop_index("ix_job_requirements_job_version_id", table_name="job_requirements")
    op.drop_table("job_requirements")
    op.drop_index("ix_job_source_clauses_job_version_id", table_name="job_source_clauses")
    op.drop_table("job_source_clauses")
    op.drop_index("ix_job_versions_status", table_name="job_versions")
    op.drop_index("ix_job_versions_job_id", table_name="job_versions")
    op.drop_table("job_versions")
