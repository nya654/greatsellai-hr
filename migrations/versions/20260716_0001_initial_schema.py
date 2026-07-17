"""Create the V3 resume screening baseline schema.

Revision ID: 20260716_0001
Revises:
Create Date: 2026-07-16 13:45:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260716_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "institutions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("roster_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        sa.Column("is_985_211", sa.Boolean(), nullable=False),
        sa.Column("registry_version", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "score_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "institution_aliases",
        sa.Column("alias_key", sa.String(length=255), nullable=False),
        sa.Column("institution_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"]),
        sa.PrimaryKeyConstraint("alias_key"),
    )
    op.create_table(
        "resumes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_page_count", sa.Integer(), nullable=False),
        sa.Column("parsed_page_count", sa.Integer(), nullable=False),
        sa.Column("extraction_status", sa.String(length=32), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_985_211", sa.Boolean(), nullable=True),
        sa.Column("highest_degree", sa.String(length=32), nullable=True),
        sa.Column("employment_months", sa.Integer(), nullable=False),
        sa.Column("employment_or_internship_months", sa.Integer(), nullable=False),
        sa.Column("facts_version", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_table(
        "score_template_dimensions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["score_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "key", name="uq_score_template_dimension_key"),
    )
    op.create_table(
        "job_matches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("facts_version", sa.Integer(), nullable=False),
        sa.Column("job_version", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("must_have_passed", sa.Boolean(), nullable=True),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "resume_educations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("school_name_raw", sa.String(length=255), nullable=False),
        sa.Column("school_key", sa.String(length=255), nullable=True),
        sa.Column("institution_id", sa.String(length=36), nullable=True),
        sa.Column("school_match_state", sa.String(length=32), nullable=False),
        sa.Column("degree", sa.String(length=32), nullable=False),
        sa.Column("major_raw", sa.String(length=255), nullable=True),
        sa.Column("major_key", sa.String(length=255), nullable=True),
        sa.Column("start_month", sa.String(length=7), nullable=True),
        sa.Column("end_month", sa.String(length=7), nullable=True),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "resume_experiences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("experience_type", sa.String(length=32), nullable=False),
        sa.Column("organization_name_raw", sa.String(length=255), nullable=True),
        sa.Column("organization_key", sa.String(length=255), nullable=True),
        sa.Column("title_raw", sa.String(length=255), nullable=True),
        sa.Column("title_key", sa.String(length=255), nullable=True),
        sa.Column("start_month", sa.String(length=7), nullable=True),
        sa.Column("end_month", sa.String(length=7), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False),
        sa.Column("classification_evidence_block_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "resume_fact_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("facts_version", sa.Integer(), nullable=False),
        sa.Column("canonical_facts_json", sa.Text(), nullable=False),
        sa.Column("facts_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_block_ids", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resume_id", "facts_version", name="uq_resume_fact_snapshot_version"),
    )
    op.create_table(
        "resume_review_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "resume_scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("facts_version", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("dimension_scores", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["score_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "resume_skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("skill_key", sa.String(length=120), nullable=False),
        sa.Column("skill_display", sa.String(length=120), nullable=False),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resume_id", "skill_key", name="uq_resume_skill"),
    )
    op.create_table(
        "resume_source_blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resume_id", "block_id", name="uq_resume_block_id"),
    )
    op.create_table(
        "resume_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("facts_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_institutions_roster_id", "institutions", ["roster_id"], unique=True)
    op.create_index(
        "ix_institutions_canonical_key",
        "institutions",
        ["canonical_key"],
        unique=True,
    )
    op.create_index("ix_institutions_is_985_211", "institutions", ["is_985_211"])
    op.create_index(
        "ix_institution_aliases_institution_id",
        "institution_aliases",
        ["institution_id"],
    )

    op.create_index("ix_resumes_candidate_id", "resumes", ["candidate_id"])
    op.create_index("ix_resumes_sha256", "resumes", ["sha256"])
    op.create_index("ix_resumes_extraction_status", "resumes", ["extraction_status"])
    op.create_index("ix_resumes_is_active", "resumes", ["is_active"])
    op.create_index("ix_resumes_is_985_211", "resumes", ["is_985_211"])
    op.create_index("ix_resumes_highest_degree", "resumes", ["highest_degree"])
    op.create_index("ix_resumes_employment_months", "resumes", ["employment_months"])
    op.create_index(
        "ix_resumes_employment_or_internship_months",
        "resumes",
        ["employment_or_internship_months"],
    )
    op.create_index(
        "uq_active_resume_per_candidate",
        "resumes",
        ["candidate_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_index(
        "ix_score_template_dimensions_template_id",
        "score_template_dimensions",
        ["template_id"],
    )
    op.create_index("ix_job_matches_job_id", "job_matches", ["job_id"])
    op.create_index("ix_job_matches_resume_id", "job_matches", ["resume_id"])

    op.create_index("ix_resume_educations_resume_id", "resume_educations", ["resume_id"])
    op.create_index("ix_resume_educations_school_key", "resume_educations", ["school_key"])
    op.create_index(
        "ix_resume_educations_institution_id",
        "resume_educations",
        ["institution_id"],
    )
    op.create_index("ix_resume_educations_degree", "resume_educations", ["degree"])
    op.create_index("ix_resume_educations_major_key", "resume_educations", ["major_key"])

    op.create_index("ix_resume_experiences_resume_id", "resume_experiences", ["resume_id"])
    op.create_index(
        "ix_resume_experiences_experience_type",
        "resume_experiences",
        ["experience_type"],
    )
    op.create_index(
        "ix_resume_experiences_organization_key",
        "resume_experiences",
        ["organization_key"],
    )
    op.create_index("ix_resume_experiences_title_key", "resume_experiences", ["title_key"])

    op.create_index(
        "ix_resume_fact_snapshots_resume_id",
        "resume_fact_snapshots",
        ["resume_id"],
    )
    op.create_index(
        "ix_resume_fact_snapshot_sha256",
        "resume_fact_snapshots",
        ["facts_sha256"],
    )
    op.create_index(
        "ix_resume_review_actions_resume_id",
        "resume_review_actions",
        ["resume_id"],
    )
    op.create_index("ix_resume_scores_resume_id", "resume_scores", ["resume_id"])
    op.create_index("ix_resume_scores_template_id", "resume_scores", ["template_id"])
    op.create_index("ix_resume_skills_resume_id", "resume_skills", ["resume_id"])
    op.create_index("ix_resume_skills_skill_key", "resume_skills", ["skill_key"])
    op.create_index(
        "ix_resume_source_blocks_resume_id",
        "resume_source_blocks",
        ["resume_id"],
    )
    op.create_index(
        "ix_resume_summaries_resume_id",
        "resume_summaries",
        ["resume_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_resume_summaries_resume_id", table_name="resume_summaries")
    op.drop_table("resume_summaries")

    op.drop_index("ix_resume_source_blocks_resume_id", table_name="resume_source_blocks")
    op.drop_table("resume_source_blocks")

    op.drop_index("ix_resume_skills_skill_key", table_name="resume_skills")
    op.drop_index("ix_resume_skills_resume_id", table_name="resume_skills")
    op.drop_table("resume_skills")

    op.drop_index("ix_resume_scores_template_id", table_name="resume_scores")
    op.drop_index("ix_resume_scores_resume_id", table_name="resume_scores")
    op.drop_table("resume_scores")

    op.drop_index("ix_resume_review_actions_resume_id", table_name="resume_review_actions")
    op.drop_table("resume_review_actions")

    op.drop_index(
        "ix_resume_fact_snapshot_sha256",
        table_name="resume_fact_snapshots",
    )
    op.drop_index(
        "ix_resume_fact_snapshots_resume_id",
        table_name="resume_fact_snapshots",
    )
    op.drop_table("resume_fact_snapshots")

    op.drop_index("ix_resume_experiences_title_key", table_name="resume_experiences")
    op.drop_index(
        "ix_resume_experiences_organization_key",
        table_name="resume_experiences",
    )
    op.drop_index(
        "ix_resume_experiences_experience_type",
        table_name="resume_experiences",
    )
    op.drop_index("ix_resume_experiences_resume_id", table_name="resume_experiences")
    op.drop_table("resume_experiences")

    op.drop_index("ix_resume_educations_major_key", table_name="resume_educations")
    op.drop_index("ix_resume_educations_degree", table_name="resume_educations")
    op.drop_index(
        "ix_resume_educations_institution_id",
        table_name="resume_educations",
    )
    op.drop_index("ix_resume_educations_school_key", table_name="resume_educations")
    op.drop_index("ix_resume_educations_resume_id", table_name="resume_educations")
    op.drop_table("resume_educations")

    op.drop_index("ix_job_matches_resume_id", table_name="job_matches")
    op.drop_index("ix_job_matches_job_id", table_name="job_matches")
    op.drop_table("job_matches")

    op.drop_index(
        "ix_score_template_dimensions_template_id",
        table_name="score_template_dimensions",
    )
    op.drop_table("score_template_dimensions")

    op.drop_index("uq_active_resume_per_candidate", table_name="resumes")
    op.drop_index("ix_resumes_employment_or_internship_months", table_name="resumes")
    op.drop_index("ix_resumes_employment_months", table_name="resumes")
    op.drop_index("ix_resumes_highest_degree", table_name="resumes")
    op.drop_index("ix_resumes_is_985_211", table_name="resumes")
    op.drop_index("ix_resumes_is_active", table_name="resumes")
    op.drop_index("ix_resumes_extraction_status", table_name="resumes")
    op.drop_index("ix_resumes_sha256", table_name="resumes")
    op.drop_index("ix_resumes_candidate_id", table_name="resumes")
    op.drop_table("resumes")

    op.drop_index(
        "ix_institution_aliases_institution_id",
        table_name="institution_aliases",
    )
    op.drop_table("institution_aliases")
    op.drop_table("score_templates")
    op.drop_table("jobs")

    op.drop_index("ix_institutions_is_985_211", table_name="institutions")
    op.drop_index("ix_institutions_canonical_key", table_name="institutions")
    op.drop_index("ix_institutions_roster_id", table_name="institutions")
    op.drop_table("institutions")
    op.drop_table("candidates")
