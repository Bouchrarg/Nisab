"""
db_admin.py — Connexion SQLAlchemy dédiée aux routes admin_plateforme (app/admin.py).

Pourquoi une connexion séparée de db.py : les routes admin doivent voir les
données de TOUTES les organisations (vue plateforme — corpus, cabinets,
statistiques globales), ce qu'une policy RLS scopée par app.current_org_id
(voir db_session.py) ne peut structurellement pas faire — une policy RLS ne
filtre que sur UNE organisation à la fois, jamais "toutes". Le rôle
applicatif nisab_app (utilisé par db.py) a donc RLS activée par design ; ces
routes utilisent le rôle superuser à la place.

Pas un contournement de sécurité improvisé : le router /admin entier est
déjà protégé par require_role("admin_plateforme") (voir admin.py), donc
l'accès superuser ici est cohérent avec le rôle plutôt qu'une fuite.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

ADMIN_DATABASE_URL = os.environ.get("ADMIN_DATABASE_URL")
if not ADMIN_DATABASE_URL:
    raise RuntimeError("ADMIN_DATABASE_URL manquant dans .env — requis pour les routes admin_plateforme.")

_ADMIN_SQLALCHEMY_URL = (
    ADMIN_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    if ADMIN_DATABASE_URL.startswith("postgresql://")
    else ADMIN_DATABASE_URL
)

# Même désactivation des prepared statements que db.py : cette connexion passe
# par le même pooler, et le pooler ne garantit pas qu'une transaction retombe
# sur la connexion serveur qui a préparé le statement. Voir le commentaire
# détaillé dans db.py.
_admin_connect_args = {"prepare_threshold": None} if "+psycopg:" in _ADMIN_SQLALCHEMY_URL else {}

admin_engine = create_engine(
    _ADMIN_SQLALCHEMY_URL, pool_pre_ping=True, future=True, connect_args=_admin_connect_args
)

AdminSessionLocal = sessionmaker(bind=admin_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_admin_db():
    """Dependency FastAPI : ouvre une session sur la connexion superuser, la ferme après la requête."""
    db = AdminSessionLocal()
    try:
        yield db
    finally:
        db.close()
