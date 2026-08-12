"""
clean_corpus_articles.py — Retire les artefacts d'extraction PDF (notes de
bas de page collées, ruptures de page) du texte des articles, DANS LA BASE
(contrairement à text_cleaning.py, qui ne nettoie qu'à l'affichage).

Nettoie DEUX copies pour rester cohérent :
1. corpus-pipeline/data/corpus.db (sqlite, source utilisée par
   ingest_to_supabase.py) — sinon la prochaine synchro écraserait ce
   nettoyage avec le texte sale d'origine (comparaison de hash sur le texte
   source, cf. ingest_to_supabase.py:texte_hash).
2. articles (Supabase/Postgres) — texte, texte_hash (même algorithme que
   ingest_to_supabase.py, pour que la prochaine synchro voie un hash
   identique et ne re-déclenche pas un ré-embedding inutile) et embedding
   (recalculé pour les lignes modifiées, pour rester cohérent avec le texte
   affiché/cité).

Usage (depuis backend/) :
    python -m scripts.clean_corpus_articles            # dry-run
    python -m scripts.clean_corpus_articles --confirm  # écrit réellement
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.embeddings import embed_passages
from app.text_cleaning import clean_article_text

CORPUS_DB_PATH = os.environ.get("CORPUS_DB_PATH", "")
if CORPUS_DB_PATH:
    if not os.path.isabs(CORPUS_DB_PATH):
        CORPUS_DB_PATH = str((BACKEND_ROOT / CORPUS_DB_PATH).resolve())
else:
    CORPUS_DB_PATH = str(BACKEND_ROOT.parent.parent / "corpus-pipeline" / "data" / "corpus.db")


def texte_hash(texte: str) -> str:
    """Même algorithme que ingest_to_supabase.py — pour que la prochaine
    synchro voie un hash identique sur le texte déjà nettoyé."""
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def clean_sqlite(confirm: bool) -> int:
    con = sqlite3.connect(CORPUS_DB_PATH)
    rows = con.execute("SELECT id, texte FROM articles").fetchall()
    changed = [(rid, clean_article_text(texte)) for rid, texte in rows if clean_article_text(texte) != texte]
    print(f"[sqlite] {len(changed)}/{len(rows)} article(s) à nettoyer ({CORPUS_DB_PATH})")
    if confirm and changed:
        con.executemany("UPDATE articles SET texte = ? WHERE id = ?", [(t, rid) for rid, t in changed])
        con.commit()
        print(f"[sqlite] {len(changed)} article(s) mis à jour.")
    con.close()
    return len(changed)


def clean_postgres(confirm: bool) -> int:
    database_url = os.environ["DATABASE_URL"]
    pg_con = psycopg.connect(database_url, autocommit=True, prepare_threshold=None)
    register_vector(pg_con)

    with pg_con.cursor() as cur:
        cur.execute("SELECT id, texte FROM articles WHERE statut = 'valide'")
        rows = cur.fetchall()

    changed = [(rid, texte, clean_article_text(texte)) for rid, texte in rows if clean_article_text(texte) != texte]
    print(f"[postgres] {len(changed)}/{len(rows)} article(s) à nettoyer")

    if not confirm or not changed:
        return len(changed)

    BATCH = 32
    with pg_con.cursor() as cur:
        for i in range(0, len(changed), BATCH):
            batch = changed[i : i + BATCH]
            embeddings = embed_passages([cleaned for _, _, cleaned in batch])
            for (rid, _old, cleaned), emb in zip(batch, embeddings):
                cur.execute(
                    """
                    UPDATE articles
                    SET texte = %s, texte_hash = %s, embedding = %s,
                        embedding_model = %s, embedded_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (cleaned, texte_hash(cleaned), emb, "intfloat/multilingual-e5-base", rid),
                )
            print(f"[postgres]   {min(i + BATCH, len(changed))}/{len(changed)} mis à jour + ré-embeddés")

    return len(changed)


def main():
    parser = argparse.ArgumentParser(description="Nettoie les artefacts d'extraction PDF dans le corpus (sqlite + Supabase).")
    parser.add_argument("--confirm", action="store_true", help="Écrit réellement (sinon dry-run).")
    args = parser.parse_args()

    clean_sqlite(args.confirm)
    clean_postgres(args.confirm)

    if not args.confirm:
        print("\nDry-run — relancer avec --confirm pour écrire réellement.")


if __name__ == "__main__":
    main()
