"""add_niveau_droit_invitation

Revision ID: d4f8a2c1e6b7
Revises: 92ce87978d93
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4f8a2c1e6b7'
down_revision: Union[str, Sequence[str], None] = '92ce87978d93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Le type Postgres `niveau_droit` existe déjà (créé pour `acces` dans la
    # migration initiale) : create_type=False pour ne pas tenter de le
    # recréer. server_default='ecriture' pour matcher le comportement figé
    # d'avant cette migration (accept_invitation forçait NiveauDroit.ecriture)
    # et éviter un backfill séparé sur les invitations déjà en base.
    niveau_droit_enum = postgresql.ENUM('lecture', 'ecriture', 'admin', name='niveau_droit', create_type=False)
    op.add_column(
        'invitation',
        sa.Column('niveau_droit', niveau_droit_enum, server_default='ecriture', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('invitation', 'niveau_droit')
