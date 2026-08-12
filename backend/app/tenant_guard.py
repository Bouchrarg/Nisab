"""
tenant_guard.py — Contrôle d'accès au niveau dossier, partagé par tous les routeurs.

## Pourquoi ce module existe

La RLS (voir db_session.get_tenant_db) filtre par **organisation** : elle garantit
qu'un utilisateur du cabinet A ne verra jamais une ligne du cabinet B, quoi qu'il
mette dans l'URL. Mais elle ne dit rien de plus fin : à l'intérieur d'un même
cabinet, tous les dossiers appartiennent à la même organisation, donc la RLS les
laisse tous passer.

Or un collaborateur n'a pas accès à tous les dossiers de son cabinet — il a accès
à ceux pour lesquels une ligne `Acces` existe, avec un `niveau_droit` donné.
C'est cette seconde couche que ce module implémente. Les deux sont nécessaires et
ne se remplacent pas :

    RLS          → isolation entre organisations   (base de données, non contournable)
    tenant_guard → isolation entre dossiers        (application, au sein d'une org)

Les admins (`admin_cabinet`, `admin_plateforme`) court-circuitent la seconde
couche : ils voient tous les dossiers de leur organisation par construction.

Ce code était dupliqué à l'identique dans routes_dossiers.py et
routes_simulation.py. Le dupliquer une troisième fois pour les routeurs
d'ingestion et de corrections aurait fini par produire des divergences
silencieuses sur un contrôle d'accès — exactement le genre d'endroit où une
divergence ne se voit pas jusqu'au jour où elle se voit.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.models import Acces, Dossier

# Ordre croissant de confiance : lecture < ecriture < admin. Sert à comparer le
# niveau_droit accordé sur un Acces au niveau minimum requis par une route
# (ex. synchroniser Odoo demande "admin", consulter le dashboard "lecture").
NIVEAU_RANK = {"lecture": 0, "ecriture": 1, "admin": 2}

# Rôles qui n'ont pas besoin d'une ligne Acces : ils portent déjà l'autorité sur
# toute l'organisation.
ROLES_TRANSVERSES = ("admin_cabinet", "admin_plateforme")


def check_dossier_acces(
    db: Session,
    dossier_id: uuid.UUID,
    user: CurrentUser,
    min_niveau: str = "lecture",
) -> None:
    """
    Vérifie que `user` a bien un droit d'au moins `min_niveau` sur ce dossier.

    Ne renvoie rien : lève 404 si l'accès n'existe pas, 403 s'il existe mais est
    trop faible. Le 404 (et non 403) sur l'accès manquant est délibéré — répondre
    403 confirmerait à un utilisateur que le dossier existe, ce qui fuite de
    l'information sur le portefeuille du cabinet.
    """
    if user.role in ROLES_TRANSVERSES:
        return

    acces = db.execute(
        select(Acces).where(
            Acces.utilisateur_id == uuid.UUID(user.id),
            Acces.dossier_id == dossier_id,
        )
    ).scalar_one_or_none()

    if acces is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")

    if NIVEAU_RANK[acces.niveau_droit.value] < NIVEAU_RANK[min_niveau]:
        raise HTTPException(
            status_code=403,
            detail=f"Niveau d'accès insuffisant sur ce dossier (requis : {min_niveau}).",
        )


def get_dossier_or_404(
    db: Session,
    dossier_id: uuid.UUID,
    user: CurrentUser,
    min_niveau: str = "lecture",
) -> Dossier:
    """
    Charge le dossier et applique les deux couches de contrôle d'accès.

    Grâce à la RLS, un dossier d'une autre organisation n'est de toute façon
    jamais renvoyé par `.get()` : le 404 couvre donc indistinctement
    « n'existe pas » et « n'appartient pas à votre organisation ».
    """
    dossier = db.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    check_dossier_acces(db, dossier_id, user, min_niveau=min_niveau)
    return dossier
