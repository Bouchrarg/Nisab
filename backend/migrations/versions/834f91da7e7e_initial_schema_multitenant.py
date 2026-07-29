"""initial_schema_multitenant

Revision ID: 834f91da7e7e
Revises:
Create Date: 2026-07-28 19:34:55.858964

Crée le schéma applicatif multi-tenant (organisation, utilisateur, dossier,
et toutes les tables métier liées), puis active Row-Level Security sur
chaque table avec une policy basée sur app.current_org_id (voir
app/db_session.py::set_tenant_context).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '834f91da7e7e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "organisation",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("nom", sa.String(200), nullable=False),
        sa.Column("type_organisation", sa.Enum("cabinet", "pme", name="type_organisation"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "utilisateur",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", pg.UUID(as_uuid=True), sa.ForeignKey("organisation.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("nom_complet", sa.String(200), server_default=""),
        sa.Column(
            "role",
            sa.Enum("collaborateur", "dirigeant_pme", "admin_cabinet", name="role_utilisateur"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_utilisateur_email", "utilisateur", ["email"])
    op.create_index("ix_utilisateur_organisation_id", "utilisateur", ["organisation_id"])

    op.create_table(
        "dossier",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", pg.UUID(as_uuid=True), sa.ForeignKey("organisation.id"), nullable=False),
        sa.Column("raison_sociale", sa.String(255), nullable=False),
        sa.Column("secteur_activite", sa.String(150), server_default=""),
        sa.Column("regime_is", sa.String(50), server_default="normal"),
        sa.Column("regime_tva", sa.String(50), server_default="mensuel"),
        sa.Column("exercice_cloture_mois", sa.Integer, server_default="12"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dossier_organisation_id", "dossier", ["organisation_id"])

    op.create_table(
        "acces",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("utilisateur_id", pg.UUID(as_uuid=True), sa.ForeignKey("utilisateur.id"), nullable=False),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column(
            "niveau_droit",
            sa.Enum("lecture", "ecriture", "admin", name="niveau_droit"),
            server_default="lecture",
        ),
    )

    op.create_table(
        "connexion_comptable",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("type", sa.Enum("odoo", "sage", "csv", "ocr", name="type_connexion"), nullable=False),
        sa.Column("identifiants_chiffres", sa.Text, nullable=True),
        sa.Column("derniere_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_connexion_comptable_dossier_id", "connexion_comptable", ["dossier_id"])

    op.create_table(
        "piece_comptable",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("type_piece", sa.String(50), server_default="facture"),
        sa.Column("donnees_json", pg.JSONB, nullable=False),
        sa.Column("date_piece", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_piece_comptable_dossier_id", "piece_comptable", ["dossier_id"])

    op.create_table(
        "declaration",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("type_declaration", sa.String(50), nullable=False),
        sa.Column("periode", sa.String(20), nullable=False),
        sa.Column("statut", sa.String(30), server_default="a_faire"),
        sa.Column("date_echeance", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_declaration_dossier_id", "declaration", ["dossier_id"])

    op.create_table(
        "alerte_risque",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("titre", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("niveau_risque", sa.Enum("faible", "moyen", "eleve", name="niveau_risque"), nullable=False),
        sa.Column("montant_exposition", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "statut",
            sa.Enum("ouverte", "traitee", "ignoree", name="statut_alerte"),
            server_default="ouverte",
        ),
        sa.Column("hash_donnees", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alerte_risque_dossier_id", "alerte_risque", ["dossier_id"])

    op.create_table(
        "simulation_controle",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("rapport_json", pg.JSONB, nullable=False),
        sa.Column("plan_remediation_json", pg.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_simulation_controle_dossier_id", "simulation_controle", ["dossier_id"])

    op.create_table(
        "echeance",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("date_limite", sa.DateTime(timezone=True), nullable=False),
        sa.Column("statut", sa.String(30), server_default="a_venir"),
    )
    op.create_index("ix_echeance_dossier_id", "echeance", ["dossier_id"])

    op.create_table(
        "notification_veille",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("article_corpus_reference", sa.String(100), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("lu", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_veille_dossier_id", "notification_veille", ["dossier_id"])

    op.create_table(
        "citation",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("dossier_id", pg.UUID(as_uuid=True), sa.ForeignKey("dossier.id"), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("reponse", sa.Text, nullable=False),
        sa.Column("article_reference", sa.String(100), nullable=False),
        sa.Column("version_corpus", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_citation_dossier_id", "citation", ["dossier_id"])

    op.create_table(
        "citation_risque",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("alerte_id", pg.UUID(as_uuid=True), sa.ForeignKey("alerte_risque.id"), nullable=False),
        sa.Column("article_reference", sa.String(100), nullable=False),
        sa.Column("version_corpus", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_citation_risque_alerte_id", "citation_risque", ["alerte_id"])

    op.create_table(
        "citation_simulation",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("simulation_id", pg.UUID(as_uuid=True), sa.ForeignKey("simulation_controle.id"), nullable=False),
        sa.Column("article_reference", sa.String(100), nullable=False),
        sa.Column("version_corpus", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_citation_simulation_simulation_id", "citation_simulation", ["simulation_id"])

    op.create_table(
        "journal_acces",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("utilisateur_id", pg.UUID(as_uuid=True), sa.ForeignKey("utilisateur.id"), nullable=True),
        sa.Column("organisation_id", pg.UUID(as_uuid=True), sa.ForeignKey("organisation.id"), nullable=True),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ─────────────────────────────────────────────────────────────────────
    # Row-Level Security : isolation stricte par organisation.
    #
    # IMPORTANT : `utilisateur` et `organisation` sont volontairement EXCLUES
    # de la RLS. Raison : le login doit pouvoir chercher un utilisateur par
    # email AVANT de connaître son organisation (c'est justement ce que le
    # login détermine) — une RLS filtrée par app.current_org_id bloquerait
    # cette recherche puisque le contexte tenant n'existe pas encore à ce
    # stade. Ces deux tables "identité" restent protégées au niveau
    # applicatif : app/routes_auth.py ne retourne jamais que la ligne de
    # l'utilisateur authentifié, et aucune route métier ne les expose en
    # liste brute. La RLS s'applique strictement à partir de `dossier` et
    # toutes les tables qui en dépendent, qui contiennent les données
    # sensibles (comptables, fiscales) à isoler.
    # ─────────────────────────────────────────────────────────────────────

    op.execute("ALTER TABLE dossier ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON dossier
        USING (organisation_id = current_setting('app.current_org_id', true)::uuid)
        WITH CHECK (organisation_id = current_setting('app.current_org_id', true)::uuid)
    """)

    via_dossier_tables = [
        "connexion_comptable",
        "piece_comptable",
        "declaration",
        "alerte_risque",
        "simulation_controle",
        "echeance",
        "notification_veille",
        "citation",
    ]
    for table in via_dossier_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
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
            )
        """)

    op.execute("ALTER TABLE citation_risque ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON citation_risque
        USING (
            alerte_id IN (
                SELECT id FROM alerte_risque WHERE dossier_id IN (
                    SELECT id FROM dossier
                    WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
                )
            )
        )
    """)

    op.execute("ALTER TABLE citation_simulation ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON citation_simulation
        USING (
            simulation_id IN (
                SELECT id FROM simulation_controle WHERE dossier_id IN (
                    SELECT id FROM dossier
                    WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
                )
            )
        )
    """)

    op.execute("ALTER TABLE acces ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON acces
        USING (
            dossier_id IN (
                SELECT id FROM dossier
                WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
            )
        )
    """)

    # journal_acces : pas de RLS ici — écritures/lectures système gérées en Phase 7.

    # ─────────────────────────────────────────────────────────────────────
    # ATTENTION (à vérifier manuellement après le déploiement) :
    # la RLS Postgres est ignorée par tout rôle superuser ou possédant
    # l'attribut BYPASSRLS. Le rôle par défaut d'une connexion Supabase
    # (souvent `postgres`) a ce comportement. Pour que ces policies aient
    # un effet réel, DATABASE_URL doit pointer vers un rôle applicatif
    # dédié, créé sans BYPASSRLS, par exemple :
    #
    #   CREATE ROLE nisab_app LOGIN PASSWORD '...';
    #   GRANT ALL ON ALL TABLES IN SCHEMA public TO nisab_app;
    #   ALTER ROLE nisab_app NOBYPASSRLS;
    #
    # Sans cette étape, le code applicatif (set_tenant_context) s'exécute
    # correctement mais les policies ne filtrent rien : c'est un point de
    # contrôle à valider explicitement en Phase 1/2, pas juste un détail.
    # ─────────────────────────────────────────────────────────────────────


def downgrade() -> None:
    for table in [
        "citation_simulation",
        "citation_risque",
        "citation",
        "notification_veille",
        "echeance",
        "simulation_controle",
        "alerte_risque",
        "declaration",
        "piece_comptable",
        "connexion_comptable",
        "acces",
        "journal_acces",
        "dossier",
        "utilisateur",
        "organisation",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    for enum_name in [
        "type_organisation",
        "role_utilisateur",
        "niveau_droit",
        "type_connexion",
        "niveau_risque",
        "statut_alerte",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
