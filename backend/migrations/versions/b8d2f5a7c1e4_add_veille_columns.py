"""add_veille_columns

Revision ID: b8d2f5a7c1e4
Revises: a7c1e4f6b0d3
Create Date: 2026-08-05 13:00:00.000000

Veille personnalisee : relier chaque article nouvellement valide du corpus aux
dossiers reellement concernes.

## Aucune nouvelle table, donc aucune nouvelle policy RLS

`notification_veille` existe depuis la Phase 1 avec sa policy (migration
834f91da7e7e) et n'avait jamais ete alimentee. On l'enrichit plutot que d'en
creer une autre.

## Pourquoi source_label et document_id

Ce ne sont pas des colonnes decoratives. L'architecture du projet pose que le CGI (texte legal
consolide) et le Bulletin Officiel (provenance temporelle, declencheur de
veille) sont deux couches DISTINCTES du corpus, a ne jamais fusionner. Une
notification doit donc pouvoir dire si elle vient d'une consolidation du CGI ou
d'un BO date — sinon le cabinet ne peut pas savoir s'il lit une reformulation
ou une mesure nouvelle.

## L'index unique

Idempotence de la diffusion. Sans lui, relancer le pipeline de veille
renotifierait tous les dossiers pour les memes articles, et la pastille de
non-lus deviendrait du bruit que personne ne regarde.

COALESCE(date_version, '') parce qu'un index unique sur une colonne NULL ne
contraint rien en Postgres : deux lignes avec date_version NULL seraient
considerees distinctes, et le doublon passerait.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d2f5a7c1e4'
down_revision: Union[str, Sequence[str], None] = 'a7c1e4f6b0d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notification_veille',
                  sa.Column('niveau', sa.String(20), nullable=False, server_default='moyen'))
    op.add_column('notification_veille', sa.Column('source_label', sa.String(200), nullable=True))
    op.add_column('notification_veille', sa.Column('document_id', sa.String(60), nullable=True))
    op.add_column('notification_veille', sa.Column('date_version', sa.String(30), nullable=True))
    op.add_column('notification_veille', sa.Column('motif', sa.Text(), nullable=True))

    op.execute(
        "CREATE UNIQUE INDEX ux_veille_unique ON notification_veille "
        "(dossier_id, article_corpus_reference, COALESCE(date_version, ''))"
    )


def downgrade() -> None:
    op.drop_index('ux_veille_unique', table_name='notification_veille')
    op.drop_column('notification_veille', 'motif')
    op.drop_column('notification_veille', 'date_version')
    op.drop_column('notification_veille', 'document_id')
    op.drop_column('notification_veille', 'source_label')
    op.drop_column('notification_veille', 'niveau')
