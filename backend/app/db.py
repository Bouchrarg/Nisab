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

# Le projet utilise déjà psycopg v3 (voir vectorstore.py / requirements.txt), pas psycopg2.
# On force le driver dans l'URL SQLAlchemy pour rester cohérent, même si .env contient
# un DATABASE_URL "postgresql://" générique (format Supabase par défaut).
_SQLALCHEMY_URL = (
    DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    if DATABASE_URL.startswith("postgresql://")
    else DATABASE_URL
)

engine = create_engine(_SQLALCHEMY_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


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
