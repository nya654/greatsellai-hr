"""Merge the account-registration and batch-score migration heads.

Revision ID: 20260720_0017
Revises: 20260720_0015, 20260720_0016
Create Date: 2026-07-20 16:50:00

This is intentionally a no-op schema merge. Both parent revisions contain
independent, already-reviewed schema changes and must be applied before future
releases can advance through one canonical Alembic head.
"""
from __future__ import annotations

from typing import Sequence, Union


revision: str = "20260720_0017"
down_revision: Union[str, Sequence[str], None] = (
    "20260720_0015",
    "20260720_0016",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
