"""
routes_dossiers.py — Endpoints scindés par dossier (tenant), tous authentifiés.

Remplace l'ancien state global de api.py (_odoo_session, _odoo_data,
CACHE_FILE, _audit_cache) par une persistance réelle en base, filtrée par
Row-Level Security via get_tenant_db (voir app/db_session.py).

Chaque route prend dossier_id en paramètre de chemin et vérifie, via la
requête SQLAlchemy elle-même (RLS), que ce dossier appartient bien à
l'organisation de l'utilisateur connecté — si ce n'est pas le cas, le
`.get()`/`.scalar_one_or_none()` ne retourne simplement rien (404), jamais
les données d'un autre tenant.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_auditor import _normalize_ref, run_ai_rag_audit
from app.api import get_vectorstore
from app.auth import CurrentUser, get_current_user, require_role
from app.db_session import get_tenant_db, set_tenant_context
from app.detection_reglee import detecter
from app.generation import generate_answer
from app.intention import choisir_format_reponse, classifier_intention, repondre_echeance
from app.langue import detecter_langue
from app.models import (
    Acces,
    AlerteRisque,
    Citation,
    CitationRisque,
    ConnexionComptable,
    Dossier,
    Echeance,
    NiveauRisque,
    PieceComptable,
    StatutAlerte,
    TypeConnexion,
)
from app.odoo_connector import OdooConnector, get_demo_data
from app.rag_retrieval import retrieve_sourced_articles
from app.regles_montant import remuneration_tiers_non_declaree_art151
from app.roi import exposition_findings
from app.secrets_store import chiffrer
from app.tax_calendar import get_calendar_events
from app.tenant_guard import get_dossier_or_404
from app.text_cleaning import clean_article_text

router = APIRouter(prefix="/dossiers", tags=["Dossiers"])

# Verrou process-local pour éviter de relancer l'audit LLM en double sur
# deux requêtes concurrentes pour le même dossier (l'invalidation, elle,
# est désormais portée par hash_donnees en base, plus par une variable
# globale).
_audit_locks: dict[str, threading.Lock] = {}


def _lock_for(dossier_id: str) -> threading.Lock:
    return _audit_locks.setdefault(dossier_id, threading.Lock())


def _hash_data(data: dict, document_id: str | None = None) -> str:
    # `document_id` entre dans le hash de cache : sans ça, relancer le même
    # audit avec une source de corpus différente (voir /audit/run) servirait
    # les anciennes alertes depuis le cache au lieu de rappeler le RAG.
    payload = {"data": data, "document_id": document_id}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ── schémas ──────────────────────────────────────────────────────────────

class DossierCreateRequest(BaseModel):
    raison_sociale: str
    secteur_activite: str = ""
    regime_is: str = "normal"
    regime_tva: str = "mensuel"
    exercice_cloture_mois: int = 12


class DossierResponse(BaseModel):
    id: str
    raison_sociale: str
    secteur_activite: str
    regime_is: str
    regime_tva: str


class OdooConnectRequest(BaseModel):
    url: str
    db: str
    username: str
    password: str
    #: Conserver les identifiants (chiffrés) pour pouvoir pousser plus tard un
    #: brouillon de correction dans Odoo. Opt-in explicite : on ne stocke pas
    #: le mot de passe de la comptabilité d'un client sans qu'il l'ait demandé.
    memoriser: bool = False


class AlerteStatutRequest(BaseModel):
    statut: str  # ouverte | traitee | ignoree (validé contre StatutAlerte côté route)


class RetenueSourceRequest(BaseModel):
    #: Confirmation du comptable : ce tiers relève-t-il d'un régime de
    #: retenue à la source (Art. 15 bis / 45 bis) ? Obligatoire — c'est tout
    #: le sens de l'appel, contrairement à montant_du qui n'a de sens que si
    #: applicable=True.
    applicable: bool
    #: Montant de retenue due, en DH. Requis si applicable=True (la règle
    #: renvoie sinon 0 DH même sur "oui", cf. regles_montant.py) ; ignoré si
    #: applicable=False.
    montant_du: float | None = None


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    top_k: int = Field(5, ge=1, le=15)
    context_data: Optional[dict] = None
    active_view: Optional[str] = None
    #: 'fr' | 'ar' | 'ar_latin'. Laisse a None, la langue est detectee sur la
    #: question elle-meme : un dirigeant qui ecrit en darija n'a rien a regler.
    langue: Optional[str] = None


# ── CRUD dossier (Module 7 — Espaces & multi-tenant) ─────────────────────

@router.post("", response_model=DossierResponse, status_code=201)
def create_dossier(
    req: DossierCreateRequest,
    # Créer un dossier = agrandir le périmètre du cabinet (nouveau client) :
    # décision structurante réservée à admin_cabinet, pas à un collaborateur
    # scopé par Acces à des dossiers déjà existants.
    user: CurrentUser = Depends(require_role("admin_cabinet")),
    db: Session = Depends(get_tenant_db),
):
    dossier = Dossier(
        id=uuid.uuid4(),
        organisation_id=uuid.UUID(user.organisation_id),
        raison_sociale=req.raison_sociale,
        secteur_activite=req.secteur_activite,
        regime_is=req.regime_is,
        regime_tva=req.regime_tva,
        exercice_cloture_mois=req.exercice_cloture_mois,
    )
    db.add(dossier)
    db.commit()
    return DossierResponse(
        id=str(dossier.id),
        raison_sociale=dossier.raison_sociale,
        secteur_activite=dossier.secteur_activite,
        regime_is=dossier.regime_is,
        regime_tva=dossier.regime_tva,
    )


@router.get("", response_model=list[DossierResponse])
def list_dossiers(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    # La RLS filtre déjà par organisation, mais ça suffit seulement pour
    # admin_cabinet/admin_plateforme (accès à tout le cabinet). Un
    # collaborateur/dirigeant_pme ne doit voir que les dossiers où il a une
    # entrée Acces — sinon il verrait tous les dossiers du cabinet.
    if user.role in ("admin_cabinet", "admin_plateforme"):
        dossiers = db.execute(select(Dossier)).scalars().all()
    else:
        dossiers = db.execute(
            select(Dossier).join(Acces, Acces.dossier_id == Dossier.id).where(Acces.utilisateur_id == uuid.UUID(user.id))
        ).scalars().all()
    return [
        DossierResponse(
            id=str(d.id),
            raison_sociale=d.raison_sociale,
            secteur_activite=d.secteur_activite,
            regime_is=d.regime_is,
            regime_tva=d.regime_tva,
        )
        for d in dossiers
    ]


class DossierRenameRequest(BaseModel):
    raison_sociale: str


@router.patch("/{dossier_id}", response_model=DossierResponse)
def rename_dossier(dossier_id: uuid.UUID, req: DossierRenameRequest, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """
    Utilisé notamment pour aligner automatiquement le nom du dossier sur le
    nom de l'entreprise réellement détecté après une connexion Odoo/démo
    (voir odoo_connect/odoo_demo côté frontend) — évite qu'un dossier créé
    avec un nom provisoire (ex. le nom de la base Odoo) reste durablement
    désynchronisé du nom d'entreprise affiché dans le tableau de bord.
    """
    dossier = get_dossier_or_404(db, dossier_id, user, min_niveau="admin")
    dossier.raison_sociale = req.raison_sociale
    db.commit()
    return DossierResponse(
        id=str(dossier.id),
        raison_sociale=dossier.raison_sociale,
        secteur_activite=dossier.secteur_activite,
        regime_is=dossier.regime_is,
        regime_tva=dossier.regime_tva,
    )


# ── Ingestion Odoo (remplace le state global) ────────────────────────────

@router.post("/{dossier_id}/odoo/connect")
def odoo_connect(dossier_id: uuid.UUID, req: OdooConnectRequest, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    get_dossier_or_404(db, dossier_id, user, min_niveau="admin")
    try:
        connector = OdooConnector(req.url, req.db, req.username, req.password)
        connector.authenticate()
        data = connector.fetch_accounting_data()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Connexion Odoo échouée : {exc}")

    _persist_accounting_data(db, dossier_id, source="odoo", data=data, connexion_type=TypeConnexion.odoo)

    memorise = False
    if req.memoriser:
        # Le chiffrement peut être indisponible (NISAB_SECRET_KEY absente) sans
        # que ça doive faire échouer la synchronisation : les données sont déjà
        # chargées et utiles. On le dit dans la réponse plutôt que de lever.
        try:
            connexion = db.execute(
                select(ConnexionComptable).where(
                    ConnexionComptable.dossier_id == dossier_id,
                    ConnexionComptable.type == TypeConnexion.odoo,
                )
            ).scalars().first()
            if connexion is not None:
                connexion.identifiants_chiffres = chiffrer({
                    "url": req.url, "db": req.db,
                    "username": req.username, "password": req.password,
                })
                db.commit()
                memorise = True
        except RuntimeError as exc:
            print(f"[odoo] mémorisation des identifiants impossible pour {dossier_id} : {exc}")

    return {
        "status": "connected",
        "company": data.get("company", {}).get("name", "Inconnu"),
        "nb_moves": len(data.get("moves", [])),
        "nb_partners": len(data.get("partners", [])),
        "identifiants_memorises": memorise,
    }


@router.post("/{dossier_id}/odoo/demo")
def odoo_demo(dossier_id: uuid.UUID, scenario: str = "commerce", user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """
    Charge des données de démonstration simulées pour ce dossier (sans
    instance Odoo réelle). `scenario` : commerce (défaut) / conforme /
    services — cf. odoo_connector.DEMO_SCENARIOS. Une valeur inconnue
    retombe sur "commerce".
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="admin")
    data = get_demo_data(scenario)
    _persist_accounting_data(db, dossier_id, source="demo", data=data, connexion_type=TypeConnexion.odoo)
    return {
        "status": "demo_loaded",
        "company": data["company"]["name"],
        "nb_moves": len(data["moves"]),
        "nb_partners": len(data["partners"]),
    }


@router.get("/{dossier_id}/odoo/status")
def odoo_status(dossier_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    get_dossier_or_404(db, dossier_id, user)
    data = _get_active_accounting_data(db, dossier_id)
    if data:
        return {"connected": True, "company": data.get("company", {}).get("name", "Odoo")}
    return {"connected": False}


def _persist_accounting_data(db: Session, dossier_id: uuid.UUID, source: str, data: dict, connexion_type: TypeConnexion) -> None:
    """
    Remplace _save_cache() : écrit les données comptables en base plutôt que
    dans une variable globale + fichier temporaire. Une seule PieceComptable
    "snapshot" par dossier pour l'instant (le détail pièce-par-pièce arrive
    en Phase 5 avec la réconciliation) — suffisant pour rebrancher les
    modules d'audit/dashboard/calendrier existants sans les réécrire.
    """
    db.query(PieceComptable).filter(
        PieceComptable.dossier_id == dossier_id, PieceComptable.type_piece == "snapshot_comptable"
    ).delete()

    db.add(PieceComptable(
        id=uuid.uuid4(),
        dossier_id=dossier_id,
        source=source,
        type_piece="snapshot_comptable",
        donnees_json=data,
        date_piece=datetime.now(timezone.utc),
    ))

    connexion = db.execute(
        select(ConnexionComptable).where(ConnexionComptable.dossier_id == dossier_id, ConnexionComptable.type == connexion_type)
    ).scalar_one_or_none()
    if connexion is None:
        connexion = ConnexionComptable(id=uuid.uuid4(), dossier_id=dossier_id, type=connexion_type)
        db.add(connexion)
    connexion.derniere_sync = datetime.now(timezone.utc)

    db.commit()


def _get_active_accounting_data(db: Session, dossier_id: uuid.UUID) -> dict | None:
    """Remplace _get_active_odoo_data()."""
    piece = db.execute(
        select(PieceComptable)
        .where(PieceComptable.dossier_id == dossier_id, PieceComptable.type_piece == "snapshot_comptable")
        .order_by(PieceComptable.created_at.desc())
    ).scalars().first()
    return piece.donnees_json if piece else None


def _fusionner_donnees_comptables(existant: dict | None, nouveau: dict) -> dict:
    """
    Fusionne un nouvel import de fichier dans le snapshot déjà actif du
    dossier, au lieu de l'écraser — utilisé par `importer_fichier`
    (routes_ingestion.py), PAS par la synchro Odoo ni le mode démo.

    Différence volontaire entre les deux : Odoo est une source de vérité
    live (une écriture supprimée côté Odoo doit disparaître au resync, donc
    `odoo/connect` et `odoo/demo` continuent de tout remplacer), alors qu'un
    export CSV représente presque toujours une PÉRIODE (le grand livre de
    janvier, puis celui de février) — le cas d'usage réel d'un cabinet est
    d'accumuler, pas de remplacer un mois par le suivant.

    Indexation par `move["id"]`, déterministe (hash du n° de pièce, voir
    fichier_connecteur._identifiant_stable) : une pièce déjà connue est
    REMPLACÉE — réimporter le même n° de pièce corrige cette pièce, ça ne la
    duplique pas — une pièce absente du nouveau fichier reste intacte.

    Limite assumée : si un mauvais import contient des pièces aux numéros
    inédits (pas de collision avec l'existant), elles s'ajoutent et restent
    en base — il n'existe pas encore de suppression pièce par pièce. Pour
    repartir d'un état propre après une erreur, il faut recharger une
    connexion Odoo ou un scénario démo (qui remplacent tout), pas réimporter
    un fichier.
    """
    if not existant:
        return nouveau

    moves_par_id = {m["id"]: m for m in existant.get("moves", [])}
    for m in nouveau.get("moves", []):
        moves_par_id[m["id"]] = m

    # Les lignes d'une pièce réimportée remplacent les anciennes plutôt que
    # de s'accumuler à côté : sinon un montant corrigé garderait l'ancien en
    # double dans l'audit, silencieusement.
    ids_touches = {m["id"] for m in nouveau.get("moves", [])}
    lignes = [l for l in existant.get("lines", []) if l["move_id"][0] not in ids_touches]
    lignes += nouveau.get("lines", [])

    partenaires_par_id = {p["id"]: p for p in existant.get("partners", [])}
    for p in nouveau.get("partners", []):
        partenaires_par_id[p["id"]] = p

    return {
        "company": nouveau.get("company") or existant.get("company"),
        # `company_id` doit SURVIVRE à une fusion. Un fichier CSV n'en porte
        # jamais (il n'a aucune notion de société Odoo) : le reconstruire sans
        # cette clé effaçait la société cible mémorisée lors de la connexion
        # Odoo, et le push de brouillon perdait silencieusement sa destination
        # — sur une base multi-sociétés, écrire dans la mauvaise société est
        # exactement ce que detect_company_id() existe pour éviter.
        "company_id": nouveau.get("company_id") or existant.get("company_id"),
        "partners": list(partenaires_par_id.values()),
        "moves": sorted(moves_par_id.values(), key=lambda m: m["date"], reverse=True),
        "lines": lignes,
        "source": nouveau.get("source", existant.get("source")),
    }


# ── Audit / risques (Module 3) ───────────────────────────────────────────

# Ordre de gravité, sert à départager deux findings qui retombent sur la même
# clé métier (même écriture, même article) — on garde le plus grave.
_SEVERITY_RANK = {"vert": 0, "orange": 1, "rouge": 2}


def _est_chiffre(f: dict) -> bool:
    return f.get("categorie_montant") != "non_calculable" and (f.get("amount_risk") or 0) > 0


def _remplace(candidat: dict, precedent: dict) -> bool:
    """
    Entre deux findings qui décrivent la même anomalie (même écriture, même
    article), lequel garde-t-on ?

    Le montant tranche AVANT la gravité. Depuis que la détection réglée
    (`detection_reglee`) tourne à côté du RAG, une même clé métier peut
    recevoir deux descriptions du même fait : celle du LLM, éventuellement
    sans montant chiffrable, et celle de la règle déterministe, avec le
    calcul en toutes lettres. Trancher par la gravité seule reviendrait à
    laisser un "rouge" sans chiffre écraser un "orange" chiffré — soit
    exactement le symptôme qu'on cherche à corriger, réintroduit par la
    porte de derrière.

    À égalité de chiffrage, on retombe sur la règle d'origine : le plus grave
    gagne.
    """
    if _est_chiffre(candidat) != _est_chiffre(precedent):
        return _est_chiffre(candidat)
    return _SEVERITY_RANK.get(candidat.get("severity"), 0) > _SEVERITY_RANK.get(precedent.get("severity"), 0)


def _cle_metier(f: dict) -> str:
    """
    Identité stable d'une anomalie : le couple (écriture, fondement légal).

    Voir la docstring d'AlerteRisque (models.py) pour le raisonnement complet.
    En deux mots : l'audit est ré-exécuté à chaque changement de données, et
    sans cette clé on ne peut pas savoir si une anomalie détectée aujourd'hui
    est celle qu'un humain a déjà traitée hier.

    On préfère `invoice` (le n° de pièce, ex. "FACT-2026-002") à move_id :
    il est lisible en base, et surtout il est stable à travers les sources —
    un même exercice réimporté en CSV après avoir été lu depuis Odoo garde ses
    numéros de pièce, pas ses identifiants techniques.
    """
    odoo_path = f.get("odoo_path") or {}
    piece = f.get("invoice") or odoo_path.get("move_id") or "sans_piece"
    ref = _normalize_ref(f.get("reference_cgi") or "sans_reference")
    return f"{piece}|{ref}"[:160]


def _parse_date_piece(valeur) -> date | None:
    """Odoo renvoie les dates en 'YYYY-MM-DD' ; un CSV peut renvoyer autre chose."""
    if isinstance(valeur, date):
        return valeur
    if not valeur:
        return None
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


def _appliquer_finding(alerte: AlerteRisque, f: dict, new_hash: str) -> None:
    """
    Recopie un finding sur une ligne AlerteRisque (nouvelle ou existante).

    Ne touche volontairement NI `id` NI `statut` : ce sont les deux champs
    porteurs de décision humaine, et toute la raison d'être de la clé métier
    est qu'ils survivent au ré-audit.
    """
    odoo_path = f.get("odoo_path") or {}
    alerte.titre = f.get("title", "Anomalie détectée")
    alerte.description = f.get("description", "")
    alerte.niveau_risque = {
        "rouge": NiveauRisque.eleve,
        "orange": NiveauRisque.moyen,
    }.get(f.get("severity"), NiveauRisque.faible)
    alerte.montant_exposition = f.get("amount_risk")
    # cf. app.regles_montant : le montant n'est plus jamais produit par le
    # LLM, ces trois champs viennent d'une règle déterministe (ou disent
    # explicitement qu'aucune règle ne s'applique). "calculable"/
    # "calculable_hypothese"/"non_calculable" — jamais None sur une alerte
    # fraîche, sauf finding pré-migration relu depuis un ancien cache.
    alerte.categorie_montant = f.get("categorie_montant")
    alerte.montant_detail = f.get("montant_detail")
    alerte.montant_hypothese = f.get("montant_hypothese")
    alerte.hash_donnees = new_hash
    alerte.reference_cgi = f.get("reference_cgi")
    alerte.rag_sources_json = f.get("rag_sources") or []
    alerte.actif = True

    alerte.move_id = odoo_path.get("move_id")
    alerte.move_ref = f.get("invoice")
    alerte.partner_nom = f.get("partner")
    alerte.date_piece = _parse_date_piece(f.get("date"))
    alerte.recommandation = f.get("recommendation")
    alerte.odoo_path_json = odoo_path or None

    # Art. 151 : le RAG (ai_auditor.calculer_montant_regle) appelle
    # toujours remuneration_tiers_non_declaree_art151(None, None, None) —
    # il n'a jamais accès à la base, donc jamais à une confirmation
    # comptable. Si le comptable a déjà répondu (retenue_source_confirmee
    # non NULL, saisi via /alertes/{id}/retenue-source), on recalcule ici
    # le montant avec sa réponse plutôt que de garder le "non_calculable"
    # par défaut que _appliquer_finding vient d'écrire ci-dessus. Comme
    # `statut`, cette réponse survit au ré-audit — recalculée à chaque
    # fois, jamais écrasée.
    if _normalize_ref(alerte.reference_cgi or "") == "article 151" and alerte.retenue_source_confirmee is not None:
        montant_retenue = float(alerte.retenue_montant_du) if alerte.retenue_montant_du is not None else None
        resultat = remuneration_tiers_non_declaree_art151(alerte.retenue_source_confirmee, montant_retenue, None)
        alerte.montant_exposition = resultat.montant
        alerte.categorie_montant = resultat.categorie.value
        alerte.montant_detail = resultat.detail
        alerte.montant_hypothese = resultat.hypothese


def _reecrire_citations(db: Session, alerte: AlerteRisque, version_corpus: str) -> None:
    """
    Une CitationRisque par article distinct cité (reference_cgi + rag_sources).

    Ces lignes sont des données *dérivées* de l'alerte, pas de l'état porté par
    un humain : on peut donc les supprimer/recréer sans rien perdre, y compris
    sur une alerte mise à jour. C'est la même exigence anti-hallucination que
    pour le chat (voir generation.py / Citation) : toute alerte affichée doit
    pouvoir être remontée à un article vérifiable du corpus versionné.

    `version_corpus` est calculé UNE fois par run d'audit (voir
    `_execute_audit`), pas par citation : toutes les citations d'un même run
    proviennent du même filtre `document_id`, donc de la même source.
    """
    db.query(CitationRisque).filter(CitationRisque.alerte_id == alerte.id).delete(synchronize_session=False)

    refs = set(alerte.rag_sources_json or [])
    if alerte.reference_cgi:
        refs.add(alerte.reference_cgi)
    for ref in refs:
        if not ref:
            continue
        db.add(CitationRisque(
            id=uuid.uuid4(),
            alerte_id=alerte.id,
            article_reference=ref,
            version_corpus=version_corpus,
        ))


def _versions_corpus(db: Session, alertes: list[AlerteRisque]) -> dict[uuid.UUID, str]:
    """
    Millésime du corpus ayant produit chaque alerte, en UNE requête pour tout
    le lot.

    L'information vit sur `CitationRisque.version_corpus` et non sur l'alerte
    (voir `_reecrire_citations`), donc la lire alerte par alerte ferait un
    SELECT par carte affichée. Toutes les citations d'une même alerte portent
    la même valeur — elles sont écrites en un seul run, depuis le même filtre
    `document_id` — d'où le `dict` sans agrégation : n'importe laquelle des
    lignes répond pour l'alerte entière.

    Absente du dict = alerte sans citation portant de version (alerte
    antérieure à ce champ). Le frontend doit alors n'afficher aucun millésime
    plutôt que d'en supposer un.
    """
    ids = [a.id for a in alertes if a.id]
    if not ids:
        return {}
    rows = db.execute(
        select(CitationRisque.alerte_id, CitationRisque.version_corpus).where(
            CitationRisque.alerte_id.in_(ids),
            CitationRisque.version_corpus.is_not(None),
        )
    ).all()
    return {alerte_id: version for alerte_id, version in rows}


def _lire_audit_persiste(
    db: Session, dossier_id: uuid.UUID, data: dict | None = None, document_id: str | None = None,
) -> dict:
    """
    LIT le dernier audit depuis la base. Ne calcule JAMAIS, n'appelle aucun LLM.

    ## Pourquoi cette fonction existe séparément de _execute_audit

    Les deux opérations « afficher le dernier audit » et « lancer un audit »
    passaient par la même fonction, distinguées seulement par un cache interne.
    N'importe quelle LECTURE pouvait donc devenir un CALCUL de plusieurs
    minutes dès que le cache manquait — et `GET /dashboard/summary`, un simple
    GET appelé au montage de trois écrans différents, en était le principal
    déclencheur. Le pire cas était silencieux : `_hash_data` inclut
    `document_id`, mais `dashboard_summary` appelait toujours avec
    `document_id=None`, donc dès qu'un millésime était sélectionné dans l'UI le
    hash ne correspondait jamais et l'audit complet repartait à chaque appel.

    Séparer les deux chemins rend la confusion impossible par construction :
    ici on ne peut pas calculer, il n'y a pas de branche qui le permette.
    `_execute_audit` reste le seul point d'entrée qui appelle le LLM, et il
    n'est atteignable que par POST /audit/run.

    `data` est optionnel : sans lui on ne peut pas dire si le résultat est
    encore d'actualité (`resultat_perime` reste None = « on ne sait pas »,
    jamais False qui affirmerait à tort que le résultat est à jour).

    `resultat_perime` plutôt que « données modifiées » : le hash couvre le
    couple (données comptables, millésime de corpus). Changer de millésime
    dans l'UI périme tout autant le résultat affiché que réimporter un CSV,
    mais ce n'est pas « les données ont changé ». Le champ dit ce qu'il mesure.
    """
    dossier = db.get(Dossier, dossier_id)

    # L'état de l'audit est porté par le DOSSIER, pas déduit du nombre
    # d'alertes : « jamais audité » et « audité, zéro anomalie » donnent tous
    # deux zéro ligne dans alerte_risque (cf. migration c9e1b3d6f204).
    if dossier is None or dossier.dernier_audit_le is None:
        return {
            "findings": [],
            "nb_anomalies": 0,
            "audit_status": "jamais_lance",
            "date_dernier_audit": None,
            "resultat_perime": None,
        }

    actives = db.execute(
        select(AlerteRisque).where(
            AlerteRisque.dossier_id == dossier_id,
            AlerteRisque.actif.is_(True),
        )
    ).scalars().all()
    versions = _versions_corpus(db, actives)

    resultat_perime = None
    if data is not None:
        resultat_perime = dossier.dernier_audit_hash != _hash_data(data, document_id)

    return {
        "findings": [_alerte_to_dict(a, versions.get(a.id)) for a in actives],
        "nb_anomalies": len(actives),
        "audit_status": "done",
        "date_dernier_audit": dossier.dernier_audit_le.isoformat(),
        "resultat_perime": resultat_perime,
    }


def _execute_audit(
    db: Session, dossier_id: uuid.UUID, data: dict, organisation_id: uuid.UUID | str,
    force: bool = False, document_id: str | None = None,
) -> tuple[list[dict], list[str], list[dict]]:
    """
    Remplace le cache en mémoire (_audit_cache) par un cache en base, clé
    sur hash_donnees : si les données comptables n'ont pas changé depuis
    la dernière exécution, on relit les alertes déjà stockées plutôt que
    de rappeler le LLM.

    Retourne (findings, technical_failures, inconclusive). Sur le chemin de
    cache, technical_failures et inconclusive sont toujours vides : on ne
    persiste pas ces infos en base (pas de changement de schéma), le run
    précédent les a déjà signalées au moment où il a tourné.

    ## Réconciliation plutôt que delete-all

    Ce code supprimait auparavant toutes les alertes du dossier avant de les
    recréer. C'était destructeur : `statut` (traitée/ignorée) et toute donnée
    humaine accrochée à alerte_risque.id disparaissaient à chaque synchro
    comptable. Se contenter de « ne plus supprimer » aurait produit des
    doublons à chaque run — il fallait pouvoir dire quand deux détections sont
    la même anomalie, d'où _cle_metier().

    Trois cas, et un seul est destructif :
      - clé présente avant ET après  -> UPDATE (id et statut préservés)
      - clé nouvelle                 -> INSERT
      - clé disparue                 -> actif = False, PAS de DELETE

    La désactivation plutôt que la suppression garde l'historique lisible et
    évite de laisser orphelines les propositions de correction qui référencent
    l'alerte.
    """
    new_hash = _hash_data(data, document_id)

    with _lock_for(str(dossier_id)):
        dossier = db.get(Dossier, dossier_id)

        # Cache porté par le dossier et non par les alertes. L'ancienne
        # condition (`existing and all(a.hash_donnees == new_hash)`) était
        # fausse sur une liste vide : un dossier audité SANS anomalie n'a
        # aucune ligne, donc son cache ne pouvait jamais être servi et il
        # relançait un audit LLM complet à chaque appel — le cas le moins
        # coûteux à servir était devenu le plus cher (cf. c9e1b3d6f204).
        if not force and dossier is not None and dossier.dernier_audit_hash == new_hash:
            lu = _lire_audit_persiste(db, dossier_id)
            return lu["findings"], [], []

        # CORRECTIF (architecture) : la détection de risques est RAG-only —
        # règle d'architecture du projet. L'ancien fallback vers compliance_checker.run_audit()
        # (moteur à seuils codés en dur, retirée) violait cette règle en
        # silence : ses findings portaient des reference_cgi non vérifiés
        # contre le corpus versionné et aucun rag_sources, donc aucune
        # CitationRisque n'était jamais créée pour eux — une alerte
        # "sourcée" qui ne l'était en fait pas, à l'exact endroit du produit
        # où l'anti-hallucination est censée être non négociable. Si le RAG
        # ne peut pas tourner, on le dit clairement plutôt que de dégrader
        # silencieusement vers un résultat qui a l'air identique mais ne
        # l'est pas.
        has_llm = bool(os.environ.get("GROQ_API_KEY") or os.environ.get("OPENROUTER_KEY"))
        if not has_llm:
            raise RuntimeError(
                "Audit RAG indisponible : aucune clé LLM configurée "
                "(GROQ_API_KEY / OPENROUTER_KEY absentes de l'environnement)."
            )

        # CORRECTIF (pool de connexions) : run_ai_rag_audit ne touche jamais
        # `db` (recherche RAG + appels LLM uniquement) mais peut prendre
        # plusieurs minutes — LLM_CALL_DELAY_SECONDS entre chaque écriture,
        # plus la latence Groq réelle, plus une éventuelle passe de retry.
        # Avant ce correctif, la connexion `get_tenant_db` restait verrouillée
        # sans rien en faire pendant tout ce temps : 1-2 audits qui tournent
        # en même temps suffisaient à épuiser le pool SQLAlchemy (5 +
        # overflow 10) et à faire échouer des routes sans rapport (vu en
        # pratique sur /auth/refresh, TimeoutError QueuePool). On rend la
        # connexion au pool pendant le run, elle ne sert à rien ici.
        db.close()
        try:
            findings, technical_failures, inconclusive = run_ai_rag_audit(data, document_id=document_id)
        except Exception as exc:
            raise RuntimeError(f"Audit RAG IA en échec technique : {exc}") from exc

        # Détection réglée, en COMPLÉMENT du RAG et jamais à sa place (voir
        # detection_reglee.py pour le raisonnement complet). Le RAG désigne un
        # seul article par écriture, choisi par un LLM : une facture réglée en
        # espèces peut donc repartir avec l'Art. 146 (mentions de facture,
        # jamais chiffrable) et laisser l'Art. 11-II — chiffrable, arithmétique
        # — non détecté. Ces règles-là n'ont besoin d'aucun jugement : leurs
        # conditions se lisent dans les données comptables.
        #
        # Les deux séries sont simplement concaténées : `cle_metier` vaut
        # "{pièce}|{article}", donc une alerte RAG et une alerte réglée sur la
        # même pièce mais deux articles différents coexistent sans se marcher
        # dessus, et la déduplication ci-dessous (_remplace) tranche le cas où
        # elles visent le MÊME article.
        try:
            findings = findings + detecter(data)
        except Exception as exc:
            raise RuntimeError(f"Détection réglée en échec technique : {exc}") from exc

        # `db.close()` a clos la transaction où vivait set_config(...,
        # true) (portée transaction, pas session — voir db_session.py) : il
        # faut reposer le contexte RLS sur la connexion fraîchement reprise
        # avant la moindre requête, sinon les policies RLS n'ont plus de
        # tenant courant.
        set_tenant_context(db, str(organisation_id))

        # Un seul lookup pour tout le run : toutes les citations qui en
        # sortent viennent du même filtre `document_id`, donc de la même
        # source. Non contraint (document_id=None) -> libellé honnête plutôt
        # que de prétendre une version précise qu'on ne peut pas garantir
        # (le RAG a pu piocher dans n'importe quel millésime valide).
        if document_id:
            version_corpus = get_vectorstore().get_document_label(document_id) or document_id
        else:
            version_corpus = "Corpus (toutes sources valides)"

        # ── Réconciliation par clé métier ────────────────────────────────
        # Déduplication d'abord : deux findings peuvent viser la même écriture
        # avec le même article (le LLM audite pièce par pièce et peut se
        # répéter). L'index unique (dossier_id, cle_metier) l'interdit en base,
        # donc on tranche ici plutôt que de laisser péter une IntegrityError :
        # on garde le plus grave.
        incoming: dict[str, dict] = {}
        for f in findings:
            cle = _cle_metier(f)
            precedent = incoming.get(cle)
            if precedent is None or _remplace(f, precedent):
                incoming[cle] = f

        # Tout ce qui avait été lu avant le db.close() ci-dessus (le `dossier`
        # du test de cache) est détaché de la session fermée : attributs encore
        # lisibles en mémoire, mais pas ré-attachables proprement à un commit.
        # On recharge plutôt que de réattacher à la main — la requête est bon
        # marché et `_lock_for(dossier_id)` garantit qu'aucun autre run sur ce
        # dossier n'a pu s'intercaler entre les deux lectures.
        dossier = db.get(Dossier, dossier_id)
        existing = db.execute(
            select(AlerteRisque).where(AlerteRisque.dossier_id == dossier_id)
        ).scalars().all()
        connues = {a.cle_metier: a for a in existing if a.cle_metier}

        alertes_actives: list[AlerteRisque] = []
        for cle, f in incoming.items():
            alerte = connues.get(cle)
            if alerte is None:
                alerte = AlerteRisque(
                    id=uuid.uuid4(),
                    dossier_id=dossier_id,
                    cle_metier=cle,
                    statut=StatutAlerte.ouverte,
                    niveau_risque=NiveauRisque.faible,  # écrasé par _appliquer_finding
                )
                db.add(alerte)
            _appliquer_finding(alerte, f, new_hash)
            db.flush()  # garantit alerte.id avant d'écrire les CitationRisque
            _reecrire_citations(db, alerte, version_corpus)
            alertes_actives.append(alerte)

        # Anomalies qui ne sont plus détectées : désactivées, jamais supprimées.
        # On leur repose le hash courant pour que `hash_donnees` reste cohérent
        # d'une ligne à l'autre (le cache, lui, est désormais porté par le
        # dossier — voir juste en dessous).
        for cle, alerte in connues.items():
            if cle not in incoming:
                alerte.actif = False
                alerte.hash_donnees = new_hash

        # Trace du run sur le dossier lui-même. C'est ce qui permet ensuite de
        # LIRE cet audit sans le recalculer (_lire_audit_persiste) et de
        # distinguer « jamais audité » de « audité, zéro anomalie » — deux
        # situations qui produisent toutes deux zéro ligne d'alerte.
        # Écrit dans la même transaction que les alertes : un audit à moitié
        # enregistré qui se déclarerait quand même « fait » serait pire que pas
        # d'audit du tout.
        if dossier is not None:
            dossier.dernier_audit_le = datetime.now(timezone.utc)
            dossier.dernier_audit_hash = new_hash

        db.commit()

        # `version_corpus` est déjà en main pour ce run : inutile de relire les
        # CitationRisque qu'on vient d'écrire (_versions_corpus rendrait
        # exactement cette valeur).
        return (
            [_alerte_to_dict(a, version_corpus) for a in alertes_actives],
            technical_failures,
            inconclusive,
        )


def _alerte_to_dict(a: AlerteRisque, version_corpus: str | None = None) -> dict:
    """
    Forme unique d'un finding renvoyé au frontend — utilisée à la fois sur le
    chemin de cache et sur le chemin d'audit frais.

    Avant, le chemin frais renvoyait le dict du LLM et le chemin de cache une
    version reconstruite depuis la base qui perdait invoice / partner / date /
    recommendation / odoo_path : le même écran affichait donc plus ou moins
    d'informations selon qu'on venait de relancer l'audit ou non. Passer les
    deux chemins par cette fonction rend cette divergence impossible par
    construction.
    """
    severity = {"eleve": "rouge", "moyen": "orange", "faible": "vert"}[a.niveau_risque.value]
    return {
        "id": str(a.id),
        "cle_metier": a.cle_metier,
        "title": a.titre,
        "description": a.description,
        "severity": severity,
        "statut": a.statut.value,
        "amount_risk": float(a.montant_exposition) if a.montant_exposition is not None else 0,
        # cf. app.regles_montant : categorie_montant distingue "0 DH vérifié"
        # de "non calculable, ne rien affirmer" — les deux ont amount_risk=0
        # une fois passés par _alerte_to_dict, seul ce champ les différencie
        # côté frontend. None = alerte antérieure au moteur de règles.
        "categorie_montant": a.categorie_montant,
        "montant_detail": a.montant_detail,
        "montant_hypothese": a.montant_hypothese,
        "reference_cgi": a.reference_cgi,
        "rag_sources": a.rag_sources_json or [],
        # Millésime du corpus contre lequel CETTE alerte a été produite (ex.
        # "Code General des Impots 2024 (version 2024-01-01)", ou "Corpus
        # (toutes sources valides)" si l'audit n'a pas été contraint). None =
        # alerte sans citation versionnée : le frontend n'affiche alors aucune
        # source plutôt que d'en supposer une — c'est exactement le bug que ce
        # champ corrige, CitationPills annonçait "CGI 2026" en dur quel que
        # soit le document réellement audité.
        "version_corpus": version_corpus,
        # Uniquement significatif quand reference_cgi == "article 151" (cf.
        # remuneration_tiers_non_declaree_art151) : None = jamais demandé au
        # comptable, le frontend n'affiche le formulaire de confirmation que
        # dans ce cas précis.
        "retenue_source_confirmee": a.retenue_source_confirmee,
        "retenue_montant_du": float(a.retenue_montant_du) if a.retenue_montant_du is not None else None,
        "invoice": a.move_ref,
        "partner": a.partner_nom,
        "date": a.date_piece.isoformat() if a.date_piece else None,
        "recommendation": a.recommandation,
        "odoo_path": a.odoo_path_json,
    }


@router.get("/{dossier_id}/audit/resultat")
def audit_resultat(
    dossier_id: uuid.UUID,
    document_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Dernier audit enregistré, LU depuis la base. Ne lance jamais d'analyse.

    C'est le pendant en lecture de POST /audit/run, et la raison d'être de la
    séparation : ouvrir un dossier, changer de dossier ou afficher le tableau
    de bord ne doivent plus jamais déclencher plusieurs minutes de calcul LLM
    à l'insu de l'utilisateur. Niveau d'accès « lecture » (contre « ecriture »
    pour /audit/run) : consulter un résultat déjà produit n'est pas produire
    un résultat.

    `document_id` ne filtre rien ici — il ne sert qu'à calculer
    `resultat_perime` contre le même millésime que celui sélectionné dans
    l'UI, sinon changer de source ferait croire à tort que les données
    comptables ont bougé.
    """
    get_dossier_or_404(db, dossier_id, user)
    data = _get_active_accounting_data(db, dossier_id)
    return _lire_audit_persiste(db, dossier_id, data, document_id)


@router.post("/{dossier_id}/audit/run")
def audit_run(
    dossier_id: uuid.UUID,
    force: bool = False,
    document_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    `document_id` (optionnel) contraint l'audit à un seul document du corpus
    (ex: "cgi_2024") au lieu de laisser le RAG piocher sans distinction parmi
    tous les millésimes valides — cf. GET /corpus/sources pour la liste des
    valeurs possibles.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")
    data = _get_active_accounting_data(db, dossier_id)
    if data is None:
        raise HTTPException(status_code=400, detail="Aucune donnée comptable chargée pour ce dossier. Appelez /odoo/connect ou /odoo/demo d'abord.")
    try:
        findings, technical_failures, inconclusive = _execute_audit(
            db, dossier_id, data, user.organisation_id, force=force, document_id=document_id
        )
        return {
            "nb_anomalies": len(findings),
            "findings": findings,
            "technical_failures": technical_failures,
            "inconclusive": inconclusive,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Dashboard (résumé par dossier) ────────────────────────────────────────

@router.get("/{dossier_id}/dashboard/summary")
def dashboard_summary(dossier_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    get_dossier_or_404(db, dossier_id, user)
    data = _get_active_accounting_data(db, dossier_id)
    if data is None:
        return {"status": "no_data", "message": "Aucune donnée chargée"}

    # ── Infos comptables de base (toujours disponibles si data existe) ──
    company = data.get("company", {})
    base = {
        "status": "data_loaded",
        "company": company.get("name", "Inconnu"),
        "nb_moves": len(data.get("moves", [])),
        "nb_partners": len(data.get("partners", [])),
        "source": data.get("source", ""),
    }

    # LECTURE SEULE. Cette route appelait auparavant `_execute_audit`, donc un
    # simple GET — monté au démarrage de trois écrans différents, dont la vue
    # par défaut du cabinet qui l'appelle une fois PAR DOSSIER — pouvait
    # déclencher plusieurs minutes d'appels LLM. Le résumé se contente
    # désormais de mettre en forme le dernier audit enregistré ; produire un
    # audit est le travail de POST /audit/run, sur clic.
    lu = _lire_audit_persiste(db, dossier_id, data)

    if lu["audit_status"] == "jamais_lance":
        return {
            **base,
            "audit_status": "jamais_lance",
            "nb_anomalies": 0,
            "risks": {"rouge": 0, "orange": 0, "vert": 0},
            "total_exposure_dh": 0,
            # None et non 0 : « pas mesuré » n'est pas « 0 % conforme ». Même
            # exigence que categorie_montant, qui refuse le zéro silencieux
            # quand on ne sait pas.
            "compliance_score": None,
            "executive_summary": "Aucune analyse n'a encore été lancée sur ce dossier.",
            "executive_ton": "neutre",
            "date_dernier_audit": None,
            "resultat_perime": None,
            "top_urgency": None,
        }

    findings = lu["findings"]
    risks = {"rouge": 0, "orange": 0, "vert": 0}
    for f in findings:
        risks[f.get("severity", "orange")] += 1
    # cf. app.regles_montant : "non_calculable" a amount_risk=0 côté
    # _alerte_to_dict, mais ce n'est PAS un montant vérifié à zéro — le
    # compter dans le total sous-estimerait silencieusement l'exposition
    # réelle. Même exigence que AuditPage.jsx côté frontend. Logique partagée
    # avec app.roi (le chiffrage ROI affiche le même total "exposition
    # chiffrable") pour ne pas la faire diverger silencieusement des deux côtés.
    expo = exposition_findings(findings)
    nb_non_chiffrables = expo["nb_non_chiffrables"]
    total_exposure = expo["total_dh"]
    compliance_score = max(0, 100 - len(findings) * 8)

    # Texte nu, sans emoji. Le backend décrit un ÉTAT (`executive_ton`), le
    # frontend choisit l'icône : injecter "✅"/"⚠️" dans une chaîne d'API rendue
    # verbatim par trois écrans mettait la charte graphique (« aucun emoji »,
    # App.css) dans un fichier de routes, et empêchait de changer d'icône sans
    # toucher au backend.
    if len(findings) == 0:
        exec_summary = "Aucune anomalie détectée. Le dossier fiscal est en bonne conformité au regard des règles du CGI analysées."
        exec_ton = "conforme"
    else:
        critical_count = risks["rouge"]
        orange_count = risks["orange"]
        parts = []
        if critical_count > 0:
            parts.append(f"{critical_count} anomalie(s) critique(s) nécessitant une action immédiate")
        if orange_count > 0:
            parts.append(f"{orange_count} alerte(s) modérée(s) à régulariser")
        exposure_str = f"{total_exposure:,.0f} DH".replace(",", " ")
        non_chiffrable_str = f" ({nb_non_chiffrables} anomalie(s) supplémentaire(s) sans montant chiffrable automatiquement, hors total)" if nb_non_chiffrables else ""
        summary_body = ", ".join(parts)
        exec_summary = (
            f"{len(findings)} anomalie(s) détectée(s) : {summary_body}. "
            f"Exposition fiscale chiffrable : {exposure_str}{non_chiffrable_str}."
        )
        exec_ton = "critique" if critical_count > 0 else "vigilance"

    top_urgency = None
    if findings:
        rouge_findings = [f for f in findings if f.get("severity") == "rouge"]
        top_f = rouge_findings[0] if rouge_findings else findings[0]
        top_urgency = {
            "title": top_f.get("title", ""),
            "invoice": top_f.get("invoice", ""),
            "amount_risk": top_f.get("amount_risk", 0),
            "severity": top_f.get("severity", "orange"),
        }

    return {
        **base,
        "audit_status": "done",
        "nb_anomalies": len(findings),
        "risks": risks,
        "total_exposure_dh": round(total_exposure, 2),
        "compliance_score": compliance_score,
        "executive_summary": exec_summary,
        "executive_ton": exec_ton,
        # Le résumé n'est plus recalculé à la volée : il faut pouvoir dire de
        # quand il date, et si les données comptables ont bougé depuis.
        "date_dernier_audit": lu["date_dernier_audit"],
        "resultat_perime": lu["resultat_perime"],
        "top_urgency": top_urgency,
    }


# ── Calendrier (Module 5) ─────────────────────────────────────────────────

def _sync_echeances(db: Session, dossier_id: uuid.UUID, events: list[dict]) -> None:
    """
    Persiste les échéances calculées dans la table Echeance (idempotent :
    upsert par dossier_id + type=category + date_limite). tax_calendar.py
    reste la source de vérité pour l'AFFICHAGE (recalcul à la volée, tient
    compte de la date du jour) ; cette table donne un historique interrogeable
    et une base pour de futures notifications (Phase 6), ce que la table ne
    faisait pas jusqu'ici bien qu'elle existe depuis la Phase 1.
    """
    now = datetime.now(timezone.utc)
    existing = {
        (e.type, e.date_limite.date()): e
        for e in db.execute(select(Echeance).where(Echeance.dossier_id == dossier_id)).scalars()
    }
    for ev in events:
        due_date = date.fromisoformat(ev["date"])
        due_dt = datetime.combine(due_date, datetime.min.time(), tzinfo=timezone.utc)
        category = ev.get("category", "Autre")
        statut = "a_venir" if due_dt >= now else "echue"
        key = (category, due_date)
        row = existing.get(key)
        if row is None:
            db.add(Echeance(id=uuid.uuid4(), dossier_id=dossier_id, type=category, date_limite=due_dt, statut=statut))
        elif row.statut != statut:
            row.statut = statut
    db.commit()


@router.get("/{dossier_id}/calendar/events")
def calendar_events(dossier_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    dossier = get_dossier_or_404(db, dossier_id, user)
    data = _get_active_accounting_data(db, dossier_id)
    try:
        events = get_calendar_events(regime=dossier.regime_is, tva_regime=dossier.regime_tva, odoo_data=data)
        try:
            _sync_echeances(db, dossier_id, events)
        except Exception as sync_exc:
            # La persistance est un ajout secondaire par rapport à l'affichage
            # (source de vérité = recalcul à la volée) : un souci ici ne doit
            # pas empêcher le cabinet de voir son calendrier.
            print(f"[calendar] échec de persistance des échéances pour {dossier_id} : {sync_exc}")
        return {"events": events}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Assistant fiscal sourcé (Module 2), avec persistance des citations ──

@router.post("/{dossier_id}/chat")
def chat(dossier_id: uuid.UUID, req: ChatRequest, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    dossier = get_dossier_or_404(db, dossier_id, user)

    # Langue detectee sur la question, sauf si le client l'impose. Elle sert
    # deux fois : a traduire la requete de recherche vers le francais (le
    # corpus n'existe qu'en francais) et a rediger la reponse.
    langue = req.langue or detecter_langue(req.query)

    # ── Routage d'intention, AVANT tout appel RAG/LLM ────────────────────
    # « Quand est ma prochaine déclaration de TVA ? » n'a pas sa réponse dans
    # le corpus CGI, elle se CALCULE — tax_calendar.py le fait déjà pour
    # GET /calendar/events. L'envoyer au RAG coûtait 3 appels LLM (reformulation
    # + filtrage + génération) et 5 articles complets dans le prompt pour, au
    # mieux, faire lire l'Art. 110 à un modèle en espérant qu'il en extraie une
    # date — plus cher ET moins fiable qu'un calcul déterministe déjà en place.
    intention = classifier_intention(req.query, langue)
    if intention == "echeance":
        events = get_calendar_events(regime=dossier.regime_is, tva_regime=dossier.regime_tva)
        resultat = repondre_echeance(req.query, events)
        # Pas de Citation persistée ici : aucun article n'a été consulté, en
        # créer une laisserait croire à une réponse sourcée sur le corpus —
        # exactement ce que `sourced: False` de tax_calendar.py refuse déjà.
        return {
            "query": req.query, "answer": resultat["answer"], "sources": [],
            "langue": langue, "sourced": False, "intention": "echeance",
        }

    store = get_vectorstore()
    matches = retrieve_sourced_articles(
        store, req.query, label=str(dossier_id), top_k_final=req.top_k, langue=langue,
    )

    sources = [
        {
            "id": m.id,
            "reference": m.reference,
            "source_label": m.source_label,
            "score": round(m.score, 4),
            "extrait": clean_article_text(m.texte)[:280],
            "texte_complet": clean_article_text(m.texte),
            # 'NOTE_CIRCULAIRE' distingue une interprétation administrative
            # d'un texte de loi — generate_answer() en a besoin pour ne
            # jamais laisser une réponse confondre les deux registres.
            "type": m.type,
        }
        for m in matches
    ]

    if not sources:
        return {"query": req.query, "answer": "Aucun article pertinent trouvé.", "sources": [], "langue": langue}

    try:
        answer = generate_answer(
            req.query, sources,
            context_data=req.context_data, active_view=req.active_view, langue=langue,
            format_reponse=choisir_format_reponse(sources),
        )
    except Exception as exc:
        answer = f"Erreur lors de la génération (articles trouvés ci-dessous quand même). Détail : {exc}"

    # Traçabilité anti-hallucination : une ligne `citation` par article
    # effectivement retourné en source de cette réponse (table CITATION du MCD).
    for s in sources:
        db.add(Citation(
            id=uuid.uuid4(),
            dossier_id=dossier_id,
            question=req.query,
            reponse=answer,
            article_reference=s["reference"],
        ))
    db.commit()

    # `langue` est renvoyee pour que l'interface applique dir="rtl" sur la
    # seule bulle de reponse, sans avoir a redetecter cote client.
    return {"query": req.query, "answer": answer, "sources": sources, "langue": langue}


@router.get("/{dossier_id}/chat/historique")
def chat_historique(dossier_id: uuid.UUID, limit: int = 50, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    get_dossier_or_404(db, dossier_id, user)
    citations = db.execute(
        select(Citation).where(Citation.dossier_id == dossier_id).order_by(Citation.created_at.desc()).limit(limit)
    ).scalars().all()
    return {
        "historique": [
            {
                "question": c.question,
                "reponse": c.reponse,
                "article_reference": c.article_reference,
                "created_at": c.created_at.isoformat(),
            }
            for c in citations
        ]
    }


@router.get("/{dossier_id}/alertes")
def list_alertes(
    dossier_id: uuid.UUID,
    inclure_inactives: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Alertes du dossier, plus récentes en premier.

    Par défaut seules les alertes encore détectées au dernier audit sont
    renvoyées. `inclure_inactives=true` ajoute celles qui ont disparu des
    données comptables — utile pour justifier a posteriori qu'une anomalie
    a bien été corrigée, puisqu'on ne les supprime plus.
    """
    get_dossier_or_404(db, dossier_id, user)
    stmt = select(AlerteRisque).where(AlerteRisque.dossier_id == dossier_id)
    if not inclure_inactives:
        stmt = stmt.where(AlerteRisque.actif.is_(True))
    alertes = db.execute(stmt.order_by(AlerteRisque.created_at.desc())).scalars().all()
    versions = _versions_corpus(db, alertes)
    return {"alertes": [_alerte_to_dict(a, versions.get(a.id)) for a in alertes]}


@router.patch("/{dossier_id}/alertes/{alerte_id}")
def update_alerte_statut(
    dossier_id: uuid.UUID,
    alerte_id: uuid.UUID,
    req: AlerteStatutRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Classe une alerte : ouverte / traitée / ignorée.

    `StatutAlerte` existait depuis la Phase 1 mais aucune route ne l'écrivait :
    toutes les alertes restaient « ouverte » à vie, et la simulation de contrôle
    (qui ne travaille que sur les alertes ouvertes) ne pouvait donc jamais être
    restreinte au périmètre réellement litigieux.

    Ce statut ne survivait de toute façon pas à un ré-audit avant la clé métier
    (voir _execute_audit) — les deux corrections vont ensemble.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")

    alerte = db.get(AlerteRisque, alerte_id)
    # RLS garantit l'isolation entre organisations ; la comparaison explicite
    # sur dossier_id empêche en plus de modifier l'alerte d'un AUTRE dossier
    # du même cabinet en forgeant l'URL.
    if alerte is None or alerte.dossier_id != dossier_id:
        raise HTTPException(status_code=404, detail="Alerte introuvable.")

    try:
        alerte.statut = StatutAlerte(req.statut)
    except ValueError:
        attendus = ", ".join(s.value for s in StatutAlerte)
        raise HTTPException(status_code=422, detail=f"Statut invalide. Valeurs attendues : {attendus}.")

    db.commit()
    return _alerte_to_dict(alerte, _versions_corpus(db, [alerte]).get(alerte.id))


@router.patch("/{dossier_id}/alertes/{alerte_id}/retenue-source")
def confirmer_retenue_source(
    dossier_id: uuid.UUID,
    alerte_id: uuid.UUID,
    req: RetenueSourceRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Confirmation comptable du statut Art. 151 (retenue à la source) sur une
    alerte précise — seul moyen de sortir cette anomalie de
    `non_calculable`, cf. app.regles_montant.remuneration_tiers_non_declaree_art151.

    Restreinte à `reference_cgi == "article 151"` : les autres articles ont
    leur propre raison d'être non-calculables (Art. 146 par construction) et
    ne doivent pas hériter d'un formulaire qui n'a de sens que pour celui-ci.

    Recalcule montant_exposition/categorie_montant/montant_detail/
    montant_hypothese immédiatement (pas besoin de relancer tout l'audit
    RAG) : correction_agent.py réutilise déjà les citations de l'alerte, la
    même logique s'applique ici — le RAG a fait son travail (identifier
    l'article), reste une donnée humaine à appliquer à une formule connue.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")

    alerte = db.get(AlerteRisque, alerte_id)
    if alerte is None or alerte.dossier_id != dossier_id:
        raise HTTPException(status_code=404, detail="Alerte introuvable.")

    if _normalize_ref(alerte.reference_cgi or "") != "article 151":
        raise HTTPException(
            status_code=422,
            detail="Cette confirmation ne s'applique qu'aux alertes fondées sur l'Article 151 (retenue à la source).",
        )

    alerte.retenue_source_confirmee = req.applicable
    alerte.retenue_montant_du = req.montant_du if req.applicable else None

    resultat = remuneration_tiers_non_declaree_art151(req.applicable, req.montant_du, None)
    alerte.montant_exposition = resultat.montant
    alerte.categorie_montant = resultat.categorie.value
    alerte.montant_detail = resultat.detail
    alerte.montant_hypothese = resultat.hypothese

    db.commit()
    # Le frontend remplace le finding en place avec cette réponse (App.jsx,
    # confirmerRetenueSource) : sans la version, la carte perdrait sa source
    # affichée au moment où le comptable confirme la retenue.
    return _alerte_to_dict(alerte, _versions_corpus(db, [alerte]).get(alerte.id))
