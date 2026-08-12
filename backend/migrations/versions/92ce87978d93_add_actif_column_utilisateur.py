"""add_actif_column_utilisateur

Revision ID: 92ce87978d93
Revises: c3e6a1b8d9f5
Create Date: 2026-07-31 04:56:45.461263

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '92ce87978d93'
down_revision: Union[str, Sequence[str], None] = 'c3e6a1b8d9f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE : l'autogénération avait aussi détecté un tas de drift sans
    # rapport avec ce changement (tables du corpus fiscal `articles` /
    # `documents` / `veille_log` / `journal_acces` créées hors SQLAlchemy,
    # contraintes NOT NULL divergentes historiques...). Tout ça a été retiré
    # à la main : cette migration ne fait QUE ce qu'elle annonce, ajouter
    # `actif` sur `utilisateur`. server_default=true pour que les comptes
    # existants restent actifs sans backfill séparé.
    op.add_column(
        'utilisateur',
        sa.Column('actif', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('utilisateur', 'actif')
