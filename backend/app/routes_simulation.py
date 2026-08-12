"""
routes_simulation.py — Endpoints Phase 4 (Module 4 : simulation de contrôle).

Suit le même patron que routes_dossiers.py : toutes les routes passent par
get_tenant_db (RLS active sur simulation_controle / citation_simulation via
dossier_id), donc un dossier ou une simulation d'une autre organisation
n'est jamais renvoyé — même en forçant l'ID dans l'URL.
"""

from __future__ import annotations

import re
import threading
import unicodedata
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.control_simulator import run_simulation
from app.db_session import get_tenant_db
from app.models import AlerteRisque, CitationSimulation, Dossier, SimulationControle, StatutAlerte
from app.simulation_pdf import build_simulation_pdf
from app.tenant_guard import check_dossier_acces, get_dossier_or_404

router = APIRouter(tags=["Simulation de contrôle"])

# Même logique que _audit_locks dans routes_dossiers.py : évite deux
# exécutions concurrentes de la simulation (coûteuse en appels LLM) pour le
# même dossier.
_simulation_locks: dict[str, threading.Lock] = {}


def _lock_for(dossier_id: str) -> threading.Lock:
    return _simulation_locks.setdefault(dossier_id, threading.Lock())


def _slugify(text: str) -> str:
    """ASCII slug pour nom de fichier téléchargé (accents retirés, espaces -> _)."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_") or "dossier"


def _simulation_summary(s: SimulationControle) -> dict:
    themes = (s.rapport_json or {}).get("themes", [])
    exposition_totale = sum(t.get("exposition_totale_mad", 0) for t in themes)
    return {
        "id": str(s.id),
        "dossier_id": str(s.dossier_id),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "nb_themes": len(themes),
        "exposition_totale_mad": exposition_totale,
    }


@router.post("/dossiers/{dossier_id}/simulation/run")
def simulation_run(dossier_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """
    Lance une simulation de contrôle à partir des AlerteRisque actuellement
    ouvertes sur le dossier. Usage interne cabinet uniquement — rien n'est
    transmis à la DGI (rappel affiché côté frontend).
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")

    with _lock_for(str(dossier_id)):
        alertes = db.execute(
            select(AlerteRisque).where(
                AlerteRisque.dossier_id == dossier_id,
                AlerteRisque.statut == StatutAlerte.ouverte,
                # Une anomalie qui n'est plus détectée reste en base (actif=False)
                # pour l'historique, mais n'a rien à faire dans un argumentaire
                # de défense : on plaiderait sur une écriture déjà corrigée.
                AlerteRisque.actif.is_(True),
            )
        ).scalars().all()

        try:
            result = run_simulation(dossier_id, alertes)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Erreur lors de la simulation : {exc}")

        simulation = SimulationControle(
            id=uuid.uuid4(),
            dossier_id=dossier_id,
            rapport_json=result["rapport_json"],
            plan_remediation_json=result["plan_remediation_json"],
        )
        db.add(simulation)
        db.flush()

        for ref in result["articles_cites"]:
            db.add(CitationSimulation(
                id=uuid.uuid4(),
                simulation_id=simulation.id,
                article_reference=ref,
                version_corpus="CGI 2026",
            ))

        db.commit()

        return {
            "id": str(simulation.id),
            "dossier_id": str(dossier_id),
            "created_at": simulation.created_at.isoformat() if simulation.created_at else None,
            "rapport": simulation.rapport_json,
            "plan_remediation": simulation.plan_remediation_json,
        }


@router.get("/dossiers/{dossier_id}/simulations")
def list_simulations(dossier_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """Historique des simulations du dossier, plus récentes en premier."""
    get_dossier_or_404(db, dossier_id, user)
    rows = db.execute(
        select(SimulationControle)
        .where(SimulationControle.dossier_id == dossier_id)
        .order_by(SimulationControle.created_at.desc())
    ).scalars().all()
    return {"simulations": [_simulation_summary(s) for s in rows]}


@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """
    Détail d'une simulation. Pas de dossier_id dans le chemin (voir plan
    d'implémentation Phase 4) : l'isolation multi-tenant reste garantie par
    la policy RLS de simulation_controle (jointure sur dossier.organisation_id),
    pas par le chemin de l'URL — un ID d'une autre organisation renvoie 404
    exactement comme pour un dossier. La granularité par utilisateur (Acces)
    est vérifiée séparément via check_dossier_acces, RLS ne la couvrant pas.
    """
    simulation = db.get(SimulationControle, simulation_id)
    if simulation is None:
        raise HTTPException(status_code=404, detail="Simulation introuvable.")
    check_dossier_acces(db, simulation.dossier_id, user)
    return {
        "id": str(simulation.id),
        "dossier_id": str(simulation.dossier_id),
        "created_at": simulation.created_at.isoformat() if simulation.created_at else None,
        "rapport": simulation.rapport_json,
        "plan_remediation": simulation.plan_remediation_json,
    }


@router.get("/simulations/{simulation_id}/export")
def export_simulation_pdf(simulation_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """
    Export PDF du rapport — même logique d'isolation que get_simulation
    ci-dessus (RLS via dossier.organisation_id, pas de dossier_id dans le
    chemin). Ne relance rien : met juste en page ce qui est déjà persisté.
    """
    simulation = db.get(SimulationControle, simulation_id)
    if simulation is None:
        raise HTTPException(status_code=404, detail="Simulation introuvable.")
    check_dossier_acces(db, simulation.dossier_id, user)

    dossier = db.get(Dossier, simulation.dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")

    pdf_bytes = build_simulation_pdf(dossier, simulation)
    date_str = simulation.created_at.strftime("%Y-%m-%d") if simulation.created_at else "sans_date"
    filename = f"simulation_{_slugify(dossier.raison_sociale)}_{date_str}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
