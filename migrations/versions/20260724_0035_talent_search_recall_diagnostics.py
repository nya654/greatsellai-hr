"""Persist talent-profile strict-recall diagnostics.

Revision ID: 20260724_0035
Revises: 20260723_0034
Create Date: 2026-07-24 11:00:00

The JSON payload contains only workspace-scoped aggregate counts and applied
filter labels.  It intentionally stores no candidate text or identifiers.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0035"
down_revision: Union[str, Sequence[str], None] = "20260723_0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "talent_search_runs",
        sa.Column(
            "recall_diagnostics",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    # SQLite cannot drop a column default with ALTER COLUMN.  Retaining the
    # harmless JSON default locally keeps the complete migration chain
    # testable; production PostgreSQL drops it after existing rows are filled.
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("talent_search_runs", "recall_diagnostics", server_default=None)


def downgrade() -> None:
    op.drop_column("talent_search_runs", "recall_diagnostics")
