"""add_dossier_etat_audit

Revision ID: c9e1b3d6f204
Revises: a9c3e7f1b4d2
Create Date: 2026-08-11 10:00:00.000000

Etat du dernier audit porte par le dossier (dernier_audit_le,
dernier_audit_hash) au lieu d'etre deduit des lignes alerte_risque.

## Le probleme corrige

L'audit ne se relance plus automatiquement : il est LU depuis la base a
l'ouverture d'un dossier et n'est RECALCULE que sur clic explicite. Il fallait
donc pouvoir repondre a « cet audit a-t-il deja tourne, et quand ? ».

Tant que la reponse etait deduite des lignes `alerte_risque`, deux situations
opposees etaient indistinguables — toutes deux donnent zero ligne :
  - un dossier jamais audite
  - un dossier audite dont aucune anomalie n'est ressortie

D'ou deux bugs, dont un silencieux :
  1. l'ecran d'audit affichait « Aucune anomalie detectee — le dossier presente
     une bonne conformite » sur un dossier jamais analyse. Une affirmation de
     conformite produite sans qu'aucune verification n'ait eu lieu, dans un
     produit dont la promesse est de ne rien affirmer sans fondement.
  2. la condition de cache de _execute_audit (`existing and all(...)`) etait
     fausse sur une liste vide : un dossier parfaitement conforme relançait un
     audit LLM complet a CHAQUE consultation. Le cas le moins couteux a servir
     etait devenu le plus cher, et personne ne pouvait le voir puisque le
     resultat affiche etait identique.

`created_at` d'alerte_risque ne pouvait pas non plus servir de date : depuis
`cle_metier` (migration e5a9c2d4f8b1), une alerte qui persiste d'un run a
l'autre est mise a JOUR et non recreee, donc `created_at` reste fige a la
premiere detection.

## Nullable, sans backfill

NULL = jamais audite. Backfiller avec `now()` affirmerait qu'un audit vient de
tourner (faux) ; backfiller avec `created_at` du dossier affirmerait qu'il a
ete audite a sa creation (faux aussi). Les dossiers existants repassent donc
par « jamais analyse » et un clic — cout : un audit, une fois. C'est le prix
correct pour ne pas inventer une date. Meme logique que `categorie_montant` :
l'absence de mesure ne se maquille pas en mesure.

## Pas de policy RLS a ajouter

Ce sont deux colonnes sur `dossier`, table deja couverte par la policy
`USING (organisation_id = current_setting('app.current_org_id', true)::uuid)`
posee par 834f91da7e7e. Une colonne n'a pas de policy propre.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e1b3d6f204'
down_revision: Union[str, Sequence[str], None] = 'a9c3e7f1b4d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dossier',
        sa.Column('dernier_audit_le', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'dossier',
        sa.Column('dernier_audit_hash', sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('dossier', 'dernier_audit_hash')
    op.drop_column('dossier', 'dernier_audit_le')
