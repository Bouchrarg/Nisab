"""add_proposition_correction

Revision ID: a7c1e4f6b0d3
Revises: e5a9c2d4f8b1
Create Date: 2026-08-05 11:00:00.000000

Workflow agentique de correction : l'IA propose une écriture sourcée, un humain
valide, amende ou rejette, et seule une proposition validée peut donner lieu à
un brouillon dans l'ERP.

## Deux tables, et pourquoi la seconde

`proposition_correction` porte la proposition et son cycle de vie.
`citation_proposition` porte les articles du CGI sur lesquels elle s'appuie.

Séparer les citations dans une table dédiée plutôt que de se contenter du
JSONB `references_json` suit le patron déjà en place pour `citation_risque` et
`citation_simulation` : une ligne horodatée et versionnée par article, pour
pouvoir répondre « sur quelle version du corpus cette affirmation reposait-elle
au moment où elle a été faite ». Le JSONB sert la lecture rapide, la table sert
la traçabilité — les deux ne remplissent pas le même office.

## L'index partiel ux_proposition_vivante

Au plus une proposition non rejetée par alerte. Sans lui, cliquer deux fois sur
« Proposer une correction » créerait deux propositions concurrentes sur la même
anomalie, chacune validable indépendamment — donc potentiellement deux écritures
poussées dans Odoo pour corriger une seule fois le même problème.

Les propositions rejetées sont exclues de la contrainte : elles restent en
historique (on veut pouvoir montrer qu'une piste a été examinée puis écartée,
et pourquoi) tout en laissant regénérer une nouvelle proposition.

## RLS

Écrite à la main : l'autogenerate d'Alembic ne produit JAMAIS les policies.
Une table tenant sans policy est lisible par tous les cabinets — le défaut le
plus grave possible dans ce produit, et le plus silencieux.

`proposition_correction` filtre sur `dossier_id` (colonne dénormalisée
exprès pour ça). `citation_proposition` n'a pas de dossier_id : elle filtre en
remontant par `proposition_id`, comme `citation_risque` le fait via `alerte_id`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c1e4f6b0d3'
down_revision: Union[str, Sequence[str], None] = 'e5a9c2d4f8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POLICY_PROPOSITION = """
CREATE POLICY tenant_isolation ON proposition_correction
USING (
    dossier_id IN (
        SELECT id FROM dossier
        WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
    )
)
WITH CHECK (
    dossier_id IN (
        SELECT id FROM dossier
        WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
    )
);
"""

_POLICY_CITATION = """
CREATE POLICY tenant_isolation ON citation_proposition
USING (
    proposition_id IN (
        SELECT p.id FROM proposition_correction p
        WHERE p.dossier_id IN (
            SELECT id FROM dossier
            WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
        )
    )
)
WITH CHECK (
    proposition_id IN (
        SELECT p.id FROM proposition_correction p
        WHERE p.dossier_id IN (
            SELECT id FROM dossier
            WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
        )
    )
);
"""


def upgrade() -> None:
    statut_proposition = sa.Enum(
        'en_attente', 'validee', 'rejetee', 'poussee', 'erreur', name='statut_proposition'
    )
    type_correction = sa.Enum(
        'ecriture_od', 'regularisation_tva', 'piece_a_reclamer', 'aucune_ecriture', name='type_correction'
    )

    op.create_table(
        'proposition_correction',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('dossier_id', pg.UUID(as_uuid=True), sa.ForeignKey('dossier.id'), nullable=False),
        # CASCADE : une alerte supprimee emporte ses propositions. Depuis la
        # migration e5a9c2d4f8b1 les alertes ne sont plus supprimees par l'audit
        # (elles sont desactivees), donc ce CASCADE ne se declenche que sur une
        # suppression volontaire de dossier.
        sa.Column('alerte_id', pg.UUID(as_uuid=True),
                  sa.ForeignKey('alerte_risque.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cle_metier', sa.String(160), nullable=False),
        sa.Column('statut', statut_proposition, nullable=False, server_default='en_attente'),
        sa.Column('type_correction', type_correction, nullable=False),
        sa.Column('resume', sa.String(300), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('payload_json', pg.JSONB(), nullable=False),
        sa.Column('references_json', pg.JSONB(), nullable=False),
        sa.Column('montant_impact', sa.Numeric(14, 2), nullable=True),
        sa.Column('genere_le', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('genere_par_modele', sa.String(60), nullable=True),
        sa.Column('critique_json', pg.JSONB(), nullable=True),
        sa.Column('amendee_le', sa.DateTime(timezone=True), nullable=True),
        sa.Column('amendee_par_id', pg.UUID(as_uuid=True), sa.ForeignKey('utilisateur.id'), nullable=True),
        sa.Column('payload_origine_json', pg.JSONB(), nullable=True),
        sa.Column('decide_le', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decide_par_id', pg.UUID(as_uuid=True), sa.ForeignKey('utilisateur.id'), nullable=True),
        sa.Column('motif_decision', sa.Text(), nullable=True),
        sa.Column('odoo_move_id', sa.Integer(), nullable=True),
        sa.Column('odoo_url', sa.String(500), nullable=True),
        sa.Column('pousse_le', sa.DateTime(timezone=True), nullable=True),
        sa.Column('erreur_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_proposition_dossier', 'proposition_correction', ['dossier_id'])
    op.create_index('ix_proposition_alerte', 'proposition_correction', ['alerte_id'])
    op.execute(
        "CREATE UNIQUE INDEX ux_proposition_vivante ON proposition_correction (alerte_id) "
        "WHERE statut <> 'rejetee'"
    )

    op.create_table(
        'citation_proposition',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('proposition_id', pg.UUID(as_uuid=True),
                  sa.ForeignKey('proposition_correction.id', ondelete='CASCADE'), nullable=False),
        sa.Column('article_reference', sa.String(100), nullable=False),
        sa.Column('version_corpus', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_citation_proposition', 'citation_proposition', ['proposition_id'])

    # ── RLS : jamais produite par l'autogenerate, toujours a la main ──────
    op.execute("ALTER TABLE proposition_correction ENABLE ROW LEVEL SECURITY")
    op.execute(_POLICY_PROPOSITION)
    op.execute("ALTER TABLE citation_proposition ENABLE ROW LEVEL SECURITY")
    op.execute(_POLICY_CITATION)

    # Le role applicatif n'est pas proprietaire des tables (c'est ce qui rend
    # la RLS effective, Postgres ne l'appliquant pas au proprietaire). Il faut
    # donc lui accorder explicitement les droits sur les nouvelles tables.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON proposition_correction TO nisab_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON citation_proposition TO nisab_app")


def downgrade() -> None:
    op.drop_table('citation_proposition')
    op.drop_index('ux_proposition_vivante', table_name='proposition_correction')
    op.drop_table('proposition_correction')
    op.execute("DROP TYPE IF EXISTS type_correction")
    op.execute("DROP TYPE IF EXISTS statut_proposition")
