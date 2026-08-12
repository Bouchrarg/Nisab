"""add_invitation_table

Revision ID: 689bf7bc8aaf
Revises: 95e0d7d9338b
Create Date: 2026-07-29 05:27:54.320993

Ajoute la table invitation (flux "admin_cabinet invite un collègue").
Pas de RLS : la route publique /invitations/accept doit pouvoir retrouver
une invitation par son token avant même qu'un contexte tenant existe —
même logique que pour utilisateur/organisation (voir migration 834f91da7e7e).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '689bf7bc8aaf'
down_revision: Union[str, Sequence[str], None] = '95e0d7d9338b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


role_enum = pg.ENUM(
    "collaborateur",
    "dirigeant_pme",
    "admin_cabinet",
    "admin_plateforme",
    name="role_utilisateur",
    create_type=False,
)

statut_enum = pg.ENUM(
    "en_attente",
    "acceptee",
    "revoquee",
    name="statut_invitation",
)


def upgrade():

    op.create_table(
        "invitation",

        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),

        sa.Column(
            "organisation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organisation.id"),
            nullable=False,
        ),

        sa.Column("email", sa.String(255), nullable=False),

        sa.Column(
            "role",
            role_enum,
            nullable=False,
        ),

        sa.Column(
            "dossier_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("dossier.id"),
        ),

        sa.Column("token", sa.String(64), nullable=False, unique=True),

        sa.Column(
            "statut",
            statut_enum,
            nullable=False,
            server_default="en_attente",
        ),

        sa.Column(
            "invite_par_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("utilisateur.id"),
        ),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_invitation_organisation_id", "invitation", ["organisation_id"])
    op.create_index("ix_invitation_email", "invitation", ["email"])
    op.create_index("ix_invitation_token", "invitation", ["token"], unique=True)