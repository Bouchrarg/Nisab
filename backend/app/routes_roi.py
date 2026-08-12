"""
routes_roi.py — Chiffrage de la valeur générée par Nisab (Lot 2.1).

Suit le même patron que routes_simulation.py : router sans préfixe, chemins
complets déclarés par route. Nécessaire ici parce que ce module expose deux
niveaux différents — un dossier (`/dossiers/{id}/roi`) et le portefeuille
entier du cabinet (`/roi/portefeuille`) — que le router `dossiers_router`
(préfixe `/dossiers`) ne peut pas exprimer pour ce second cas.

Le calcul lui-même vit dans app/roi.py (pur, sans FastAPI) ; ce fichier ne
fait que lire l'audit déjà persisté (jamais de calcul LLM — mêmes garanties
que GET /dossiers/{id}/audit/resultat) et l'agréger.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db_session import get_tenant_db
from app.models import Acces, Dossier
from app.roi import agreger_roi_portefeuille, calculer_roi_dossier
from app.routes_dossiers import _get_active_accounting_data, _lire_audit_persiste
from app.tax_calendar import get_calendar_events
from app.tenant_guard import get_dossier_or_404

router = APIRouter(tags=["ROI"])


#: Fenêtre maximale regardée en arrière pour l'exposition échéances, même
#: si les données remontent plus loin — évite qu'un dossier avec des années
#: d'historique produise des centaines d'échéances passées à chiffrer.
NB_MOIS_ARRIERE_MAX_ROI = 24


def _nb_mois_arriere(data: dict) -> int:
    """
    Nombre de mois entre la pièce comptable la plus ANCIENNE du dossier et
    aujourd'hui, pour que `get_calendar_events` regarde en arrière jusqu'à
    couvrir toute la période réellement documentée.

    ## Pourquoi get_calendar_events(odoo_data=data) seul ne suffisait pas

    Par défaut (`nb_months_back=0`), la fonction ne renvoie que des
    échéances À VENIR (`horizon_start = today`) — cohérent pour l'écran
    Calendrier, qui doit rester tourné vers l'avenir, mais faux pour le ROI :
    sur un dossier de démonstration dont les écritures sont datées de
    février-mars, dès que "today" dépasse ces mois (ce qui arrive vite,
    l'horizon avance chaque jour), la SEULE échéance TVA chiffrable de tout
    le dossier sort silencieusement de la fenêtre — le panneau affiche alors
    "0 DH, 0/24 échéances chiffrables" alors que le calcul lui-même est
    correct (vérifié par test_roi.py section 6 sur les mêmes données). Le
    ROI doit regarder en arrière jusqu'à la période réellement couverte par
    les écritures, pas seulement en avant depuis la date du jour.
    """
    from datetime import date as _date
    dates = [m.get("date") for m in data.get("moves", []) if m.get("date")]
    if not dates:
        return 0
    plus_ancienne = min(_date.fromisoformat(str(d)[:10]) for d in dates)
    mois = (_date.today().year - plus_ancienne.year) * 12 + (_date.today().month - plus_ancienne.month)
    return max(0, min(mois, NB_MOIS_ARRIERE_MAX_ROI))


def _roi_pour_dossier(db: Session, dossier: Dossier) -> dict | None:
    """
    None si le dossier n'a pas de données comptables ou n'a jamais été
    audité — un ROI de 0 DH sur un dossier non analysé affirmerait à tort
    "aucune valeur générée" alors que la vraie réponse est "pas encore mesuré"
    (même distinction que audit_status == 'jamais_lance' partout ailleurs).
    """
    data = _get_active_accounting_data(db, dossier.id)
    if data is None:
        return None
    lu = _lire_audit_persiste(db, dossier.id, data)
    if lu["audit_status"] != "done":
        return None
    nb_pieces = len(data.get("moves", []))
    # `odoo_data=data` : c'est ce qui permet à _montant_tva_periode de lire
    # les lignes de TVA facturée/déductible pour chiffrer l'exposition
    # échéances. `nb_months_back` étend la fenêtre à la période réellement
    # documentée par le dossier — voir _nb_mois_arriere ci-dessus pour la
    # raison, différente de GET /calendar/events qui reste volontairement
    # tourné vers l'avenir.
    events = get_calendar_events(
        regime=dossier.regime_is, tva_regime=dossier.regime_tva, odoo_data=data,
        nb_months_back=_nb_mois_arriere(data),
    )
    return calculer_roi_dossier(lu["findings"], nb_pieces, events=events)


@router.get("/dossiers/{dossier_id}/roi")
def roi_dossier(dossier_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    dossier = get_dossier_or_404(db, dossier_id, user)
    resultat = _roi_pour_dossier(db, dossier)
    if resultat is None:
        return {"status": "indisponible", "reason": "Aucune analyse disponible pour ce dossier."}
    return {"status": "ok", **resultat}


@router.get("/roi/portefeuille")
def roi_portefeuille(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """
    Agrégation sur les dossiers accessibles à l'utilisateur — même règle de
    périmètre que GET /dossiers (list_dossiers, routes_dossiers.py) : la RLS
    filtre déjà par organisation, mais un collaborateur/dirigeant_pme ne doit
    voir que les dossiers où il a une entrée Acces.
    """
    if user.role in ("admin_cabinet", "admin_plateforme"):
        dossiers = db.execute(select(Dossier)).scalars().all()
    else:
        dossiers = db.execute(
            select(Dossier).join(Acces, Acces.dossier_id == Dossier.id).where(Acces.utilisateur_id == uuid.UUID(user.id))
        ).scalars().all()

    rois = []
    nb_non_analyses = 0
    for d in dossiers:
        r = _roi_pour_dossier(db, d)
        if r is not None:
            rois.append(r)
        else:
            nb_non_analyses += 1

    return {
        "status": "ok",
        "nb_dossiers_total": len(dossiers),
        "nb_dossiers_non_analyses": nb_non_analyses,
        **agreger_roi_portefeuille(rois),
    }
