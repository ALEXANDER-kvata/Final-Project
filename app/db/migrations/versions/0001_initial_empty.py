"""initial empty migration

Revision ID: 0001_initial_empty
Revises:
Create Date: 2026-08-10 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "0001_initial_empty"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
