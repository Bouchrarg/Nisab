"""add_montant_regle_columns

Revision ID: f1a4c8e2b9d6
Revises: b8d2f5a7c1e4
Create Date: 2026-08-07 00:00:00.000000

Ajoute categorie_montant / montant_detail / montant_hypothese à
alerte_risque ET proposition_correction.

Contexte : jusqu'ici, `amount_risk` (audit) et `montant_impact` (correction)
étaient des nombres inventés par le LLM sans aucune vérification
arithmétique — contrairement aux citations légales (filtrées) ou aux
écritures de correction (rééquilibrées). C'est le seul endroit du produit où
un montant était affirmé sans être sourcé (règle d'architecture du projet,
"zéro affirmation sans source"). `app.regles_montant` calcule désormais ces montants par une
formule déterministe testée, pour les articles où une formule existe ; le
LLM ne produit plus jamais de chiffre en DH (voir le nouveau
AUDIT_SYSTEM_PROMPT / SYSTEM_PROMPT de correction_agent).

Trois colonnes, pas juste le montant : sans `categorie_montant`, un frontend
ne peut pas distinguer "0 DH, vérifié, aucun risque" de "montant non
calculable, ne rien affirmer" — deux situations qui, un chiffre nu, se
ressemblent. `montant_detail`/`montant_hypothese` sont le calcul en toutes
lettres, pour qu'un contrôleur DGI (ou l'étudiante qui soutient ce projet)
puisse le vérifier sans deviner d'où le nombre sort.

Nullable partout, sans backfill : une ligne NULL signifie "antérieure au
moteur de règles, jamais recalculée" — distinct de "non_calculable" (une
règle a tourné et a explicitement dit qu'elle ne pouvait rien affirmer). Un
prochain audit remplit le champ pour les alertes actives ; les alertes
inactives (actif=False) restent NULL, ce qui est correct : on ne réécrit pas
l'historique.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a4c8e2b9d6'
down_revision: Union[str, Sequence[str], None] = 'b8d2f5a7c1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alerte_risque', sa.Column('categorie_montant', sa.String(30), nullable=True))
    op.add_column('alerte_risque', sa.Column('montant_detail', sa.Text(), nullable=True))
    op.add_column('alerte_risque', sa.Column('montant_hypothese', sa.Text(), nullable=True))

    op.add_column('proposition_correction', sa.Column('categorie_montant', sa.String(30), nullable=True))
    op.add_column('proposition_correction', sa.Column('montant_detail', sa.Text(), nullable=True))
    op.add_column('proposition_correction', sa.Column('montant_hypothese', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('proposition_correction', 'montant_hypothese')
    op.drop_column('proposition_correction', 'montant_detail')
    op.drop_column('proposition_correction', 'categorie_montant')

    op.drop_column('alerte_risque', 'montant_hypothese')
    op.drop_column('alerte_risque', 'montant_detail')
    op.drop_column('alerte_risque', 'categorie_montant')
