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
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_auditor import run_ai_rag_audit
from app.api import get_vectorstore
from app.auth import CurrentUser, get_current_user
from app.compliance_checker import run_audit
from app.db_session import get_tenant_db
from app.generation import generate_answer
from app.models import (
    AlerteRisque,
    Citation,
    ConnexionComptable,
    Dossier,
    NiveauRisque,
    PieceComptable,
    StatutAlerte,
    TypeConnexion,
)
from app.odoo_connector import OdooConnector, get_demo_data
from app.tax_calendar import get_calendar_events

router = APIRouter(prefix="/dossiers", tags=["Dossiers"])

# Verrou process-local pour éviter de relancer l'audit LLM en double sur
# deux requêtes concurrentes pour le même dossier (l'invalidation, elle,
# est désormais portée par hash_donnees en base, plus par une variable
# globale).
_audit_locks: dict[str, threading.Lock] = {}


def _lock_for(dossier_id: str) -> threading.Lock:
    return _audit_locks.setdefault(dossier_id, threading.Lock())


def _hash_data(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _get_dossier_or_404(db: Session, dossier_id: uuid.UUID) -> Dossier:
    dossier = db.get(Dossier, dossier_id)
    if dossier is None:
        # Grâce à la RLS, un dossier d'une autre organisation n'est de toute
        # façon jamais renvoyé par .get() : ce 404 couvre aussi bien
        # "n'existe pas" que "n'appartient pas à votre organisation".
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    return dossier


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


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    top_k: int = Field(5, ge=1, le=15)
    context_data: Optional[dict] = None
    active_view: Optional[str] = None


# ── CRUD dossier (Module 7 — Espaces & multi-tenant) ─────────────────────

@router.post("", response_model=DossierResponse, status_code=201)
def create_dossier(
    req: DossierCreateRequest,
    user: CurrentUser = Depends(get_current_user),
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
def list_dossiers(db: Session = Depends(get_tenant_db)):
    # La RLS filtre déjà par organisation : pas de WHERE supplémentaire nécessaire.
    dossiers = db.execute(select(Dossier)).scalars().all()
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


# ── Ingestion Odoo (remplace le state global) ────────────────────────────

@router.post("/{dossier_id}/odoo/connect")
def odoo_connect(dossier_id: uuid.UUID, req: OdooConnectRequest, db: Session = Depends(get_tenant_db)):
    _get_dossier_or_404(db, dossier_id)
    try:
        connector = OdooConnector(req.url, req.db, req.username, req.password)
        connector.authenticate()
        data = connector.fetch_accounting_data()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Connexion Odoo échouée : {exc}")

    _persist_accounting_data(db, dossier_id, source="odoo", data=data, connexion_type=TypeConnexion.odoo)

    return {
        "status": "connected",
        "company": data.get("company", {}).get("name", "Inconnu"),
        "nb_moves": len(data.get("moves", [])),
        "nb_partners": len(data.get("partners", [])),
    }


@router.post("/{dossier_id}/odoo/demo")
def odoo_demo(dossier_id: uuid.UUID, db: Session = Depends(get_tenant_db)):
    """Charge des données de démonstration simulées pour ce dossier (sans instance Odoo réelle)."""
    _get_dossier_or_404(db, dossier_id)
    data = get_demo_data()
    _persist_accounting_data(db, dossier_id, source="demo", data=data, connexion_type=TypeConnexion.odoo)
    return {
        "status": "demo_loaded",
        "company": data["company"]["name"],
        "nb_moves": len(data["moves"]),
        "nb_partners": len(data["partners"]),
    }


@router.get("/{dossier_id}/odoo/status")
def odoo_status(dossier_id: uuid.UUID, db: Session = Depends(get_tenant_db)):
    _get_dossier_or_404(db, dossier_id)
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


# ── Audit / risques (Module 3) ───────────────────────────────────────────

def _execute_audit(db: Session, dossier_id: uuid.UUID, data: dict, force: bool = False) -> list[dict]:
    """
    Remplace le cache en mémoire (_audit_cache) par un cache en base, clé
    sur hash_donnees : si les données comptables n'ont pas changé depuis
    la dernière exécution, on relit les alertes déjà stockées plutôt que
    de rappeler le LLM.
    """
    new_hash = _hash_data(data)

    with _lock_for(str(dossier_id)):
        existing = db.execute(
            select(AlerteRisque).where(AlerteRisque.dossier_id == dossier_id)
        ).scalars().all()

        if not force and existing and all(a.hash_donnees == new_hash for a in existing):
            return [_alerte_to_dict(a) for a in existing]

        try:
            findings = run_ai_rag_audit(data) if os.environ.get("GROQ_API_KEY") else None
            if not findings:
                findings = run_audit(data)
        except Exception as exc:
            print(f"Audit RAG IA non disponible ({exc}), fallback sur les règles statiques.")
            findings = run_audit(data)

        # Remplace les alertes existantes du dossier par le résultat frais
        db.query(AlerteRisque).filter(AlerteRisque.dossier_id == dossier_id).delete()
        alertes = []
        for f in findings:
            niveau = {"rouge": NiveauRisque.eleve, "orange": NiveauRisque.moyen}.get(f.get("severity"), NiveauRisque.faible)
            alerte = AlerteRisque(
                id=uuid.uuid4(),
                dossier_id=dossier_id,
                titre=f.get("title", "Anomalie détectée"),
                description=f.get("description", ""),
                niveau_risque=niveau,
                montant_exposition=f.get("amount_risk"),
                statut=StatutAlerte.ouverte,
                hash_donnees=new_hash,
            )
            db.add(alerte)
            alertes.append((alerte, f))
        db.commit()

        return [_finding_with_id(a, f) for a, f in alertes]


def _alerte_to_dict(a: AlerteRisque) -> dict:
    severity = {"eleve": "rouge", "moyen": "orange", "faible": "vert"}[a.niveau_risque.value]
    return {
        "id": str(a.id),
        "title": a.titre,
        "description": a.description,
        "severity": severity,
        "amount_risk": float(a.montant_exposition) if a.montant_exposition is not None else 0,
    }


def _finding_with_id(a: AlerteRisque, f: dict) -> dict:
    out = dict(f)
    out["id"] = str(a.id)
    return out


@router.post("/{dossier_id}/audit/run")
def audit_run(dossier_id: uuid.UUID, force: bool = False, db: Session = Depends(get_tenant_db)):
    _get_dossier_or_404(db, dossier_id)
    data = _get_active_accounting_data(db, dossier_id)
    if data is None:
        raise HTTPException(status_code=400, detail="Aucune donnée comptable chargée pour ce dossier. Appelez /odoo/connect ou /odoo/demo d'abord.")
    try:
        findings = _execute_audit(db, dossier_id, data, force=force)
        return {"nb_anomalies": len(findings), "findings": findings}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Dashboard (résumé par dossier) ────────────────────────────────────────

@router.get("/{dossier_id}/dashboard/summary")
def dashboard_summary(dossier_id: uuid.UUID, db: Session = Depends(get_tenant_db)):
    _get_dossier_or_404(db, dossier_id)
    data = _get_active_accounting_data(db, dossier_id)
    if data is None:
        return {"status": "no_data", "message": "Aucune donnée chargée"}

    try:
        findings = _execute_audit(db, dossier_id, data)
        risks = {"rouge": 0, "orange": 0, "vert": 0}
        for f in findings:
            risks[f.get("severity", "orange")] += 1
        total_exposure = sum(f.get("amount_risk", 0) for f in findings)
        compliance_score = max(0, 100 - len(findings) * 8)

        if len(findings) == 0:
            exec_summary = "✅ Aucune anomalie détectée. Le dossier fiscal est en bonne conformité au regard des règles du CGI 2026 analysées."
        else:
            critical_count = risks["rouge"]
            orange_count = risks["orange"]
            parts = []
            if critical_count > 0:
                parts.append(f"{critical_count} anomalie(s) critique(s) nécessitant une action immédiate")
            if orange_count > 0:
                parts.append(f"{orange_count} alerte(s) modérée(s) à régulariser")
            exposure_str = f"{total_exposure:,.0f} DH".replace(",", " ")
            summary_body = ", ".join(parts)
            exec_summary = f"⚠️ {len(findings)} anomalie(s) détectée(s) : {summary_body}. Exposition fiscale estimée : {exposure_str}."

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
            "company": data.get("company", {}).get("name", "Inconnu"),
            "nb_anomalies": len(findings),
            "risks": risks,
            "total_exposure_dh": round(total_exposure, 2),
            "compliance_score": compliance_score,
            "executive_summary": exec_summary,
            "top_urgency": top_urgency,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Calendrier (Module 5) ─────────────────────────────────────────────────

@router.get("/{dossier_id}/calendar/events")
def calendar_events(dossier_id: uuid.UUID, db: Session = Depends(get_tenant_db)):
    dossier = _get_dossier_or_404(db, dossier_id)
    data = _get_active_accounting_data(db, dossier_id)
    try:
        events = get_calendar_events(regime=dossier.regime_is, tva_regime=dossier.regime_tva, odoo_data=data)
        return {"events": events}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Assistant fiscal sourcé (Module 2), avec persistance des citations ──

@router.post("/{dossier_id}/chat")
def chat(dossier_id: uuid.UUID, req: ChatRequest, db: Session = Depends(get_tenant_db)):
    _get_dossier_or_404(db, dossier_id)

    store = get_vectorstore()
    matches = store.search(req.query, top_k=req.top_k)

    sources = [
        {
            "id": m.id,
            "reference": m.reference,
            "source_label": m.source_label,
            "score": round(m.score, 4),
            "extrait": m.texte.strip()[:280],
            "texte_complet": m.texte.strip(),
        }
        for m in matches
    ]

    if not sources:
        return {"query": req.query, "answer": "Aucun article pertinent trouvé.", "sources": []}

    try:
        answer = generate_answer(req.query, sources, context_data=req.context_data, active_view=req.active_view)
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

    return {"query": req.query, "answer": answer, "sources": sources}


@router.get("/{dossier_id}/chat/historique")
def chat_historique(dossier_id: uuid.UUID, limit: int = 50, db: Session = Depends(get_tenant_db)):
    _get_dossier_or_404(db, dossier_id)
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
def list_alertes(dossier_id: uuid.UUID, db: Session = Depends(get_tenant_db)):
    _get_dossier_or_404(db, dossier_id)
    alertes = db.execute(
        select(AlerteRisque).where(AlerteRisque.dossier_id == dossier_id).order_by(AlerteRisque.created_at.desc())
    ).scalars().all()
    return {"alertes": [_alerte_to_dict(a) for a in alertes]}
