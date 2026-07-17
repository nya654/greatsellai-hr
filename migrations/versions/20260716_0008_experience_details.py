"""Store names and source-cited detail items for resume experiences.

Revision ID: 20260716_0008
Revises: 20260716_0007
Create Date: 2026-07-16 20:10:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0008"
down_revision: Union[str, Sequence[str], None] = "20260716_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "resume_experiences",
        sa.Column("experience_name_raw", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "resume_experiences",
        sa.Column("experience_name_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "resume_experiences",
        sa.Column(
            "detail_items",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.create_index(
        "ix_resume_experiences_experience_name_key",
        "resume_experiences",
        ["experience_name_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resume_experiences_experience_name_key",
        table_name="resume_experiences",
    )
    op.drop_column("resume_experiences", "detail_items")
    op.drop_column("resume_experiences", "experience_name_key")
    op.drop_column("resume_experiences", "experience_name_raw")
