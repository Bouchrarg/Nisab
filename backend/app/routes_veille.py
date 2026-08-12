"""
routes_veille.py — Consultation des notifications de veille par dossier.

Côté lecture uniquement : la diffusion, qui écrit pour toutes les
organisations, vit dans admin.py sous `admin_plateforme` (voir veille.py pour
la raison).

Toutes les routes ici passent par `get_tenant_db` et `get_dossier_or_404` : un
cabinet ne voit que les notifications de ses propres dossiers, et un
collaborateur que celles des dossiers auxquels il a accès.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db_session import get_tenant_db
from app.models import NotificationVeille
from app.tenant_guard import get_dossier_or_404

router = APIRouter(prefix="/dossiers", tags=["Veille"])


class MarquerLuRequest(BaseModel):
    lu: bool = True


def _notification_to_dict(n: NotificationVeille) -> dict:
    return {
        "id": str(n.id),
        "reference": n.article_corpus_reference,
        "message": n.message,
        "motif": n.motif,
        "niveau": n.niveau,
        "source_label": n.source_label,
        "document_id": n.document_id,
        "date_version": n.date_version,
        "lu": n.lu,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/{dossier_id}/veille")
def lister_veille(
    dossier_id: uuid.UUID,
    non_lues_seulement: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Notifications de veille du dossier, plus récentes en premier."""
    get_dossier_or_404(db, dossier_id, user)
    stmt = select(NotificationVeille).where(NotificationVeille.dossier_id == dossier_id)
    if non_lues_seulement:
        stmt = stmt.where(NotificationVeille.lu.is_(False))
    notifications = db.execute(stmt.order_by(NotificationVeille.created_at.desc())).scalars().all()
    return {
        "notifications": [_notification_to_dict(n) for n in notifications],
        "nb_non_lues": sum(1 for n in notifications if not n.lu),
    }


@router.patch("/{dossier_id}/veille/{notification_id}")
def marquer_lu(
    dossier_id: uuid.UUID,
    notification_id: uuid.UUID,
    req: MarquerLuRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Marque une notification comme lue (ou la remet en non-lue)."""
    get_dossier_or_404(db, dossier_id, user)
    n = db.get(NotificationVeille, notification_id)
    # Comparaison explicite sur dossier_id en plus de la RLS : empêche d'agir
    # sur la notification d'un autre dossier du même cabinet via l'URL.
    if n is None or n.dossier_id != dossier_id:
        raise HTTPException(status_code=404, detail="Notification introuvable.")
    n.lu = req.lu
    db.commit()
    return _notification_to_dict(n)


@router.post("/{dossier_id}/veille/tout-lu")
def tout_marquer_lu(
    dossier_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Marque toutes les notifications du dossier comme lues.

    Un UPDATE en masse plutôt qu'une boucle : sur un dossier ancien la liste
    peut être longue, et le compteur de non-lus n'a pas besoin d'être exact
    ligne à ligne pour être remis à zéro.
    """
    get_dossier_or_404(db, dossier_id, user)
    resultat = db.execute(
        update(NotificationVeille)
        .where(NotificationVeille.dossier_id == dossier_id, NotificationVeille.lu.is_(False))
        .values(lu=True)
    )
    db.commit()
    return {"nb_marquees": resultat.rowcount or 0}
