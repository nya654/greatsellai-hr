"""Merge the settings-center and recruiting-agent-label migration heads.

Revision ID: 20260806_0061
Revises: 20260806_0060, 20260806_0058
Create Date: 2026-08-07 12:00:00

``20260806_0058`` (recruiting-agent turn-label rename) landed on main while
the settings-center branch added ``20260806_0059`` / ``20260806_0060`` from the
same parent ``20260805_0057``.  Both contain independent, already-reviewed
schema changes and must be applied before future releases can advance through
one canonical Alembic head, so this is intentionally a no-op schema merge.
"""
from __future__ import annotations

from typing import Sequence, Union


revision: str = "20260806_0061"
down_revision: Union[str, Sequence[str], None] = (
    "20260806_0060",
    "20260806_0058",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
