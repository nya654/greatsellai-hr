"""Add a provider-agnostic large-model allowance to trial workspaces.

Revision ID: 20260723_0033
Revises: 20260722_0032
Create Date: 2026-07-23 15:20:00

Only actual provider attempts in the AI ledger count.  The migration backfills
the traceable portion of a current trial and caps it at the new allowance, so
an existing trial workspace cannot receive an unbounded second allowance at
rollout time.  ``service_kind`` is reporting metadata, not a billing bypass.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0033"
down_revision: Union[str, Sequence[str], None] = "20260722_0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TRIAL_LLM_CALL_LIMIT = 1_000


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "trial_llm_call_limit",
            sa.Integer(),
            nullable=False,
            server_default=sa.text(str(TRIAL_LLM_CALL_LIMIT)),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "trial_llm_call_used",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    organizations = sa.table(
        "organizations",
        sa.column("id", sa.String()),
        sa.column("plan_status", sa.String()),
        sa.column("trial_started_at", sa.DateTime(timezone=True)),
        sa.column("trial_ends_at", sa.DateTime(timezone=True)),
        sa.column("trial_llm_call_used", sa.Integer()),
    )
    invocations = sa.table(
        "api_invocations",
        sa.column("id", sa.String()),
        sa.column("ai_run_id", sa.String()),
        sa.column("organization_id", sa.String()),
        sa.column("started_at", sa.DateTime(timezone=True)),
    )
    attempt_count = (
        sa.select(sa.func.count(invocations.c.id))
        .where(
            invocations.c.organization_id == organizations.c.id,
            sa.or_(
                organizations.c.trial_started_at.is_(None),
                invocations.c.started_at >= organizations.c.trial_started_at,
            ),
            sa.or_(
                organizations.c.trial_ends_at.is_(None),
                invocations.c.started_at < organizations.c.trial_ends_at,
            ),
        )
        .correlate(organizations)
        .scalar_subquery()
    )
    op.execute(
        organizations.update()
        .where(organizations.c.plan_status == "trial")
        .values(
            trial_llm_call_used=sa.case(
                (attempt_count >= TRIAL_LLM_CALL_LIMIT, TRIAL_LLM_CALL_LIMIT),
                else_=attempt_count,
            )
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_column("trial_llm_call_used")
        batch_op.drop_column("trial_llm_call_limit")
