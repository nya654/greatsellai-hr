"""Support multiple AI-import scoring templates per workspace.

Revision ID: 20260806_0062
Revises: 20260806_0061
Create Date: 2026-08-07

The single default_score_template_id column becomes a score_template_ids JSON
array so a workspace can auto-score against several templates. Existing
single-template rows are migrated into the new column; auto-scoring requires
at least one template. Core table expressions keep the JSON backfill
portable across SQLite and PostgreSQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0062"
down_revision: Union[str, Sequence[str], None] = "20260806_0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "workspace_ai_import_settings",
        sa.Column("score_template_ids", sa.JSON(), nullable=True),
    )
    table = sa.table(
        "workspace_ai_import_settings",
        sa.column("id", sa.String()),
        sa.column("default_score_template_id", sa.String()),
        sa.column("score_template_ids", sa.JSON()),
    )
    bind.execute(table.update().values(score_template_ids=[]))
    rows = bind.execute(
        sa.select(table.c.id, table.c.default_score_template_id).where(
            table.c.default_score_template_id.is_not(None)
        )
    )
    for row_id, template_id in rows:
        bind.execute(
            table.update()
            .where(table.c.id == row_id)
            .values(score_template_ids=[template_id])
        )
    # SQLite cannot drop a column that a foreign key references; batch mode
    # rebuilds the table there (and issues plain DDL on PostgreSQL).
    with op.batch_alter_table("workspace_ai_import_settings") as batch_op:
        batch_op.drop_column("default_score_template_id")


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("workspace_ai_import_settings") as batch_op:
        batch_op.add_column(
            sa.Column("default_score_template_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_workspace_ai_import_settings_default_score_template_id",
            "score_templates",
            ["default_score_template_id"],
            ["id"],
        )
    table = sa.table(
        "workspace_ai_import_settings",
        sa.column("id", sa.String()),
        sa.column("default_score_template_id", sa.String()),
        sa.column("score_template_ids", sa.JSON()),
    )
    rows = bind.execute(sa.select(table.c.id, table.c.score_template_ids))
    for row_id, template_ids in rows:
        first = template_ids[0] if template_ids else None
        bind.execute(
            table.update()
            .where(table.c.id == row_id)
            .values(default_score_template_id=first)
        )
    with op.batch_alter_table("workspace_ai_import_settings") as batch_op:
        batch_op.drop_column("score_template_ids")
