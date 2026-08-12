"""add_alerte_cle_metier

Revision ID: e5a9c2d4f8b1
Revises: d4f8a2c1e6b7
Create Date: 2026-08-05 09:00:00.000000

Donne à alerte_risque une identité stable dans le temps + le contexte de
l'écriture auditée.

## Le problème corrigé

_execute_audit() (routes_dossiers.py) supprimait TOUTES les CitationRisque
puis TOUTES les AlerteRisque du dossier à chaque exécution non cachée, puis
les recréait avec des UUID neufs. Conséquence : le champ `statut`
(ouverte/traitee/ignoree), qui existe depuis la Phase 1, ne pouvait pas
survivre à un ré-audit, et toute donnée humaine accrochée à alerte_risque.id
était détruite en silence.

Cela rendait le workflow de correction avec validation humaine littéralement
impossible : une correction validée par un collaborateur disparaissait dès la
prochaine synchronisation comptable.

Le correctif n'est pas « arrêter de supprimer » — ça produirait des doublons
à chaque run. Il faut pouvoir répondre à « ces deux détections sont-elles la
même anomalie ? ». D'où `cle_metier` = "{move_ref}|{reference_cgi normalisée}",
et une réconciliation insert/update/désactivation côté application.

## Pourquoi un backfill 'legacy_' plutôt qu'un DELETE

Les alertes déjà en base n'ont pas de move_ref persisté (les colonnes de
contexte arrivent avec cette migration), donc on ne peut pas leur recalculer
une vraie clé. Leur donner 'legacy_<uuid>' les rend uniques et lisibles sans
rien détruire : elles seront naturellement remplacées par des lignes à vraie
clé au prochain audit forcé. Une migration qui supprime des données du client
pour se simplifier la vie est une migration qu'on ne peut pas rejouer en prod.

## Pourquoi les 6 colonnes de contexte

move_id / move_ref / partner_nom / date_piece / recommandation /
odoo_path_json existaient dans le finding produit par run_ai_rag_audit() mais
n'étaient jamais persistés — même bug que celui corrigé par la migration
c3e6a1b8d9f5 pour reference_cgi, et exactement au même endroit. Sur le chemin
de cache, FindingCard perdait donc les blocs « Écriture comptable auditée » et
« Recommandation ». Et le workflow de correction a besoin de move_id pour
savoir de quelle pièce Odoo il parle.

Aucune nouvelle table ici : pas de policy RLS à ajouter, alerte_risque a déjà
la sienne (migration 834f91da7e7e).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5a9c2d4f8b1'
down_revision: Union[str, Sequence[str], None] = 'd4f8a2c1e6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Identité stable + cycle de vie
    op.add_column('alerte_risque', sa.Column('cle_metier', sa.String(160), nullable=True))
    op.add_column(
        'alerte_risque',
        sa.Column('actif', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Contexte de l'écriture auditée
    op.add_column('alerte_risque', sa.Column('move_id', sa.Integer(), nullable=True))
    op.add_column('alerte_risque', sa.Column('move_ref', sa.String(120), nullable=True))
    op.add_column('alerte_risque', sa.Column('partner_nom', sa.String(200), nullable=True))
    op.add_column('alerte_risque', sa.Column('date_piece', sa.Date(), nullable=True))
    op.add_column('alerte_risque', sa.Column('recommandation', sa.Text(), nullable=True))
    op.add_column('alerte_risque', sa.Column('odoo_path_json', pg.JSONB(), nullable=True))

    # Backfill non destructif : les alertes existantes reçoivent une clé
    # unique dérivée de leur id, ce qui permet de poser l'index unique
    # ci-dessous sans supprimer une seule ligne.
    op.execute("UPDATE alerte_risque SET cle_metier = 'legacy_' || id::text WHERE cle_metier IS NULL")

    # C'est cet index qui rend la réconciliation applicative sûre : deux
    # alertes de même clé sur un même dossier deviennent impossibles, donc
    # le "une clé = une ligne" n'est pas qu'une convention de code.
    op.create_index('ux_alerte_cle_metier', 'alerte_risque', ['dossier_id', 'cle_metier'], unique=True)

    # server_default posé uniquement pour remplir les lignes existantes ;
    # une fois la table à jour, la valeur par défaut est portée par le modèle
    # SQLAlchemy (default=True), pas par la base.
    op.alter_column('alerte_risque', 'actif', server_default=None)


def downgrade() -> None:
    op.drop_index('ux_alerte_cle_metier', table_name='alerte_risque')
    op.drop_column('alerte_risque', 'odoo_path_json')
    op.drop_column('alerte_risque', 'recommandation')
    op.drop_column('alerte_risque', 'date_piece')
    op.drop_column('alerte_risque', 'partner_nom')
    op.drop_column('alerte_risque', 'move_ref')
    op.drop_column('alerte_risque', 'move_id')
    op.drop_column('alerte_risque', 'actif')
    op.drop_column('alerte_risque', 'cle_metier')
