"""Add encrypted IMAP configuration and idempotent attachment imports.

Revision ID: 20260717_0010
Revises: 20260717_0009
Create Date: 2026-07-17 23:50:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0010"
down_revision: Union[str, Sequence[str], None] = "20260717_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mailbox_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("mailbox", sa.String(length=255), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mailbox_configs_enabled", "mailbox_configs", ["enabled"])
    op.create_table(
        "email_attachment_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mailbox_config_id", sa.String(length=36), nullable=False),
        sa.Column("message_uid", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.String(length=998), nullable=True),
        sa.Column("attachment_filename", sa.String(length=255), nullable=False),
        sa.Column("attachment_sha256", sa.String(length=64), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mailbox_config_id"], ["mailbox_configs.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mailbox_config_id",
            "message_uid",
            "attachment_sha256",
            name="uq_email_attachment_import_message_attachment",
        ),
    )
    op.create_index("ix_email_attachment_imports_mailbox_config_id", "email_attachment_imports", ["mailbox_config_id"])
    op.create_index("ix_email_attachment_imports_status", "email_attachment_imports", ["status"])
    op.create_index("ix_email_attachment_imports_resume_id", "email_attachment_imports", ["resume_id"])
    op.create_index("ix_email_attachment_imports_config_created", "email_attachment_imports", ["mailbox_config_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_email_attachment_imports_config_created", table_name="email_attachment_imports")
    op.drop_index("ix_email_attachment_imports_resume_id", table_name="email_attachment_imports")
    op.drop_index("ix_email_attachment_imports_status", table_name="email_attachment_imports")
    op.drop_index("ix_email_attachment_imports_mailbox_config_id", table_name="email_attachment_imports")
    op.drop_table("email_attachment_imports")
    op.drop_index("ix_mailbox_configs_enabled", table_name="mailbox_configs")
    op.drop_table("mailbox_configs")
