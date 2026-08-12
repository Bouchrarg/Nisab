"""add_interne_org_type

Revision ID: a1c4e9f2b6d3
Revises: 689bf7bc8aaf
Create Date: 2026-07-30 10:00:00.000000

Ajoute la valeur 'interne' à l'enum type_organisation.

Contexte : create_platform_admin.py (bootstrap du tout premier compte
admin_plateforme) doit rattacher cet utilisateur à une organisation à cause
de la contrainte FK sur utilisateur.organisation_id, alors qu'un
admin_plateforme n'appartient à aucun cabinet client. Faute d'une 3e valeur
d'enum, le script utilisait 'cabinet' par défaut — ce qui faisait compter
cette organisation technique ("IAAI Academy - Interne") dans les KPIs
"organisations"/"cabinets" de l'overview plateforme (voir admin.py). Cette
migration ajoute la valeur d'enum manquante ; la migration suivante
(b2d5f0a3c7e4) corrige la donnée existante et bascule admin.py à l'exclure
des compteurs.

Migration séparée (comme 95e0d7d9338b) : ALTER TYPE ... ADD VALUE ne peut
pas être utilisé dans la même transaction que celle qui consomme cette
nouvelle valeur (UPDATE), donc schéma et donnée sont scindés en deux
migrations distinctes.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c4e9f2b6d3'
down_revision: Union[str, Sequence[str], None] = '689bf7bc8aaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE type_organisation ADD VALUE IF NOT EXISTS 'interne'"
        )


def downgrade() -> None:
    # Comme pour 95e0d7d9338b : Postgres ne permet pas de retirer une valeur
    # d'un enum directement (nécessiterait de recréer le type). Non
    # implémenté volontairement — cas rare en pratique.
    pass
