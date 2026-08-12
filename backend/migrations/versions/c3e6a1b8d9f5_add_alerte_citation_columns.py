"""add_alerte_citation_columns

Revision ID: c3e6a1b8d9f5
Revises: b2d5f0a3c7e4
Create Date: 2026-07-30 10:15:00.000000

Ajoute reference_cgi et rag_sources_json à alerte_risque.

Contexte : le finding produit par run_ai_rag_audit() contenait déjà
reference_cgi et rag_sources (voir ai_auditor.py), mais _execute_audit()
(routes_dossiers.py) ne les persistait pas — seuls titre/description/
niveau/montant étaient écrits en base. Résultat : dès qu'une deuxième
requête retombait sur le cache (hash_donnees inchangé), la réponse
reconstruite via _alerte_to_dict() perdait silencieusement la base légale
de chaque alerte, ce qui casse à la fois l'affichage (FindingCard) et,
surtout, la Phase 4 (simulation de contrôle) qui a besoin d'un
argumentaire *sourcé* à partir des alertes existantes. CITATION_RISQUE
(déjà présente dans le MCD) reste la table de traçabilité normalisée pour
l'historique horodaté multi-articles ; ces deux colonnes sur alerte_risque
donnent un accès direct et rapide à "la" référence retenue pour cette
alerte sans jointure, ce qui est ce dont FindingCard/control_simulator ont
besoin.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3e6a1b8d9f5'
down_revision: Union[str, Sequence[str], None] = 'b2d5f0a3c7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alerte_risque', sa.Column('reference_cgi', sa.String(200), nullable=True))
    op.add_column('alerte_risque', sa.Column('rag_sources_json', pg.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('alerte_risque', 'rag_sources_json')
    op.drop_column('alerte_risque', 'reference_cgi')
