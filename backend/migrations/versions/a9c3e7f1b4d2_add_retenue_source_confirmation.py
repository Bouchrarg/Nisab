"""add_retenue_source_confirmation

Revision ID: a9c3e7f1b4d2
Revises: f1a4c8e2b9d6
Create Date: 2026-08-08 00:00:00.000000

Ajoute deux colonnes à `alerte_risque` pour débloquer le chiffrage de
l'Art. 151/194 (rémunération à un tiers non déclarée) sans jamais deviner
un fait fiscal à la place du comptable.

Contexte (cf. app.regles_montant.remuneration_tiers_non_declaree_art151) :
la majoration ne s'applique que si le bénéficiaire relevait du régime de
retenue à la source — un statut fiscal du tiers qu'aucune donnée Odoo ne
porte. Jusqu'ici, `_calculer_montant_regle` appelait systématiquement cette
règle avec `retenue_source_applicable=None`, donc "article 151" restait
`non_calculable` à 100% des cas, même quand le comptable connaît la réponse.

Deux colonnes, pas une seule case à cocher : `retenue_source_confirmee`
(oui/non/pas encore répondu) ET `retenue_montant_du` (le montant de retenue
lui-même, que la règle ne peut pas déduire des données comptables non plus —
voir `remuneration_tiers_non_declaree_art151`, qui renvoie 0 DH même sur
"oui" si ce montant manque). `jours_retard` reste hors formulaire : la règle
retombe sur le palier "defaut" (20%) en son absence, ce n'est pas bloquant
pour sortir du 0 DH.

Ces deux colonnes sont un fait humain, pas un résultat d'audit : elles
suivent la même règle que `statut` (jamais écrasées par `_appliquer_finding`
au ré-audit, cf. routes_dossiers.py) — sinon reconfirmer à chaque synchro
comptable rendrait la fonctionnalité inutile.

Nullable, sans backfill : NULL = "jamais demandé au comptable", à ne pas
confondre avec `False` = "confirmé : ne relève PAS de la retenue à la
source" (un vrai résultat, qui doit produire categorie_montant=calculable,
montant=0, pas non_calculable).
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a9c3e7f1b4d2'
down_revision: Union[str, Sequence[str], None] = 'f1a4c8e2b9d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alerte_risque', sa.Column('retenue_source_confirmee', sa.Boolean(), nullable=True))
    op.add_column('alerte_risque', sa.Column('retenue_montant_du', sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('alerte_risque', 'retenue_montant_du')
    op.drop_column('alerte_risque', 'retenue_source_confirmee')
