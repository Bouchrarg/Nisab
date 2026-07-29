"""
models.py — Modèles SQLAlchemy du schéma applicatif multi-tenant.

Reprend directement le MCD/MLD du rapport de conception (section 10) :
ORGANISATION -> DOSSIER -> {PIECE_COMPTABLE, DECLARATION, ALERTE_RISQUE,
SIMULATION_CONTROLE, ECHEANCE, CONNEXION_COMPTABLE, NOTIFICATION_VEILLE},
+ ACCES (jonction utilisateur/dossier) et les tables de traçabilité des
citations (CITATION / CITATION_RISQUE / CITATION_SIMULATION).

Toutes les tables métier portent, directement ou via dossier_id, un chemin
vers organisation_id — c'est cette colonne que filtrent les policies RLS.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TypeOrganisation(str, enum.Enum):
    cabinet = "cabinet"
    pme = "pme"


class RoleUtilisateur(str, enum.Enum):
    collaborateur = "collaborateur"
    dirigeant_pme = "dirigeant_pme"
    admin_cabinet = "admin_cabinet"


class NiveauDroit(str, enum.Enum):
    lecture = "lecture"
    ecriture = "ecriture"
    admin = "admin"


class NiveauRisque(str, enum.Enum):
    faible = "faible"
    moyen = "moyen"
    eleve = "eleve"


class StatutAlerte(str, enum.Enum):
    ouverte = "ouverte"
    traitee = "traitee"
    ignoree = "ignoree"


class TypeConnexion(str, enum.Enum):
    odoo = "odoo"
    sage = "sage"
    csv = "csv"
    ocr = "ocr"


# ─────────────────────────────────────────────────────────────────────────
# Organisation / utilisateurs / dossiers
# ─────────────────────────────────────────────────────────────────────────

class Organisation(Base):
    __tablename__ = "organisation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    type_organisation: Mapped[TypeOrganisation] = mapped_column(
        Enum(TypeOrganisation, name="type_organisation"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    utilisateurs: Mapped[list["Utilisateur"]] = relationship(back_populates="organisation")
    dossiers: Mapped[list["Dossier"]] = relationship(back_populates="organisation")


class Utilisateur(Base):
    __tablename__ = "utilisateur"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisation.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nom_complet: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[RoleUtilisateur] = mapped_column(Enum(RoleUtilisateur, name="role_utilisateur"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organisation: Mapped["Organisation"] = relationship(back_populates="utilisateurs")
    acces: Mapped[list["Acces"]] = relationship(back_populates="utilisateur")


class Dossier(Base):
    __tablename__ = "dossier"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisation.id"), nullable=False, index=True)
    raison_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    secteur_activite: Mapped[str] = mapped_column(String(150), default="")
    regime_is: Mapped[str] = mapped_column(String(50), default="normal")
    regime_tva: Mapped[str] = mapped_column(String(50), default="mensuel")
    exercice_cloture_mois: Mapped[int] = mapped_column(default=12)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organisation: Mapped["Organisation"] = relationship(back_populates="dossiers")
    acces: Mapped[list["Acces"]] = relationship(back_populates="dossier")


class Acces(Base):
    __tablename__ = "acces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"), nullable=False)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False)
    niveau_droit: Mapped[NiveauDroit] = mapped_column(Enum(NiveauDroit, name="niveau_droit"), default=NiveauDroit.lecture)

    utilisateur: Mapped["Utilisateur"] = relationship(back_populates="acces")
    dossier: Mapped["Dossier"] = relationship(back_populates="acces")


# ─────────────────────────────────────────────────────────────────────────
# Ingestion / données comptables
# ─────────────────────────────────────────────────────────────────────────

class ConnexionComptable(Base):
    __tablename__ = "connexion_comptable"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    type: Mapped[TypeConnexion] = mapped_column(Enum(TypeConnexion, name="type_connexion"), nullable=False)
    identifiants_chiffres: Mapped[str | None] = mapped_column(Text, nullable=True)
    derniere_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PieceComptable(Base):
    __tablename__ = "piece_comptable"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # odoo | csv | ocr
    type_piece: Mapped[str] = mapped_column(String(50), default="facture")
    donnees_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    date_piece: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Declaration(Base):
    __tablename__ = "declaration"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    type_declaration: Mapped[str] = mapped_column(String(50), nullable=False)
    periode: Mapped[str] = mapped_column(String(20), nullable=False)
    statut: Mapped[str] = mapped_column(String(30), default="a_faire")
    date_echeance: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─────────────────────────────────────────────────────────────────────────
# Risques / contrôle / échéances
# ─────────────────────────────────────────────────────────────────────────

class AlerteRisque(Base):
    __tablename__ = "alerte_risque"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    niveau_risque: Mapped[NiveauRisque] = mapped_column(Enum(NiveauRisque, name="niveau_risque"), nullable=False)
    montant_exposition: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    statut: Mapped[StatutAlerte] = mapped_column(Enum(StatutAlerte, name="statut_alerte"), default=StatutAlerte.ouverte)
    hash_donnees: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SimulationControle(Base):
    __tablename__ = "simulation_controle"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    rapport_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    plan_remediation_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Echeance(Base):
    __tablename__ = "echeance"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    date_limite: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    statut: Mapped[str] = mapped_column(String(30), default="a_venir")


class NotificationVeille(Base):
    __tablename__ = "notification_veille"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    article_corpus_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    lu: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ─────────────────────────────────────────────────────────────────────────
# Traçabilité des citations (cœur anti-hallucination, persisté)
# ─────────────────────────────────────────────────────────────────────────

class Citation(Base):
    """Citation attachée à une réponse de l'assistant fiscal sourcé."""
    __tablename__ = "citation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reponse: Mapped[str] = mapped_column(Text, nullable=False)
    article_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    version_corpus: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CitationRisque(Base):
    """Citation attachée à une alerte de risque."""
    __tablename__ = "citation_risque"

    id: Mapped[uuid.UUID] = _uuid_pk()
    alerte_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerte_risque.id"), nullable=False, index=True)
    article_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    version_corpus: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CitationSimulation(Base):
    """Citation attachée à une simulation de contrôle."""
    __tablename__ = "citation_simulation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    simulation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("simulation_controle.id"), nullable=False, index=True)
    article_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    version_corpus: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
