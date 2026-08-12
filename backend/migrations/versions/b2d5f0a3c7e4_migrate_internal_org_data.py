"""migrate_internal_org_data

Revision ID: b2d5f0a3c7e4
Revises: a1c4e9f2b6d3
Create Date: 2026-07-30 10:05:00.000000

Bascule l'organisation technique "IAAI Academy - Interne" (créée par
scripts/create_platform_admin.py, voir migration précédente) du type
'cabinet' vers 'interne'. Idempotent : ne touche que les lignes qui
correspondent encore à l'ancien état.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2d5f0a3c7e4'
down_revision: Union[str, Sequence[str], None] = 'a1c4e9f2b6d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE organisation SET type_organisation = 'interne' "
            "WHERE nom = 'IAAI Academy - Interne' AND type_organisation = 'cabinet'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE organisation SET type_organisation = 'cabinet' "
            "WHERE nom = 'IAAI Academy - Interne' AND type_organisation = 'interne'"
        )
    )
