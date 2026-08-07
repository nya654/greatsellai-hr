"""Add per-workspace AI import processing settings.

Revision ID: 20260806_0059
Revises: 20260805_0057
Create Date: 2026-08-06 16:00:00

Each workspace gets one lazily-created row controlling whether imported
resumes auto-run AI summary / scoring and for which ingestion sources.
Defaults are all-on, matching the product's "默认全开" decision.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0059"
down_revision: Union[str, Sequence[str], None] = "20260805_0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_ai_import_settings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column(
            "auto_summary_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "auto_score_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("default_score_template_id", sa.String(length=36), nullable=True),
        sa.Column(
            "trigger_manual_upload",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "trigger_mailbox_import",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["default_score_template_id"], ["score_templates.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["user_accounts.id"]),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_workspace_ai_import_settings_organization",
        ),
    )
    op.create_index(
        "ix_workspace_ai_import_settings_organization_id",
        "workspace_ai_import_settings",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_ai_import_settings_organization_id",
        table_name="workspace_ai_import_settings",
    )
    op.drop_table("workspace_ai_import_settings")
