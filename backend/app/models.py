"""
models.py — Modèles SQLAlchemy du schéma applicatif multi-tenant.

Toutes les tables métier portent, directement ou via dossier_id, un chemin
vers organisation_id — c'est cette colonne que filtrent les policies RLS.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
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
    interne = "interne"


class RoleUtilisateur(str, enum.Enum):
    collaborateur = "collaborateur"
    dirigeant_pme = "dirigeant_pme"
    admin_cabinet = "admin_cabinet"          # admin d'UN cabinet client (son organisation, ses dossiers)
    admin_plateforme = "admin_plateforme"    # équipe Nisab/IAAI : corpus fiscal, veille, supervision globale


class StatutInvitation(str, enum.Enum):
    en_attente = "en_attente"
    acceptee = "acceptee"
    revoquee = "revoquee"


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
    # Désactivation réversible (admin plateforme) plutôt qu'une suppression :
    # effective au prochain login/refresh (voir routes_auth.py), pas à
    # chaque requête — pas de vérification DB systématique pour rester
    # cohérent avec le design stateless de get_current_user (auth.py).
    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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

    # ── État du dernier audit ────────────────────────────────────────────
    # L'audit est un état DU DOSSIER, pas des alertes qu'il produit. Tant que
    # cet état était déduit des lignes `alerte_risque`, deux situations
    # radicalement différentes étaient indistinguables :
    #   - un dossier jamais audité              -> 0 ligne
    #   - un dossier audité, aucune anomalie    -> 0 ligne
    # D'où deux bugs réels, l'un visible et l'autre silencieux :
    #   1. l'écran d'audit affichait « Aucune anomalie détectée — bonne
    #      conformité » sur un dossier qui n'avait jamais été analysé ;
    #   2. le cache de _execute_audit (`existing and all(...)`) était vide,
    #      donc un dossier PARFAITEMENT conforme relançait un audit LLM
    #      complet à chaque consultation — le cas le moins coûteux à servir
    #      était devenu le plus cher.
    #
    #: NULL = jamais audité. Ce n'est pas « audité il y a longtemps ».
    dernier_audit_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Empreinte des données comptables + du millésime de corpus sur lesquels
    #: le dernier audit a tourné (cf. _hash_data). Sert à deux choses : servir
    #: le cache sans rappeler le LLM, et dire à l'utilisateur « les données ont
    #: changé depuis cette analyse » au lieu de relancer sans le prévenir.
    dernier_audit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

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


class Invitation(Base):
    """
    Invitation d'un nouveau membre dans une organisation.

    Pas de RLS ici, pour la même raison que Utilisateur/Organisation :
    POST /invitations/accept doit pouvoir retrouver une invitation par son
    token AVANT que la personne n'ait de compte (donc avant tout contexte
    tenant). La protection se fait au niveau applicatif : seules les routes
    réservées à admin_cabinet filtrent explicitement par organisation_id.
    """
    __tablename__ = "invitation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisation.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[RoleUtilisateur] = mapped_column(Enum(RoleUtilisateur, name="role_utilisateur",create_type=False,), nullable=False)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dossier.id"), nullable=True)
    niveau_droit: Mapped[NiveauDroit] = mapped_column(
        Enum(NiveauDroit, name="niveau_droit", create_type=False), default=NiveauDroit.ecriture
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    statut: Mapped[StatutInvitation] = mapped_column(
        Enum(StatutInvitation, name="statut_invitation",create_type=False,), default=StatutInvitation.en_attente
    )
    invite_par_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    """
    Une anomalie détectée sur une écriture comptable, rattachée à un article
    du CGI.

    ## cle_metier — pourquoi cette colonne existe

    L'audit RAG est ré-exécuté à chaque changement des données comptables. Avant
    cette colonne, chaque ré-exécution supprimait toutes les alertes du dossier
    et les recréait avec des `id` neufs : tout état porté par un humain (statut
    « traitée », proposition de correction validée) disparaissait silencieusement.

    `cle_metier` répond à la question « qu'est-ce qui fait que deux détections
    sont la même anomalie ? ». Réponse retenue : le couple **(écriture,
    fondement légal)**, soit `"{move_ref}|{reference_cgi normalisée}"` — par
    exemple `FACT-2026-002|article 193`. Tant que ce couple réapparaît d'un run
    à l'autre, la ligne est mise à jour au lieu d'être recréée, donc `id` et
    `statut` survivent.

    Limite assumée : `reference_cgi` est produite par le LLM (sous contrainte du
    garde-fou anti-hallucination de ai_auditor). Si un re-run retient l'article
    146 au lieu du 145 sur la même écriture, la clé change et l'alerte apparaît
    comme neuve. C'est voulu — si le fondement légal change, une correction
    validée sur l'ancien fondement n'est plus nécessairement valable, mieux vaut
    la re-proposer que reporter une validation sur une autre base juridique.

    ## actif — pourquoi on ne supprime plus

    Une anomalie qui n'est plus détectée passe `actif = False` au lieu d'être
    supprimée : l'historique reste consultable, et les propositions de correction
    qui la référencent ne se retrouvent pas orphelines. Tous les lecteurs
    (dashboard, liste d'alertes, simulation de contrôle) filtrent sur
    `actif == True`.

    ## Champs de contexte dupliqués depuis le finding

    move_id / move_ref / partner_nom / date_piece / recommandation /
    odoo_path_json ne sont pas décoratifs : sans eux, relire une alerte depuis
    la base (chemin de cache) perdait l'écriture auditée et la recommandation,
    que le frontend affiche. Et le workflow de correction ne peut pas relancer
    un audit complet juste pour retrouver de quelle écriture il s'agit.
    """

    __tablename__ = "alerte_risque"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    niveau_risque: Mapped[NiveauRisque] = mapped_column(Enum(NiveauRisque, name="niveau_risque"), nullable=False)
    montant_exposition: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: "calculable" | "calculable_hypothese" | "non_calculable" — cf.
    #: app.regles_montant.CategorieMontant. NULL = alerte antérieure au
    #: moteur de règles (aucune règle n'a encore tourné dessus), à distinguer
    #: de "non_calculable" (une règle a tourné et a explicitement dit
    #: qu'aucun montant ne pouvait être avancé). String plutôt qu'un type
    #: Postgres ENUM : ce domaine est encore jeune (5 règles), un ENUM figé
    #: coûterait une migration ALTER TYPE à chaque article ajouté.
    categorie_montant: Mapped[str | None] = mapped_column(String(30), nullable=True)
    #: Le calcul en toutes lettres (ex. "Amende Art. 193 CGI : 6% x 47 000,00
    #: DH = 2 820,00 DH.") — ce qu'un contrôleur DGI ou un comptable doit
    #: pouvoir vérifier de tête. Distinct de `recommandation` (l'action à
    #: mener) : ceci est la justification du CHIFFRE, pas de l'action.
    montant_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Rempli UNIQUEMENT si categorie_montant == "calculable_hypothese" :
    #: l'hypothèse sur laquelle repose le calcul (donnée extraite d'un texte
    #: plutôt qu'un champ garanti, ex. prix véhicule). Affiché au frontend
    #: pour que le montant ne soit jamais présenté comme un fait acquis.
    montant_hypothese: Mapped[str | None] = mapped_column(Text, nullable=True)
    statut: Mapped[StatutAlerte] = mapped_column(Enum(StatutAlerte, name="statut_alerte"), default=StatutAlerte.ouverte)
    hash_donnees: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_cgi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rag_sources_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: Confirmation humaine du statut du bénéficiaire au regard de la retenue
    #: à la source (Art. 15 bis / 45 bis) — uniquement pertinent quand
    #: reference_cgi == "article 151", cf. app.regles_montant.
    #: remuneration_tiers_non_declaree_art151. NULL = jamais demandé au
    #: comptable, à distinguer de False = "confirmé : ne s'applique pas"
    #: (un vrai résultat). Comme `statut`, JAMAIS écrasé par
    #: _appliquer_finding au ré-audit (routes_dossiers.py) — sinon le
    #: comptable devrait reconfirmer à chaque synchro comptable.
    retenue_source_confirmee: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Montant de retenue due, saisi par le comptable — la règle ne peut pas
    #: le déduire des données comptables (voir la docstring de la fonction
    #: ci-dessus). Même exemption que retenue_source_confirmee.
    retenue_montant_du: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # Identité stable de l'anomalie — unique par (dossier_id, cle_metier),
    # contrainte posée dans la migration e5a9c2d4f8b1.
    cle_metier: Mapped[str | None] = mapped_column(String(160), nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Contexte de l'écriture auditée, nécessaire au frontend et au workflow
    # de correction (move_id sert à retrouver la pièce dans Odoo).
    move_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    move_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    partner_nom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_piece: Mapped[date | None] = mapped_column(Date, nullable=True)
    recommandation: Mapped[str | None] = mapped_column(Text, nullable=True)
    odoo_path_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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
    """
    Signalement à un dossier qu'un article du corpus qu'il cite a évolué.

    ## Ce qui rend la veille « personnalisée »

    Un article n'est pas notifié à tous les dossiers, ni deviné par mots-clés
    sectoriels. Il est notifié aux dossiers qui **ont déjà cité cette
    référence** — via une alerte de risque, une réponse de l'assistant, une
    simulation de contrôle ou une proposition de correction.

    C'est déterministe, sans LLM, donc sans hallucination possible, et fondé
    sur l'historique réel du dossier plutôt que sur une supposition. Défendable
    en une phrase : *si ce cabinet a déjà eu besoin de l'article 106 sur ce
    dossier, un changement de l'article 106 le concerne.*

    ## source_label / document_id

    CGI et Bulletin Officiel sont deux couches distinctes du corpus (règle
    d'architecture). La notification doit dire d'où elle vient : lire une
    consolidation du CGI et lire une mesure nouvelle publiée au BO n'appellent
    pas la même réaction.
    """

    __tablename__ = "notification_veille"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    article_corpus_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    lu: Mapped[bool] = mapped_column(Boolean, default=False)

    niveau: Mapped[str] = mapped_column(String(20), nullable=False, default="moyen")
    #: Origine dans le corpus : "CGI 2026" vs "BO n° 7465 bis". Conserve la
    #: distinction entre texte consolidé et publication datée.
    source_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    date_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    #: Pourquoi CE dossier est concerné (ex. « cité dans 2 alerte(s) de risque »).
    #: La veille doit pouvoir se justifier, comme le reste du produit.
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)

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


class StatutProposition(str, enum.Enum):
    """
    Cycle de vie d'une proposition de correction.

    Cinq états, pas un de plus. En particulier :

    - pas d'état « brouillon » : la génération est synchrone, si le LLM échoue
      ou si un garde-fou refuse la sortie, RIEN n'est persisté. Une proposition
      qui existe est une proposition valide.
    - pas d'état « amendée » : amender, c'est éditer le payload d'une
      proposition restée `en_attente`. La traçabilité est portée par
      amendee_le / amendee_par_id / payload_origine_json, pas par un état.
      Moins d'états à expliquer, même information conservée.
    """
    en_attente = "en_attente"
    validee = "validee"
    rejetee = "rejetee"
    poussee = "poussee"
    erreur = "erreur"


class TypeCorrection(str, enum.Enum):
    """
    Nature de la correction proposée.

    Le point de conception le plus important du workflow : **beaucoup
    d'anomalies fiscales ne se corrigent pas par une écriture comptable**.
    Un fournisseur sans ICE, une facture sans mentions obligatoires, un
    paiement en espèces déjà effectué : aucune écriture d'OD ne répare ça.

    Si le prompt forçait le LLM à produire une écriture dans tous les cas, il
    en inventerait une — et une écriture inventée pour un problème qu'elle ne
    résout pas est pire qu'une absence de proposition, parce qu'elle a l'air
    d'une réponse.

    Les deux derniers types portent donc `lignes: []` et ne peuvent jamais
    être poussés dans Odoo (refus explicite côté route et bouton désactivé).
    """
    ecriture_od = "ecriture_od"                  # écriture d'opérations diverses
    regularisation_tva = "regularisation_tva"    # idem, sur comptes de TVA
    piece_a_reclamer = "piece_a_reclamer"        # action documentaire, pas comptable
    aucune_ecriture = "aucune_ecriture"          # fait acquis : provisionner / régulariser en déclaratif


class PropositionCorrection(Base):
    """
    Correction proposée par l'IA pour une alerte, soumise à validation humaine.

    ## L'invariant central

    Une PropositionCorrection n'existe en base que si elle est rattachée à au
    moins une CitationProposition. C'est la règle produit du projet
    (« zéro affirmation sans source ») appliquée à l'endroit où elle est le
    plus facile à casser par inadvertance : ici l'IA ne se contente pas de
    commenter, elle propose une écriture comptable.

    Les références retenues sont en outre **filtrées contre celles de
    l'alerte** : le générateur ne fait aucune nouvelle recherche RAG, il ne
    peut donc citer que ce sur quoi l'alerte était déjà fondée. Pas de dérive
    de sources entre le constat et le remède.

    ## Pourquoi dossier_id est dénormalisé

    L'information est déductible via alerte_id -> alerte_risque.dossier_id.
    Elle est dupliquée quand même parce que c'est la colonne sur laquelle porte
    la policy RLS : une policy qui devrait faire une jointure serait plus lente
    et surtout plus facile à écrire de travers. La colonne qui protège les
    données du client doit être la plus simple possible à relire.
    """

    __tablename__ = "proposition_correction"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False, index=True)
    alerte_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerte_risque.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Copie figée de alerte_risque.cle_metier au moment de la génération.
    #: Permet de retrouver à quoi la proposition se rapportait même si l'alerte
    #: a changé de fondement légal entre-temps (cf. docstring d'AlerteRisque).
    cle_metier: Mapped[str] = mapped_column(String(160), nullable=False)

    statut: Mapped[StatutProposition] = mapped_column(
        Enum(StatutProposition, name="statut_proposition"), nullable=False, default=StatutProposition.en_attente
    )
    type_correction: Mapped[TypeCorrection] = mapped_column(
        Enum(TypeCorrection, name="type_correction"), nullable=False
    )

    resume: Mapped[str] = mapped_column(String(300), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    #: {"lignes": [{"compte","libelle","debit","credit"}], "action": str|None,
    #:  "date_ecriture": "YYYY-MM-DD", "journal": str|None}
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: Références CGI retenues APRÈS filtrage contre celles de l'alerte.
    references_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    #: Copié TEL QUEL depuis alerte_risque.montant_exposition au moment de la
    #: génération — jamais recalculé, jamais redemandé au LLM. correction_agent
    #: ne fait "aucune nouvelle recherche RAG" (cf. sa docstring) ; le même
    #: principe s'applique au montant, qui n'est pas non plus un nouveau calcul.
    montant_impact: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: Copiés depuis l'alerte au même titre que montant_impact — voir
    #: AlerteRisque.categorie_montant / montant_detail / montant_hypothese.
    categorie_montant: Mapped[str | None] = mapped_column(String(30), nullable=True)
    montant_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    montant_hypothese: Mapped[str | None] = mapped_column(Text, nullable=True)

    genere_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    genere_par_modele: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: Trace de la passe d'auto-critique : le motif retenu si le premier jet a
    #: été jugé incohérent et régénéré. Sert à montrer que la boucle a tourné.
    critique_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    amendee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amendee_par_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    #: Payload tel que l'IA l'avait produit, conservé dès le premier amendement.
    #: Sans lui, on ne saurait plus dire ce qui vient de la machine et ce qui
    #: vient de l'humain — exactement la question qu'un contrôleur poserait.
    payload_origine_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    decide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decide_par_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    motif_decision: Mapped[str | None] = mapped_column(Text, nullable=True)

    odoo_move_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odoo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pousse_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erreur_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CitationProposition(Base):
    """
    Article du corpus cité par une proposition de correction.

    Même forme que CitationRisque et CitationSimulation — c'est le patron du
    projet : toute sortie IA persistée a sa table de citations horodatée,
    versionnée par `version_corpus`. Uniformité voulue, pour qu'on puisse
    répondre « d'où vient cette affirmation » de la même façon partout.
    """

    __tablename__ = "citation_proposition"

    id: Mapped[uuid.UUID] = _uuid_pk()
    proposition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proposition_correction.id", ondelete="CASCADE"), nullable=False, index=True
    )
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


class JournalAcces(Base):
    """
    Journal des accès aux données personnelles/comptables — exigence CNDP
    (loi 09-08, cf. cahier-des-charges.md : "confidentialité et hébergement
    conformes"). Table créée par la migration initiale (834f91da7e7e) mais
    restée sans classe ORM jusqu'ici : le schéma existait, rien ne l'écrivait
    ni ne le lisait.

    `utilisateur_id` et `organisation_id` sont NULLABLE : une tentative
    d'accès sans jeton valide (ou avant résolution du tenant) doit pouvoir
    être journalisée quand même — voir app/journal_acces.py.

    Volontairement SANS policy RLS, comme `utilisateur`/`organisation` (même
    raison) : `organisation_id` nullable rendrait une policy RLS classique
    inapplicable aux lignes pré-résolution de tenant, et seules les routes
    déjà gated `admin_plateforme` (app/admin.py) la lisent — protection au
    niveau applicatif, pas au niveau base.
    """

    __tablename__ = "journal_acces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateur.id"), nullable=True)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organisation.id"), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
