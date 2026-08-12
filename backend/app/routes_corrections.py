"""
routes_corrections.py — Workflow agentique de correction avec validation humaine.

## La machine à états, en une image

    AlerteRisque (actif, clé métier stable)
        │  POST .../proposition        génération + garde-fous
        │     échec ⇒ RIEN n'est persisté (502 explicite)
        ▼
    en_attente ──valider──► validee ──pousser──► poussee (brouillon Odoo)
        │   ▲                                │
        │   └── PATCH (amendement)           └── échec ─► erreur ──retry──► validee
        └── rejeter (motif obligatoire) ──► rejetee   (terminal, regénérable)

Toute transition illégale répond 409 avec un message en français, jamais un 500.

## Le principe qui gouverne tout le fichier

Aucune écriture ne part vers l'ERP sans qu'un humain identifié l'ait validée,
et ce qu'il valide est exactement ce qui partira. C'est pour ça que
l'amendement rejoue la validation d'équilibre, que le motif de rejet est
obligatoire, et que `decide_par_id` est renseigné : en cas de contrôle fiscal,
la question ne sera pas « qu'a dit l'IA » mais « qui a décidé ».
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import get_vectorstore
from app.auth import CurrentUser, get_current_user
from app.correction_agent import CORPUS_VERSION, TYPES_AVEC_ECRITURE, generer_proposition, valider_equilibre
from app.db_session import get_tenant_db
from app.models import (
    AlerteRisque,
    CitationProposition,
    ConnexionComptable,
    PropositionCorrection,
    StatutAlerte,
    StatutProposition,
    TypeConnexion,
)
from app.odoo_connector import OdooConnector
from app.routes_dossiers import _get_active_accounting_data
from app.secrets_store import cle_disponible, dechiffrer
from app.tenant_guard import get_dossier_or_404
from app.text_cleaning import clean_article_text

router = APIRouter(prefix="/dossiers", tags=["Corrections"])

# Un seul appel LLM de génération à la fois par dossier : la génération dure
# 10 à 30 s et double-cliquer ne doit pas produire deux propositions
# concurrentes. Même patron que _audit_locks / _simulation_locks.
_generation_locks: dict[str, threading.Lock] = {}


def _lock_for(dossier_id: str) -> threading.Lock:
    return _generation_locks.setdefault(dossier_id, threading.Lock())


def _retrouver_ecriture(
    db: Session, dossier_id: uuid.UUID, move_ref: str | None
) -> tuple[dict | None, list[dict]]:
    """
    Retrouve dans le snapshot comptable l'écriture désignée par une alerte.

    Rapprochement par `move_ref` (le n° de pièce, ex. « OD/2026/06/0001 »)
    et non par id technique : `AlerteRisque` ne stocke pas l'id Odoo, et le
    n° de pièce est justement l'identité stable que la clé métier utilise
    déjà. Comparaison sur `name` puis `ref`, les deux champs sous lesquels
    le pivot peut porter ce numéro selon la source (Odoo vs import CSV).

    Retourne `(None, [])` si le snapshot a disparu ou si la pièce n'y est
    plus (resynchro Odoo depuis l'audit) — cas non exceptionnel, traité en
    amont par le générateur, qui se voit alors interdire de chiffrer plutôt
    que d'improviser.
    """
    if not move_ref:
        return None, []
    data = _get_active_accounting_data(db, dossier_id) or {}
    moves = data.get("moves") or []
    cible = str(move_ref).strip()
    move = next(
        (m for m in moves if str(m.get("name") or "").strip() == cible
         or str(m.get("ref") or "").strip() == cible),
        None,
    )
    if move is None:
        return None, []
    move_id = move.get("id")
    lignes = [
        l for l in (data.get("lines") or [])
        if isinstance(l.get("move_id"), list) and l["move_id"] and l["move_id"][0] == move_id
    ]
    return move, lignes


# ── schémas ──────────────────────────────────────────────────────────────

class LigneEcriture(BaseModel):
    compte: str
    libelle: str = ""
    debit: float = 0.0
    credit: float = 0.0


class AmendementRequest(BaseModel):
    lignes: list[LigneEcriture] | None = None
    resume: str | None = Field(None, max_length=300)
    action: str | None = None
    date_ecriture: str | None = None


class RejetRequest(BaseModel):
    # Un rejet sans motif ne se distingue pas d'un oubli. Cinq caractères
    # minimum : assez pour empêcher un "x", pas assez pour décourager.
    motif: str = Field(..., min_length=5, max_length=2000)


# ── helpers ──────────────────────────────────────────────────────────────

def _proposition_to_dict(p: PropositionCorrection) -> dict:
    payload = p.payload_json or {}
    return {
        "id": str(p.id),
        "alerte_id": str(p.alerte_id),
        "cle_metier": p.cle_metier,
        "statut": p.statut.value,
        "type_correction": p.type_correction.value,
        "peut_etre_poussee": p.type_correction in TYPES_AVEC_ECRITURE,
        "resume": p.resume,
        "justification": p.justification,
        "lignes": payload.get("lignes", []),
        "action": payload.get("action"),
        "date_ecriture": payload.get("date_ecriture"),
        "references": p.references_json or [],
        "montant_impact": float(p.montant_impact) if p.montant_impact is not None else None,
        "categorie_montant": p.categorie_montant,
        "montant_detail": p.montant_detail,
        "montant_hypothese": p.montant_hypothese,
        "genere_le": p.genere_le.isoformat() if p.genere_le else None,
        "genere_par_modele": p.genere_par_modele,
        "critique": p.critique_json,
        "amendee": p.amendee_le is not None,
        "amendee_le": p.amendee_le.isoformat() if p.amendee_le else None,
        "payload_origine": p.payload_origine_json,
        "decide_le": p.decide_le.isoformat() if p.decide_le else None,
        "motif_decision": p.motif_decision,
        "odoo_move_id": p.odoo_move_id,
        "odoo_url": p.odoo_url,
        "pousse_le": p.pousse_le.isoformat() if p.pousse_le else None,
        "erreur_message": p.erreur_message,
    }


def _get_proposition_or_404(db: Session, dossier_id: uuid.UUID, proposition_id: uuid.UUID) -> PropositionCorrection:
    p = db.get(PropositionCorrection, proposition_id)
    # La RLS isole déjà les organisations ; la comparaison sur dossier_id
    # empêche en plus d'agir sur la proposition d'un AUTRE dossier du même
    # cabinet en forgeant l'URL.
    if p is None or p.dossier_id != dossier_id:
        raise HTTPException(status_code=404, detail="Proposition introuvable.")
    return p


def _exiger_statut(p: PropositionCorrection, attendus: set[StatutProposition], action: str) -> None:
    if p.statut not in attendus:
        libelles = " ou ".join(s.value for s in attendus)
        raise HTTPException(
            status_code=409,
            detail=f"Impossible de {action} une proposition au statut « {p.statut.value} » "
                   f"(statut attendu : {libelles}).",
        )


# ── génération ───────────────────────────────────────────────────────────

@router.post("/{dossier_id}/alertes/{alerte_id}/proposition")
def creer_proposition(
    dossier_id: uuid.UUID,
    alerte_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Génère une proposition de correction pour une alerte.

    Aucune nouvelle recherche RAG : le générateur ne reçoit que le texte des
    articles DÉJÀ cités par l'alerte (voir correction_agent). Si le modèle ne
    produit rien de sourçable et d'équilibré, on répond 502 et **rien n'est
    écrit en base** — pas de proposition « à moitié valide » à trier plus tard.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")

    alerte = db.get(AlerteRisque, alerte_id)
    if alerte is None or alerte.dossier_id != dossier_id:
        raise HTTPException(status_code=404, detail="Alerte introuvable.")
    if not alerte.actif:
        raise HTTPException(
            status_code=409,
            detail="Cette anomalie n'est plus détectée dans les données comptables : "
                   "elle n'a plus besoin d'être corrigée.",
        )

    with _lock_for(str(dossier_id)):
        existante = db.execute(
            select(PropositionCorrection).where(
                PropositionCorrection.alerte_id == alerte_id,
                PropositionCorrection.statut != StatutProposition.rejetee,
            )
        ).scalars().first()
        if existante is not None:
            # 409 et non 200 : renvoyer silencieusement l'existante masquerait
            # le fait que le clic n'a rien produit de neuf.
            raise HTTPException(
                status_code=409,
                detail="Une proposition existe déjà pour cette alerte. "
                       "Rejetez-la d'abord si vous voulez en générer une autre.",
            )

        references = [r for r in [alerte.reference_cgi, *(alerte.rag_sources_json or [])] if r]
        try:
            textes = get_vectorstore().get_texts_by_references(list(dict.fromkeys(references)))
        except Exception:
            # Le corpus indisponible n'empêche pas de générer : le prompt sera
            # simplement moins fourni, et le filtrage des citations reste actif.
            textes = {}

        # L'écriture réellement visée, tirée du snapshot déjà persisté : aucun
        # appel Odoo, aucune requête de plus que le SELECT que faisait déjà le
        # push. Sans elle, le générateur ne connaissait de la pièce que son
        # numéro et devait inventer les montants (cf. correction_agent.
        # _construire_contexte_ecriture).
        move, lignes_move = _retrouver_ecriture(db, dossier_id, alerte.move_ref)

        try:
            resultat = generer_proposition(alerte, textes, move, lignes_move)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Génération de la correction en échec : {exc}")

        proposition = PropositionCorrection(
            id=uuid.uuid4(),
            dossier_id=dossier_id,
            alerte_id=alerte_id,
            cle_metier=alerte.cle_metier or "",
            statut=StatutProposition.en_attente,
            type_correction=resultat["type_correction"],
            resume=resultat["resume"],
            justification=resultat["justification"],
            payload_json=resultat["payload"],
            references_json=resultat["references"],
            montant_impact=resultat["montant_impact"],
            categorie_montant=resultat.get("categorie_montant"),
            montant_detail=resultat.get("montant_detail"),
            montant_hypothese=resultat.get("montant_hypothese"),
            genere_par_modele=resultat.get("modele"),
            critique_json=resultat.get("critique"),
        )
        db.add(proposition)
        db.flush()

        # L'invariant du module : une proposition sans citation ne doit pas
        # exister. _interpreter a déjà refusé le cas references == [], cette
        # boucle matérialise la traçabilité horodatée.
        for ref in resultat["references"]:
            db.add(CitationProposition(
                id=uuid.uuid4(),
                proposition_id=proposition.id,
                article_reference=ref,
                version_corpus=CORPUS_VERSION,
            ))

        db.commit()
        return _proposition_to_dict(proposition)


# ── consultation ─────────────────────────────────────────────────────────

@router.get("/{dossier_id}/propositions")
def lister_propositions(
    dossier_id: uuid.UUID,
    statut: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    get_dossier_or_404(db, dossier_id, user)
    stmt = select(PropositionCorrection).where(PropositionCorrection.dossier_id == dossier_id)
    if statut:
        try:
            stmt = stmt.where(PropositionCorrection.statut == StatutProposition(statut))
        except ValueError:
            attendus = ", ".join(s.value for s in StatutProposition)
            raise HTTPException(status_code=422, detail=f"Statut inconnu. Valeurs possibles : {attendus}.")
    propositions = db.execute(stmt.order_by(PropositionCorrection.created_at.desc())).scalars().all()
    return {"propositions": [_proposition_to_dict(p) for p in propositions]}


@router.get("/{dossier_id}/propositions/{proposition_id}")
def detail_proposition(
    dossier_id: uuid.UUID,
    proposition_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Proposition + texte intégral des articles cités, pour que le validateur relise la source."""
    get_dossier_or_404(db, dossier_id, user)
    p = _get_proposition_or_404(db, dossier_id, proposition_id)

    articles = []
    try:
        textes = get_vectorstore().get_texts_by_references(list(p.references_json or []))
        articles = [
            {"reference": ref, "texte_complet": clean_article_text(textes[ref])}
            for ref in (p.references_json or []) if textes.get(ref)
        ]
    except Exception:
        articles = []

    return {**_proposition_to_dict(p), "articles_cites": articles}


# ── amendement ───────────────────────────────────────────────────────────

@router.patch("/{dossier_id}/propositions/{proposition_id}")
def amender_proposition(
    dossier_id: uuid.UUID,
    proposition_id: uuid.UUID,
    req: AmendementRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Modifie une proposition en attente.

    Deux points de conception :

    - la version produite par l'IA est figée dans `payload_origine_json` au
      PREMIER amendement seulement. Sans elle, on ne pourrait plus distinguer
      ce qui vient de la machine de ce qui vient de l'humain — exactement la
      question qu'un contrôleur poserait.
    - l'équilibre débit/crédit est revérifié. Un humain se trompe aussi, et la
      règle comptable ne lui est pas plus indulgente qu'au modèle.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")
    p = _get_proposition_or_404(db, dossier_id, proposition_id)
    _exiger_statut(p, {StatutProposition.en_attente}, "amender")

    payload = dict(p.payload_json or {})

    if req.lignes is not None:
        lignes = [l.model_dump() for l in req.lignes]
        if p.type_correction in TYPES_AVEC_ECRITURE:
            ok, motif = valider_equilibre(lignes)
            if not ok:
                raise HTTPException(status_code=422, detail=motif)
        elif lignes:
            raise HTTPException(
                status_code=422,
                detail=f"Une proposition de type « {p.type_correction.value} » ne comporte pas d'écriture comptable.",
            )
        payload["lignes"] = lignes

    if req.action is not None:
        payload["action"] = req.action.strip() or None
    if req.date_ecriture is not None:
        try:
            date.fromisoformat(req.date_ecriture)
        except ValueError:
            raise HTTPException(status_code=422, detail="Date d'écriture invalide (format attendu : AAAA-MM-JJ).")
        payload["date_ecriture"] = req.date_ecriture

    if p.payload_origine_json is None:
        p.payload_origine_json = p.payload_json

    p.payload_json = payload
    if req.resume:
        p.resume = req.resume.strip()[:300]
    p.amendee_le = datetime.now(timezone.utc)
    p.amendee_par_id = uuid.UUID(user.id)

    db.commit()
    return _proposition_to_dict(p)


# ── décision humaine ─────────────────────────────────────────────────────

@router.post("/{dossier_id}/propositions/{proposition_id}/valider")
def valider_proposition(
    dossier_id: uuid.UUID,
    proposition_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Le validateur endosse la proposition.

    On revérifie l'équilibre juste avant : c'est le dernier point où la
    proposition peut encore être refusée sans conséquence, et une écriture
    déséquilibrée validée serait rejetée par Odoo plus tard, avec un message
    bien moins clair.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")
    p = _get_proposition_or_404(db, dossier_id, proposition_id)
    _exiger_statut(p, {StatutProposition.en_attente}, "valider")

    if p.type_correction in TYPES_AVEC_ECRITURE:
        ok, motif = valider_equilibre((p.payload_json or {}).get("lignes", []))
        if not ok:
            raise HTTPException(status_code=422, detail=f"Validation refusée — {motif}")

    p.statut = StatutProposition.validee
    p.decide_le = datetime.now(timezone.utc)
    p.decide_par_id = uuid.UUID(user.id)
    db.commit()
    return _proposition_to_dict(p)


@router.post("/{dossier_id}/propositions/{proposition_id}/rejeter")
def rejeter_proposition(
    dossier_id: uuid.UUID,
    proposition_id: uuid.UUID,
    req: RejetRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Écarte la proposition, avec motif obligatoire.

    Le motif n'est pas de la bureaucratie : c'est le seul signal exploitable
    sur ce que l'IA propose de travers, et la trace qui permet de dire à un
    contrôleur « cette piste a été examinée puis écartée pour telle raison »
    plutôt que « on ne l'a pas traitée ».
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")
    p = _get_proposition_or_404(db, dossier_id, proposition_id)
    _exiger_statut(p, {StatutProposition.en_attente, StatutProposition.validee, StatutProposition.erreur}, "rejeter")

    p.statut = StatutProposition.rejetee
    p.motif_decision = req.motif.strip()
    p.decide_le = datetime.now(timezone.utc)
    p.decide_par_id = uuid.UUID(user.id)
    db.commit()
    return _proposition_to_dict(p)


# ── push vers Odoo ───────────────────────────────────────────────────────

@router.post("/{dossier_id}/propositions/{proposition_id}/pousser")
def pousser_proposition(
    dossier_id: uuid.UUID,
    proposition_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Crée le brouillon correspondant dans Odoo.

    Niveau `admin` sur le dossier : c'est la seule route de tout Nisab qui
    écrit dans le système comptable du client.

    L'écriture est créée en `state = draft` et n'est JAMAIS postée — le
    comptable la relit dans son ERP et la valide lui-même. Nisab ne valide
    aucune écriture comptable, jamais (règle produit du projet).
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="admin")
    p = _get_proposition_or_404(db, dossier_id, proposition_id)

    # `erreur` est accepté : c'est le chemin de reprise après un échec Odoo
    # (mot de passe changé, compte manquant depuis corrigé).
    _exiger_statut(p, {StatutProposition.validee, StatutProposition.erreur}, "pousser")

    if p.type_correction not in TYPES_AVEC_ECRITURE:
        raise HTTPException(
            status_code=400,
            detail=f"Une proposition de type « {p.type_correction.value} » ne donne lieu à aucune "
                   "écriture comptable : il n'y a rien à créer dans Odoo.",
        )

    lignes = (p.payload_json or {}).get("lignes", [])
    ok, motif = valider_equilibre(lignes)
    if not ok:
        raise HTTPException(status_code=422, detail=f"Écriture invalide — {motif}")

    if not cle_disponible():
        raise HTTPException(
            status_code=503,
            detail="Chiffrement non configuré sur le serveur (NISAB_SECRET_KEY absente) : "
                   "impossible de relire les identifiants Odoo.",
        )

    connexion = db.execute(
        select(ConnexionComptable).where(
            ConnexionComptable.dossier_id == dossier_id,
            ConnexionComptable.type == TypeConnexion.odoo,
        )
    ).scalars().first()
    if connexion is None or not connexion.identifiants_chiffres:
        raise HTTPException(
            status_code=400,
            detail="Aucun identifiant Odoo mémorisé pour ce dossier. Reconnectez-vous à Odoo "
                   "en cochant « mémoriser les identifiants » pour pouvoir pousser des corrections.",
        )

    try:
        identifiants = dechiffrer(connexion.identifiants_chiffres)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # La société cible est celle qui a été auditée, mémorisée dans le snapshot.
    # La redeviner ici risquerait d'écrire dans une autre société que celle
    # d'où viennent les écritures analysées.
    data = _get_active_accounting_data(db, dossier_id) or {}
    company_id = data.get("company_id")

    connecteur = OdooConnector(
        url=identifiants["url"], db=identifiants["db"],
        username=identifiants["username"], password=identifiants["password"],
        company_id=company_id,
    )

    try:
        connecteur.authenticate()
        resultat = connecteur.create_draft_move(
            lignes=lignes,
            date_ecriture=(p.payload_json or {}).get("date_ecriture") or date.today().isoformat(),
            ref=f"Nisab — correction {p.cle_metier}"[:200],
            narration=f"{p.resume}\n\n{p.justification}\n\nArticles : {', '.join(p.references_json or [])}",
            journal_code=(p.payload_json or {}).get("journal"),
        )
    except Exception as exc:  # OdooWriteError incluse
        # L'échec est persisté : sans ça, l'utilisateur ne verrait qu'un message
        # éphémère et la proposition resterait « validée » comme si de rien
        # n'était, sans trace de la tentative.
        p.statut = StatutProposition.erreur
        p.erreur_message = str(exc)[:2000]
        db.commit()
        raise HTTPException(status_code=502, detail=f"Échec de la création dans Odoo : {exc}")

    p.statut = StatutProposition.poussee
    p.odoo_move_id = resultat["move_id"]
    p.odoo_url = resultat["url"]
    p.pousse_le = datetime.now(timezone.utc)
    p.erreur_message = None

    # L'alerte est traitée : elle sort du périmètre de la simulation de
    # contrôle, qui ne travaille que sur les alertes ouvertes.
    alerte = db.get(AlerteRisque, p.alerte_id)
    if alerte is not None:
        alerte.statut = StatutAlerte.traitee

    db.commit()
    return {
        **_proposition_to_dict(p),
        "comptes_resolus": resultat.get("comptes_resolus", []),
        "message": "Brouillon créé dans Odoo. Il n'est PAS validé : relisez-le puis postez-le depuis Odoo.",
    }
