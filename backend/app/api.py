from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.generation import generate_answer
from app.intention import choisir_format_reponse, classifier_intention
from app.langue import detecter_langue
from app.auth import get_current_user, CurrentUser
from fastapi import Depends
from app.rag_retrieval import retrieve_sourced_articles
from app.text_cleaning import clean_article_text
from app.vectorstore import PgVectorStore, VectorStore

router = APIRouter()

# NOTE : ce routeur est désormais réservé aux endpoints qui
# portent sur le corpus fiscal PARTAGÉ (lecture seule, identique pour tous
# les tenants) : /health, /search, /law/feed. Tout ce qui touchait à des
# données de dossier (Odoo, audit, dashboard, calendrier, chat) a été
# déplacé vers app/routes_dossiers.py, où chaque endpoint est authentifié
# et scindé par dossier_id (plus de variables globales ni de cache fichier).


@lru_cache(maxsize=1)
def get_vectorstore() -> VectorStore:
    return PgVectorStore()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = Field(5, ge=1, le=15)

class GeneralChatRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = Field(5, ge=1, le=15)


@router.get("/health")
def health():
    try:
        return {"status": "ok", **get_vectorstore().stats()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/search")
def search(req: SearchRequest):
    store = get_vectorstore()
    matches = store.search(req.query, top_k=req.top_k)
    return {
        "query": req.query,
        "results": [
            {
                "id": m.id,
                "reference": m.reference,
                "source_label": m.source_label,
                "score": round(m.score, 4),
                "extrait": clean_article_text(m.texte)[:280],
                "texte_complet": clean_article_text(m.texte),
            }
            for m in matches
        ],
    }


@router.post("/chat/general")
def chat_general(req: GeneralChatRequest, user: CurrentUser = Depends(get_current_user)):
    # Meme mecanique que le chat scope dossier : la langue detectee sert a
    # traduire la requete vers le francais ET a rediger la reponse.
    langue = detecter_langue(req.query)

    # Pas de dossier ici, donc pas de régime IS/TVA connu : impossible de
    # calculer une échéance (voir /dossiers/{id}/chat pour ce chemin). On le
    # dit plutôt que d'envoyer la question au RAG, qui n'a pas la réponse et
    # ferait lire l'Art. 110 à un LLM en espérant qu'il improvise une date.
    if classifier_intention(req.query, langue) == "echeance":
        return {
            "query": req.query,
            "answer": "Les échéances fiscales dépendent du régime de votre dossier — ouvrez un dossier "
                      "et posez la question depuis son assistant, ou consultez directement son calendrier fiscal.",
            "sources": [], "langue": langue, "sourced": False, "intention": "echeance",
        }

    store = get_vectorstore()
    matches = retrieve_sourced_articles(store, req.query, label="general", top_k_final=req.top_k, langue=langue)

    sources = [
        {
            "id": m.id,
            "reference": m.reference,
            "source_label": m.source_label,
            "score": round(m.score, 4),
            "extrait": clean_article_text(m.texte)[:280],
            "texte_complet": clean_article_text(m.texte),
            "type": m.type,
        }
        for m in matches
    ]

    if not sources:
        return {"query": req.query, "answer": "Aucun article pertinent trouvé.", "sources": [], "langue": langue}

    try:
        answer = generate_answer(req.query, sources, langue=langue, format_reponse=choisir_format_reponse(sources))
    except Exception as exc:
        answer = f"Erreur lors de la génération (articles trouvés ci-dessous quand même). Détail : {exc}"

    return {"query": req.query, "answer": answer, "sources": sources, "langue": langue}

@router.get("/articles/by-reference")
def get_article_by_reference(reference: str):
    store = get_vectorstore()
    with store._conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, reference, source_label, texte
            FROM articles
            WHERE statut = 'valide' AND reference = %s
            LIMIT 1
            """,
            (reference,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Article introuvable dans le corpus actuel.")

    return {
        "id": row[0],
        "reference": row[1],
        "source_label": row[2],
        "texte_complet": clean_article_text(row[3]),
    }


@router.get("/corpus/sources")
def corpus_sources():
    """
    Documents distincts du corpus (un par `document_id`, ex: "cgi_2024",
    "bo_7465_bis_2025"), pour peupler un sélecteur de source d'audit
    (POST /dossiers/{id}/audit/run?document_id=...). Lit `source_label` /
    `date_version` sur `articles` (mêmes colonnes que /law/feed utilise déjà)
    plutôt que sur `documents` — une table `documents` existe bien côté
    Postgres (synchronisée par `ingest_to_supabase.py`), mais ces valeurs
    telles qu'attribuées à CHAQUE article sont ce qui doit rester affiché,
    pas la valeur générique du document source.
    """
    store = get_vectorstore()
    with store._conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT document_id, source_label, date_version
            FROM articles
            WHERE statut = 'valide' AND document_id IS NOT NULL
            ORDER BY date_version DESC NULLS LAST
            """
        )
        rows = cur.fetchall()
    return {
        "sources": [
            {"document_id": r[0], "label": r[1], "date_version": r[2]}
            for r in rows
        ]
    }


@router.get("/law/feed")
def law_feed(mode: str = "latest", limit: int = 5):
    """Retourne les documents légaux ingérés (corpus partagé, pas de scope tenant)."""
    try:
        store = get_vectorstore()
        with store._conn.cursor() as cur:
            if mode == "per_label":
                cur.execute(
                    """
                    SELECT id, source_label, reference, LEFT(texte, 200) AS apercu, statut, document_id
                    FROM (
                        SELECT id, source_label, reference, texte, statut, document_id,
                               ROW_NUMBER() OVER (PARTITION BY source_label ORDER BY id DESC) AS rn
                        FROM articles
                        WHERE statut = 'valide'
                    ) t
                    WHERE rn <= %s
                    ORDER BY source_label, id DESC
                    LIMIT 100
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            else:
                cur.execute(
                    """
                    SELECT id, source_label, reference, LEFT(texte, 200) AS apercu, statut, document_id
                    FROM articles
                    WHERE statut = 'valide'
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

        feed = []
        for row in rows:
            source_label = row[1] or ""
            reference = row[2] or ""
            apercu = (clean_article_text(row[3]) or "").replace("\n", " ")
            doc_id = row[5] or ""

            sl = source_label.lower()
            if "cgi" in sl or "code général" in sl:
                doc_type = "CGI"
            elif "bulletin" in sl or "bo " in sl or "b.o" in sl:
                doc_type = "Bulletin Officiel"
            elif "circulaire" in sl or "note" in sl:
                doc_type = "Circulaire DGI"
            elif "loi de finances" in sl or "lf " in sl:
                doc_type = "Loi de Finances"
            else:
                doc_type = "Document fiscal"

            feed.append({
                "id": doc_id,
                "title": source_label,
                "type": doc_type,
                "source_label": source_label,
                "reference": reference,
                "summary": apercu[:180] + ("…" if len(apercu) > 180 else ""),
            })

        return {"feed": feed, "mode": mode, "limit": limit}
    except Exception as exc:
        print(f"[law/feed] Erreur corpus : {exc}")
        return {"feed": []}
