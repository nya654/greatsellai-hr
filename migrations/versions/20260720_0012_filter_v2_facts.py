"""Add source-grounded facts used by condition filter V2.

Revision ID: 20260720_0012
Revises: 20260718_0011
Create Date: 2026-07-20 12:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0012"
down_revision: Union[str, Sequence[str], None] = "20260718_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "resume_ai_extraction_jobs",
        sa.Column("job_kind", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE resume_ai_extraction_jobs SET job_kind = 'initial' WHERE job_kind IS NULL"
    )
    op.add_column("institutions", sa.Column("tier_tags", sa.JSON(), nullable=True))
    op.add_column("resume_educations", sa.Column("institution_tiers", sa.JSON(), nullable=True))
    op.add_column("resume_educations", sa.Column("average_score", sa.Float(), nullable=True))
    op.add_column("resume_educations", sa.Column("gpa_value", sa.Float(), nullable=True))
    op.add_column("resume_educations", sa.Column("gpa_scale", sa.Float(), nullable=True))
    op.add_column("resume_educations", sa.Column("gpa_percent", sa.Float(), nullable=True))
    op.add_column("resume_educations", sa.Column("rank_position", sa.Integer(), nullable=True))
    op.add_column("resume_educations", sa.Column("rank_total", sa.Integer(), nullable=True))
    op.add_column("resume_educations", sa.Column("rank_percent", sa.Float(), nullable=True))
    op.add_column("resume_experiences", sa.Column("leadership_context", sa.String(length=32), nullable=True))
    op.add_column("resume_experiences", sa.Column("leadership_role", sa.String(length=64), nullable=True))
    op.add_column("resume_experiences", sa.Column("award_level", sa.String(length=32), nullable=True))
    op.add_column("resume_experiences", sa.Column("award_result_raw", sa.String(length=255), nullable=True))
    op.add_column("resume_skills", sa.Column("skill_category", sa.String(length=64), nullable=True))

    op.create_index("ix_resume_educations_gpa_percent", "resume_educations", ["gpa_percent"])
    op.create_index("ix_resume_educations_rank_percent", "resume_educations", ["rank_percent"])
    op.create_index("ix_resume_experiences_leadership_context", "resume_experiences", ["leadership_context"])
    op.create_index("ix_resume_experiences_leadership_role", "resume_experiences", ["leadership_role"])
    op.create_index("ix_resume_experiences_award_level", "resume_experiences", ["award_level"])
    op.create_index("ix_resume_skills_skill_category", "resume_skills", ["skill_category"])

    op.create_table(
        "resume_language_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("credential_code", sa.String(length=32), nullable=False),
        sa.Column("credential_name_raw", sa.String(length=120), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resume_id", "credential_code", "score", name="uq_resume_language_credential"),
    )
    op.create_index("ix_resume_language_credentials_resume_id", "resume_language_credentials", ["resume_id"])
    op.create_index("ix_resume_language_credentials_code", "resume_language_credentials", ["credential_code"])
    op.create_index("ix_resume_language_credentials_score", "resume_language_credentials", ["score"])

    op.create_table(
        "resume_scholarships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("scholarship_name_raw", sa.String(length=255), nullable=False),
        sa.Column("scholarship_name_key", sa.String(length=255), nullable=False),
        sa.Column("scholarship_level", sa.String(length=32), nullable=True),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resume_scholarships_resume_id", "resume_scholarships", ["resume_id"])
    op.create_index("ix_resume_scholarships_name_key", "resume_scholarships", ["scholarship_name_key"])
    op.create_index("ix_resume_scholarships_level", "resume_scholarships", ["scholarship_level"])

    # Existing facts remain valid and deliberately have no inferred V2 values.
    op.execute("UPDATE institutions SET tier_tags = '[]' WHERE tier_tags IS NULL")
    op.execute("UPDATE resume_educations SET institution_tiers = '[]' WHERE institution_tiers IS NULL")


def downgrade() -> None:
    op.drop_index("ix_resume_scholarships_level", table_name="resume_scholarships")
    op.drop_index("ix_resume_scholarships_name_key", table_name="resume_scholarships")
    op.drop_index("ix_resume_scholarships_resume_id", table_name="resume_scholarships")
    op.drop_table("resume_scholarships")
    op.drop_index("ix_resume_language_credentials_score", table_name="resume_language_credentials")
    op.drop_index("ix_resume_language_credentials_code", table_name="resume_language_credentials")
    op.drop_index("ix_resume_language_credentials_resume_id", table_name="resume_language_credentials")
    op.drop_table("resume_language_credentials")
    op.drop_index("ix_resume_skills_skill_category", table_name="resume_skills")
    op.drop_index("ix_resume_experiences_award_level", table_name="resume_experiences")
    op.drop_index("ix_resume_experiences_leadership_role", table_name="resume_experiences")
    op.drop_index("ix_resume_experiences_leadership_context", table_name="resume_experiences")
    op.drop_index("ix_resume_educations_rank_percent", table_name="resume_educations")
    op.drop_index("ix_resume_educations_gpa_percent", table_name="resume_educations")
    op.drop_column("resume_skills", "skill_category")
    op.drop_column("resume_experiences", "award_result_raw")
    op.drop_column("resume_experiences", "award_level")
    op.drop_column("resume_experiences", "leadership_role")
    op.drop_column("resume_experiences", "leadership_context")
    op.drop_column("resume_educations", "rank_percent")
    op.drop_column("resume_educations", "rank_total")
    op.drop_column("resume_educations", "rank_position")
    op.drop_column("resume_educations", "gpa_percent")
    op.drop_column("resume_educations", "gpa_scale")
    op.drop_column("resume_educations", "gpa_value")
    op.drop_column("resume_educations", "average_score")
    op.drop_column("resume_educations", "institution_tiers")
    op.drop_column("institutions", "tier_tags")
    op.drop_column("resume_ai_extraction_jobs", "job_kind")
