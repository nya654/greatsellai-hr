"""Start mailbox ingestion at the UID present when the mailbox is bound.

Revision ID: 20260718_0011
Revises: 20260717_0010
Create Date: 2026-07-18 10:15:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0011"
down_revision: Union[str, Sequence[str], None] = "20260717_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable is deliberate: existing mailbox configurations establish their
    # baseline on the first post-upgrade sync without importing old mail.
    op.add_column(
        "mailbox_configs",
        sa.Column("import_start_uid", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "mailbox_configs",
        sa.Column("imap_uidvalidity", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "mailbox_configs",
        sa.Column("import_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mailbox_configs", "import_started_at")
    op.drop_column("mailbox_configs", "imap_uidvalidity")
    op.drop_column("mailbox_configs", "import_start_uid")
