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
from app.metrics import mesurer
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
    #: Type du document source ('CGI' | 'BULLETIN_OFFICIEL' | 'NOTE_CIRCULAIRE'
    #: | ...), None si le JOIN vers `documents` n'a rien trouvé. Par défaut
    #: pour ne pas casser les constructeurs existants (hybrid_search) qui ne
    #: le renseignent pas.
    type: str | None = None
    #: Références CGI commentées, séparées par SEPARATEUR_REFERENCES
    #: (extract_circulaire.py) — uniquement renseigné pour type='NOTE_CIRCULAIRE'.
    #: Sert au post-filtre du chat (rag_retrieval.py) : une circulaire n'est
    #: jamais citée seule, seulement accompagnée d'un des articles CGI listés
    #: ici parmi les AUTRES résultats du même lot.
    articles_cgi_commentes: str | None = None


class VectorStore(ABC):
    @abstractmethod
    def search(
        self, query: str, top_k: int = 5, document_id: str | None = None,
        exclude_types: list[str] | None = None,
    ) -> list[ArticleMatch]:
        raise NotImplementedError

    @abstractmethod
    def stats(self) -> dict:
        raise NotImplementedError


class PgVectorStore(VectorStore):
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.environ["DATABASE_URL"]
        self._conn = psycopg.connect(self.database_url, autocommit=True, prepare_threshold=None)
        register_vector(self._conn)

    def search(
        self, query: str, top_k: int = 5, document_id: str | None = None,
        exclude_types: list[str] | None = None,
    ) -> list[ArticleMatch]:
        """
        `document_id` est optionnel et additif : `None` (défaut) préserve le
        comportement historique (recherche sur tout le corpus valide), utilisé
        par le chat (`rag_retrieval.py`) et par un audit non contraint. Fourni,
        il borne la recherche à UN document précis (ex: `cgi_2024`) — c'est ce
        qui permet d'auditer explicitement contre le millésime choisi plutôt
        que de laisser le RAG piocher sans distinction parmi toutes les années
        présentes dans le corpus.

        `exclude_types` retire du retrieval les articles dont le TYPE de
        document (`documents.type`) figure dans la liste — utilisé par
        `ai_auditor.py` avec `exclude_types=("NOTE_CIRCULAIRE",)` : une note
        circulaire engage l'administration, pas le contribuable, et ne peut
        pas fonder une anomalie à elle seule (règle d'architecture du projet,
        cf. extract_circulaire.py). L'exclure du pool de candidats de l'audit
        rend cette règle vraie par construction plutôt que par un filtre a
        posteriori sur la sortie du LLM — l'audit ne peut simplement jamais la
        voir. Le chat (`rag_retrieval.py`) n'exclut rien : c'est la seule
        couche où une circulaire peut apparaître, sous réserve d'être
        accompagnée d'un article CGI dans le même lot de résultats (filtre
        appliqué côté rag_retrieval.py, pas ici).
        """
        with mesurer("embedding"):
            q_emb = embed_query(query)
        with self._conn.cursor() as cur:
            with mesurer("retrieval_sql"):
                cur.execute(
                    """
                    SELECT a.id, a.reference, a.source_label, a.document_id, a.texte,
                           1 - (a.embedding <=> %s) AS score, d.type, a.articles_cgi_commentes
                    FROM articles a
                    LEFT JOIN documents d ON d.id = a.document_id
                    WHERE a.statut = 'valide' AND a.embedding IS NOT NULL
                      AND (%s::text IS NULL OR a.document_id = %s)
                      AND (%s::text[] IS NULL OR d.type IS NULL OR NOT (d.type = ANY(%s)))
                    ORDER BY a.embedding <=> %s
                    LIMIT %s
                    """,
                    (q_emb, document_id, document_id, exclude_types, exclude_types, q_emb, top_k),
                )
                rows = cur.fetchall()

        return [
            ArticleMatch(
                id=r[0], reference=r[1], source_label=r[2],
                document_id=r[3], texte=r[4], score=float(r[5]),
                type=r[6], articles_cgi_commentes=r[7],
            )
            for r in rows
        ]

    def get_document_label(self, document_id: str) -> str | None:
        """
        Libellé lisible + version d'un `document_id` donné (ex: "CGI 2026
        (version 2026-01-01)"), pour affichage sur une citation quand l'audit
        a été contraint à un document précis via `search(document_id=...)`.

        Lit `source_label`/`date_version` sur `articles` plutôt que sur
        `documents` : ce sont les valeurs telles qu'attribuées à CET article
        au moment de son extraction (mêmes colonnes que `/law/feed` (api.py)
        utilise déjà), pas la valeur générique du document. Une table
        `documents` existe bel et bien côté Postgres (synchronisée par
        `ingest_to_supabase.py`, cf. son upsert) — le correctif d'un ancien
        commentaire ici affirmait le contraire à tort ; elle est d'ailleurs
        celle que `search()` ci-dessus rejoint pour `exclude_types` et `type`.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_label, date_version FROM articles WHERE document_id = %s LIMIT 1",
                (document_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        source_label, date_version = row
        version = f" (version {date_version})" if date_version else ""
        return f"{source_label}{version}" if source_label else None

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

    def get_texts_by_references(self, references: list[str]) -> dict[str, str]:
        """
        Texte complet des articles pour un lot de références exactes
        (`articles.reference`) — un seul aller-retour DB au lieu d'un par
        référence. Utilisé par control_simulator.py pour classifier les
        alertes par thème à partir du titre officiel de l'article plutôt
        que du seul texte libre généré par l'audit.
        """
        if not references:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT reference, texte
                FROM articles
                WHERE statut = 'valide' AND reference = ANY(%s)
                """,
                (references,),
            )
            return {ref: texte for ref, texte in cur.fetchall()}

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