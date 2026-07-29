"""
vectorstore.py - Recherche vectorielle sur Supabase (Postgres + pgvector).

"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import psycopg
from pgvector.psycopg import register_vector

from app.embeddings import embed_query
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ArticleMatch:
    id: int
    reference: str
    source_label: str
    document_id: str
    texte: str
    score: float


class VectorStore(ABC):
    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[ArticleMatch]:
        raise NotImplementedError

    @abstractmethod
    def stats(self) -> dict:
        raise NotImplementedError


class PgVectorStore(VectorStore):
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.environ["DATABASE_URL"]
        self._conn = psycopg.connect(self.database_url, autocommit=True, prepare_threshold=None)
        register_vector(self._conn)

    def search(self, query: str, top_k: int = 5) -> list[ArticleMatch]:
        q_emb = embed_query(query)
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, reference, source_label, document_id, texte,
                       1 - (embedding <=> %s) AS score
                FROM articles
                WHERE statut = 'valide' AND embedding IS NOT NULL
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (q_emb, q_emb, top_k),
            )
            rows = cur.fetchall()

        return [
            ArticleMatch(
                id=r[0], reference=r[1], source_label=r[2],
                document_id=r[3], texte=r[4], score=float(r[5]),
            )
            for r in rows
        ]

    def hybrid_search(self, query: str, top_k: int = 5, candidate_k: int = 20) -> list[ArticleMatch]:
        """
        Recherche hybride : combine le classement vectoriel dense (embed_query,
        similarité cosinus) avec un classement plein-texte PostgreSQL (mots-clés),
        fusionnés par Reciprocal Rank Fusion (RRF).

        Justification : le modèle multilingual-e5-base produit des similarités
        cosinus très compressées sur le corpus fiscal (souvent 0.81-0.84 pour des
        textes pertinents ET non pertinents), un effet d'anisotropie connu sur du
        texte juridique au vocabulaire partagé. Le classement (l'ORDRE des
        résultats) reste exploitable même quand le score brut ne l'est pas, donc
        RRF combine les deux CLASSEMENTS plutôt que les scores bruts eux-mêmes.

        RRF : score_final(article) = sum( 1 / (k + rang_dans_chaque_classement) )
        avec k=60 (valeur standard de la littérature, peu sensible en pratique).

        Note : la recherche plein-texte utilise to_tsvector('french', texte) à la
        volée (pas de colonne/indexe tsvector persisté, pour rester simple vu la
        taille actuelle du corpus ~400 articles). Si le corpus grossit fortement,
        prévoir une colonne générée + index GIN pour la performance.
        """
        q_emb = embed_query(query)
        k_rrf = 60

        with self._conn.cursor() as cur:
            # Classement dense (vectoriel)
            cur.execute(
                """
                SELECT id, reference, source_label, document_id, texte,
                       1 - (embedding <=> %s) AS score
                FROM articles
                WHERE statut = 'valide' AND embedding IS NOT NULL
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (q_emb, q_emb, candidate_k),
            )
            dense_rows = cur.fetchall()

            # Classement plein-texte (mots-clés, français)
            cur.execute(
                """
                SELECT id, reference, source_label, document_id, texte,
                       ts_rank(to_tsvector('french', texte), plainto_tsquery('french', %s)) AS score
                FROM articles
                WHERE statut = 'valide'
                  AND to_tsvector('french', texte) @@ plainto_tsquery('french', %s)
                ORDER BY score DESC
                LIMIT %s
                """,
                (query, query, candidate_k),
            )
            fulltext_rows = cur.fetchall()

        articles_by_id: dict[int, tuple] = {}
        rrf_scores: dict[int, float] = {}

        for rank, row in enumerate(dense_rows, start=1):
            articles_by_id[row[0]] = row
            rrf_scores[row[0]] = rrf_scores.get(row[0], 0.0) + 1.0 / (k_rrf + rank)

        for rank, row in enumerate(fulltext_rows, start=1):
            articles_by_id[row[0]] = row
            rrf_scores[row[0]] = rrf_scores.get(row[0], 0.0) + 1.0 / (k_rrf + rank)

        ranked_ids = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)[:top_k]

        return [
            ArticleMatch(
                id=articles_by_id[i][0], reference=articles_by_id[i][1],
                source_label=articles_by_id[i][2], document_id=articles_by_id[i][3],
                texte=articles_by_id[i][4], score=float(rrf_scores[i]),
            )
            for i in ranked_ids
        ]

    def stats(self) -> dict:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM articles WHERE statut = 'valide'")
            n_valide = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM articles WHERE embedding IS NOT NULL")
            n_embedded = cur.fetchone()[0]
        return {
            "backend": "supabase-pgvector",
            "model": "intfloat/multilingual-e5-base",
            "nb_articles_valides": n_valide,
            "nb_articles_embeddes": n_embedded,
        }