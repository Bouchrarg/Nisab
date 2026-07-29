"""
db_session.py — Bascule le contexte "tenant courant" sur une session Postgres,
pour que les policies Row-Level Security (voir migration 0001) filtrent
automatiquement chaque requête par organisation.

Utilisation typique (dans une dependency FastAPI, après authentification) :

    def get_tenant_db(db: Session = Depends(get_db), user=Depends(get_current_user)):
        set_tenant_context(db, user.organisation_id)
        return db
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db import get_db


def get_tenant_db(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Session:
    """
    Dependency FastAPI "tout-en-un" pour les routes protégées :
    ouvre une session DB, authentifie l'utilisateur, et positionne le
    contexte RLS sur son organisation. À utiliser à la place de get_db
    seul dès qu'une route touche des données de dossier/organisation.

        @router.get("/dossiers")
        def list_dossiers(db: Session = Depends(get_tenant_db)):
            return db.query(Dossier).all()  # déjà filtré par RLS
    """
    set_tenant_context(db, user.organisation_id)
    return db


def set_tenant_context(db: Session, organisation_id: str) -> None:
    """
    Positionne app.current_org_id pour la transaction en cours.
    SET LOCAL ne vit que le temps de la transaction courante : il faut
    l'appeler à chaque nouvelle session/requête, pas une seule fois au démarrage.
    """
    db.execute(text("SET LOCAL app.current_org_id = :org_id"), {"org_id": str(organisation_id)})


def clear_tenant_context(db: Session) -> None:
    """Repasse en mode 'aucun tenant' (utile pour les routes admin globales)."""
    db.execute(text("RESET app.current_org_id"))
