"""Persist private recruiting-Agent work-session context.

Revision ID: 20260724_0036
Revises: 20260724_0035
Create Date: 2026-07-24 16:40:00

Only opaque IDs and server-derived candidate-set membership are retained.
Prompts, chat text, candidate names, resume text, source blocks, and model
output are deliberately absent from this schema.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0036"
down_revision: Union[str, Sequence[str], None] = "20260724_0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recruiting_agent_conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("active_job_version_id", sa.String(length=36), nullable=True),
        sa.Column("active_candidate_set_id", sa.String(length=36), nullable=True),
        sa.Column(
            "context_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"]),
        sa.ForeignKeyConstraint(["active_job_version_id"], ["job_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_recruiting_agent_conversation_id_organization",
        ),
    )
    op.create_index(
        "ix_recruiting_agent_conversations_organization_owner_updated",
        "recruiting_agent_conversations",
        ["organization_id", "owner_user_id", "updated_at"],
    )
    op.create_index(
        "ix_recruiting_agent_conversations_organization_id",
        "recruiting_agent_conversations",
        ["organization_id"],
    )
    op.create_index(
        "ix_recruiting_agent_conversations_organization_expiry",
        "recruiting_agent_conversations",
        ["organization_id", "expires_at"],
    )
    op.create_index(
        "ix_recruiting_agent_conversations_owner_user_id",
        "recruiting_agent_conversations",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_recruiting_agent_conversations_active_job_version_id",
        "recruiting_agent_conversations",
        ["active_job_version_id"],
    )
    op.create_index(
        "ix_recruiting_agent_conversations_active_candidate_set_id",
        "recruiting_agent_conversations",
        ["active_candidate_set_id"],
    )
    op.create_index(
        "ix_recruiting_agent_conversations_expires_at",
        "recruiting_agent_conversations",
        ["expires_at"],
    )

    op.create_table(
        "recruiting_agent_candidate_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            [
                "recruiting_agent_conversations.id",
                "recruiting_agent_conversations.organization_id",
            ],
            name="fk_recruiting_agent_candidate_set_conversation_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_recruiting_agent_candidate_set_id_organization",
        ),
    )
    op.create_index(
        "ix_agent_sets_org_conv_created",
        "recruiting_agent_candidate_sets",
        ["organization_id", "conversation_id", "created_at"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_sets_organization_id",
        "recruiting_agent_candidate_sets",
        ["organization_id"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_sets_conversation_id",
        "recruiting_agent_candidate_sets",
        ["conversation_id"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_sets_source_kind",
        "recruiting_agent_candidate_sets",
        ["source_kind"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_sets_source_ref_id",
        "recruiting_agent_candidate_sets",
        ["source_ref_id"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_sets_expires_at",
        "recruiting_agent_candidate_sets",
        ["expires_at"],
    )

    op.create_table(
        "recruiting_agent_candidate_set_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_set_id", sa.String(length=36), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_set_id", "organization_id"],
            [
                "recruiting_agent_candidate_sets.id",
                "recruiting_agent_candidate_sets.organization_id",
            ],
            name="fk_recruiting_agent_candidate_set_item_set_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_set_id",
            "resume_id",
            name="uq_recruiting_agent_candidate_set_item_resume",
        ),
    )
    op.create_index(
        "ix_agent_set_items_org_set_ordinal",
        "recruiting_agent_candidate_set_items",
        ["organization_id", "candidate_set_id", "ordinal"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_set_items_organization_id",
        "recruiting_agent_candidate_set_items",
        ["organization_id"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_set_items_organization_resume",
        "recruiting_agent_candidate_set_items",
        ["organization_id", "resume_id"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_set_items_candidate_set_id",
        "recruiting_agent_candidate_set_items",
        ["candidate_set_id"],
    )
    op.create_index(
        "ix_recruiting_agent_candidate_set_items_resume_id",
        "recruiting_agent_candidate_set_items",
        ["resume_id"],
    )


def downgrade() -> None:
    op.drop_table("recruiting_agent_candidate_set_items")
    op.drop_table("recruiting_agent_candidate_sets")
    op.drop_table("recruiting_agent_conversations")
