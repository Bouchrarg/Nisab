"""
ingest_to_supabase.py — Synchronise corpus-pipeline/data/corpus.db vers Supabase.

Idempotent : à relancer à chaque nouvel article ou document ajouté au
pipeline local. Ne ré-embedde que ce qui a changé (comparaison de hash),
donc le coût CPU reste maîtrisé même quand le corpus grossit beaucoup.

Usage :
    export DATABASE_URL=postgresql://...
    python scripts/ingest_to_supabase.py [--include-a-verifier]
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

import psycopg
from dotenv import dotenv_values, load_dotenv
from pgvector.psycopg import register_vector

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.embeddings import embed_passages


def get_database_url() -> str:
    values = dotenv_values(BACKEND_ROOT / ".env")
    raw_value = (values.get("DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if raw_value.startswith("DATABASE_URL="):
        raw_value = raw_value.split("=", 1)[1].strip()
    raw_value = raw_value.strip().strip('"').strip("'")
    if raw_value:
        os.environ["DATABASE_URL"] = raw_value
    return raw_value

CORPUS_DB_PATH = os.environ.get("CORPUS_DB_PATH", "")
if CORPUS_DB_PATH:
    if not os.path.isabs(CORPUS_DB_PATH):
        CORPUS_DB_PATH = str((BACKEND_ROOT / CORPUS_DB_PATH).resolve())
else:
    CORPUS_DB_PATH = str(Path(__file__).resolve().parents[2] / "corpus-pipeline" / "data" / "corpus.db")


def normalize_database_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.hostname or parsed.password is None:
        return raw_url

    encoded_password = quote(parsed.password, safe="")
    if parsed.password == encoded_password:
        return raw_url

    auth = f"{quote(parsed.username or '', safe='')}:{encoded_password}" if parsed.username else encoded_password
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"

    updated = parsed._replace(netloc=f"{auth}@{host}")
    if "sslmode" not in updated.query:
        query = updated.query + ("&" if updated.query else "") + "sslmode=require"
        updated = updated._replace(query=query)

    return urlunparse(updated)


def texte_hash(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _ensure_sqlite_circulaire_column(conn: sqlite3.Connection) -> None:
    """
    Même colonne, même idempotence que extract_circulaire.py::ensure_schema
    (dupliquée plutôt qu'importée : ce script vit dans backend/scripts, l'autre
    dans corpus-pipeline/scripts — deux projets distincts, cf. la même
    convention déjà posée pour text_cleaning.py). Nécessaire ici aussi : ce
    script lit `articles.articles_cgi_commentes` par SELECT explicite plus
    bas, qui échouerait sur une base SQLite où aucune circulaire n'a encore
    jamais été uploadée (colonne inexistante).
    """
    try:
        conn.execute("ALTER TABLE articles ADD COLUMN articles_cgi_commentes TEXT")
        conn.commit()
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def _ensure_sqlite_statut_juridique_column(conn: sqlite3.Connection) -> None:
    """
    Même idempotence que _ensure_sqlite_circulaire_column, pour
    `documents.statut_juridique` (cf. admin.py::qualifier_document / Lot 2.3).
    """
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN statut_juridique TEXT")
        conn.commit()
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def main(include_a_verifier: bool):
    sqlite_con = sqlite3.connect(CORPUS_DB_PATH)
    _ensure_sqlite_circulaire_column(sqlite_con)
    _ensure_sqlite_statut_juridique_column(sqlite_con)
    database_url = normalize_database_url(get_database_url())
    try:
        pg_con = psycopg.connect(database_url, autocommit=True, prepare_threshold=None)
    except Exception as exc:
        print("Échec de connexion à la base de données.")
        print(f"URL utilisée : {database_url}")
        print(f"Erreur : {exc}")
        raise
    register_vector(pg_con)

    # `articles.articles_cgi_commentes` (notes circulaires DGI, cf.
    # corpus-pipeline/scripts/extract_circulaire.py) n'existe pas dans le
    # schéma Postgres historique — cette table vit hors Alembic (voir
    # migration 92ce87978d93), donc son évolution passe par ce genre
    # d'ALTER idempotent plutôt que par une révision Alembic. IF NOT EXISTS
    # rend l'appel sûr à chaque exécution, y compris sur une base qui l'a déjà.
    with pg_con.cursor() as cur:
        cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS articles_cgi_commentes TEXT")
        # cf. admin.py::qualifier_document (Lot 2.3) — 'en_vigueur' |
        # 'remplacee_par:<document_id>', jamais renseigné pour un CGI.
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS statut_juridique TEXT")

    # 1. Sync documents
    docs = sqlite_con.execute(
        "SELECT id, label, type, url, date_version, statut, statut_juridique FROM documents"
    ).fetchall()
    with pg_con.cursor() as cur:
        for d in docs:
            cur.execute(
                """
                INSERT INTO documents (id, label, type, url, date_version, statut, statut_juridique)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label, statut = EXCLUDED.statut,
                    date_version = EXCLUDED.date_version,
                    statut_juridique = EXCLUDED.statut_juridique
                """,
                d,
            )
    print(f"{len(docs)} document(s) synchronisé(s)")

    # 2. Charger les articles éligibles
    statuts = ("valide", "a_verifier") if include_a_verifier else ("valide",)
    placeholders = ",".join("?" for _ in statuts)
    articles = sqlite_con.execute(
        f"""SELECT document_id, reference, texte, source_label, date_version, statut, articles_cgi_commentes
            FROM articles WHERE statut IN ({placeholders})""",
        statuts,
    ).fetchall()

    # 3. Déterminer lesquels sont nouveaux ou modifiés (comparaison de hash)
    to_embed = []
    unchanged = 0
    with pg_con.cursor() as cur:
        for document_id, reference, texte, source_label, date_version, statut, articles_cgi_commentes in articles:
            h = texte_hash(texte)
            cur.execute(
                "SELECT texte_hash FROM articles WHERE document_id=%s AND reference=%s",
                (document_id, reference),
            )
            row = cur.fetchone()
            if row and row[0] == h:
                unchanged += 1
                continue
            to_embed.append((document_id, reference, texte, h, source_label, date_version, statut, articles_cgi_commentes))

    print(f"{unchanged} article(s) inchangé(s), {len(to_embed)} à (ré)embedder")

    if not to_embed:
        print("Rien à faire.")
        return

    # 4. Embedding par batch (CPU) — batch de 32 pour rester raisonnable en mémoire
    BATCH = 32
    with pg_con.cursor() as cur:
        for i in range(0, len(to_embed), BATCH):
            batch = to_embed[i : i + BATCH]
            embeddings = embed_passages([b[2] for b in batch])
            for (document_id, reference, texte, h, source_label, date_version, statut, articles_cgi_commentes), emb in zip(
                batch, embeddings
            ):
                cur.execute(
                    """
                    INSERT INTO articles
                        (document_id, reference, texte, texte_hash, source_label,
                         date_version, statut, embedding, embedding_model, embedded_at,
                         articles_cgi_commentes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
                    ON CONFLICT (document_id, reference) DO UPDATE SET
                        texte = EXCLUDED.texte, texte_hash = EXCLUDED.texte_hash,
                        statut = EXCLUDED.statut, embedding = EXCLUDED.embedding,
                        embedding_model = EXCLUDED.embedding_model,
                        articles_cgi_commentes = EXCLUDED.articles_cgi_commentes,
                        embedded_at = now(), updated_at = now()
                    """,
                    (document_id, reference, texte, h, source_label, date_version,
                     statut, emb, "intfloat/multilingual-e5-base", articles_cgi_commentes),
                )
            print(f"  {min(i + BATCH, len(to_embed))}/{len(to_embed)} embeddés")

    print("Terminé.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-a-verifier", action="store_true")
    args = parser.parse_args()
    main(include_a_verifier=args.include_a_verifier)