"""add_admin_plateforme_role

Revision ID: 95e0d7d9338b
Revises: 834f91da7e7e
Create Date: 2026-07-29 01:01:53.546932

Ajoute la valeur 'admin_plateforme' à l'enum role_utilisateur.

Contexte : /admin (gestion du corpus fiscal partagé, veille, pipeline
d'ingestion) était protégé par require_role("admin_cabinet"), qui est en
réalité le rôle d'administration D'UN cabinet client (son organisation, ses
dossiers). Un admin_cabinet ne doit jamais pouvoir modifier le corpus
partagé entre tous les tenants — il fallait un rôle distinct, non rattaché
à un cabinet client, réservé à l'équipe Nisab/IAAI Academy elle-même.

Migration séparée (plutôt que de modifier 0001 seule) pour rester
applicable même si 0001 a déjà été exécutée sur une base existante.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '95e0d7d9338b'
down_revision: Union[str, Sequence[str], None] = '834f91da7e7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE role_utilisateur ADD VALUE IF NOT EXISTS 'admin_plateforme'")


def downgrade() -> None:
    # Postgres ne permet pas de retirer une valeur d'un enum directement.
    # Une vraie rollback nécessiterait de recréer le type — non implémenté
    # ici volontairement (cas très rare en pratique, à traiter au besoin).
    pass
