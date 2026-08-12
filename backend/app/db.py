"""
db.py — Connexion SQLAlchemy à la base applicative (schéma "app").

Réutilise la même instance Postgres/Supabase que pgvector (DATABASE_URL déjà
présent dans .env), mais dans un schéma logique séparé pour les données
métier (organisation, dossier, alertes, ...) par opposition au corpus fiscal
partagé (documents, articles) qui reste géré via corpus.db / pgvector.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL manquant dans .env — requis pour la base applicative.")

_SQLALCHEMY_URL = (
    DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    if DATABASE_URL.startswith("postgresql://")
    else DATABASE_URL
)

#: psycopg3 prépare automatiquement côté serveur toute requête exécutée plus de
#: `prepare_threshold` fois (5 par défaut), puis la réutilise par son nom
#: (`_pg3_0`, `_pg3_1`...). Derrière le pooler Supabase en mode TRANSACTION,
#: ce nom ne vaut rien : la transaction suivante peut être routée vers une
#: autre connexion serveur, qui n'a jamais préparé ce statement, et Postgres
#: répond `prepared statement "_pg3_0" does not exist`.
#:
#: Le déclencheur concret a été le contexte RLS reposé à chaque début de
#: transaction (db_session._reposer_contexte_tenant) : `SELECT set_config(...)`
#: franchit le seuil en quelques requêtes. Mais le piège préexistait pour
#: n'importe quelle requête assez fréquente — il attendait juste son tour.
#:
#: `None` désactive la préparation côté serveur. C'est le réglage attendu
#: derrière un pooler en mode transaction : on renonce à un cache de plan que
#: le pooler rend de toute façon inutilisable.
_connect_args = {"prepare_threshold": None} if "+psycopg:" in _SQLALCHEMY_URL else {}

engine = create_engine(_SQLALCHEMY_URL, pool_pre_ping=True, future=True, connect_args=_connect_args)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy de l'app."""
    pass


def get_db():
    """Dependency FastAPI : ouvre une session, la ferme après la requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
