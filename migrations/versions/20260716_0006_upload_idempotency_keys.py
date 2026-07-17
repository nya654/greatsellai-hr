"""Add durable idempotency records for resume uploads.

Revision ID: 20260716_0006
Revises: 20260716_0005
Create Date: 2026-07-16 17:10:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0006"
down_revision: Union[str, Sequence[str], None] = "20260716_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resume_upload_idempotency_keys",
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("resume_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("idempotency_key_hash"),
        sa.UniqueConstraint("resume_id"),
    )


def downgrade() -> None:
    op.drop_table("resume_upload_idempotency_keys")
