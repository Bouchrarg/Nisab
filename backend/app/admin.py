
from __future__ import annotations

import datetime
import os
import sqlite3
import subprocess
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["Administration"])

# Journal des exécutions du pipeline (session courante, non persisté)
_pipeline_log: list[dict] = []


def _project_root() -> str:
    # backend/app/admin.py -> backend/app -> backend -> racine du projet
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _corpus_db_path() -> str:
    return os.path.join(_project_root(), "corpus-pipeline", "data", "corpus.db")


def _scripts_dir() -> str:
    return os.path.join(_project_root(), "corpus-pipeline", "scripts")


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_corpus_db_path())
    conn.row_factory = sqlite3.Row
    return conn


class ValidateArticlesRequest(BaseModel):
    ids: Optional[list[int]] = None
    all_pending: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Article review & validation
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/articles")
def list_articles(
    statut: str = Query("a_verifier"),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    document_id: Optional[str] = None,
    q: Optional[str] = None,
):
    """Liste paginée des articles pour relecture admin."""
    db_path = _corpus_db_path()
    if not os.path.exists(db_path):
        return {"articles": [], "total": 0, "page": page, "pages": 0}

    offset = (page - 1) * limit
    clauses = ["statut = ?"]
    params: list = [statut]
    if document_id:
        clauses.append("document_id = ?")
        params.append(document_id)
    if q:
        clauses.append("(reference LIKE ? OR source_label LIKE ? OR texte LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    where = " AND ".join(clauses)

    conn = _db_connect()
    total = conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE {where}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT id, document_id, reference, source_label,
                   substr(texte, 1, 300) AS apercu, statut, date_extraction
            FROM articles WHERE {where}
            ORDER BY document_id, id LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    conn.close()

    pages = max(1, (total + limit - 1) // limit)
    return {
        "articles": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": pages,
    }


@router.get("/articles/{article_id}")
def get_article(article_id: int):
    conn = _db_connect()
    row = conn.execute(
        "SELECT id, document_id, reference, source_label, texte, statut, date_extraction FROM articles WHERE id=?",
        (article_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return dict(row)


@router.post("/articles/validate")
def validate_articles(body: ValidateArticlesRequest):
    """Marque des articles comme valides (relecture admin)."""
    if not body.all_pending and not body.ids:
        raise HTTPException(status_code=400, detail="Precisez ids ou all_pending=true")

    conn = _db_connect()
    if body.all_pending:
        cur = conn.execute("UPDATE articles SET statut='valide' WHERE statut='a_verifier'")
    else:
        placeholders = ",".join("?" for _ in body.ids)
        cur = conn.execute(
            f"UPDATE articles SET statut='valide' WHERE id IN ({placeholders}) AND statut='a_verifier'",
            body.ids,
        )
    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE statut='a_verifier'"
    ).fetchone()[0]
    conn.close()
    return {"validated": cur.rowcount, "remaining_pending": remaining}


@router.post("/articles/reject")
def reject_articles(body: ValidateArticlesRequest):
    """Supprime des articles jugés incorrects (decoupage erroné)."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="Precisez les ids a supprimer")

    conn = _db_connect()
    placeholders = ",".join("?" for _ in body.ids)
    cur = conn.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", body.ids)
    conn.commit()
    conn.close()
    return {"deleted": cur.rowcount}


@router.post("/articles/deduplicate")
def deduplicate_articles():
    """Supprime les doublons (meme document + meme reference)."""
    conn = _db_connect()
    before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.execute("""
        DELETE FROM articles
        WHERE id NOT IN (
            SELECT MAX(id) FROM articles GROUP BY document_id, reference
        )
    """)
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()
    return {"removed": before - after, "remaining": after}


@router.get("/documents")
def list_documents():
    """Documents sources disponibles (pour filtre relecture)."""
    db_path = _corpus_db_path()
    if not os.path.exists(db_path):
        return {"documents": []}
    conn = _db_connect()
    rows = conn.execute(
        "SELECT id, label, type, statut FROM documents ORDER BY id"
    ).fetchall()
    conn.close()
    return {"documents": [dict(r) for r in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# Corpus statistics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/corpus/stats")
def corpus_stats():
    """
    Retourne les statistiques du corpus local (SQLite).
    - Nombre de documents par type et statut
    - Nombre d'articles par statut
    - Dernier document téléchargé
    - Dernière vérification du Bulletin Officiel
    """
    db_path = _corpus_db_path()
    if not os.path.exists(db_path):
        return {
            "status": "no_db",
            "message": "Base locale non initialisée. Lancez d'abord init_db.py ou run_pipeline.py.",
        }
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        docs = cur.execute(
            "SELECT type, statut, COUNT(*) as n FROM documents GROUP BY type, statut"
        ).fetchall()
        arts = cur.execute(
            "SELECT statut, COUNT(*) as n FROM articles GROUP BY statut"
        ).fetchall()
        last_doc = cur.execute(
            "SELECT label, type, statut, date_telechargement "
            "FROM documents ORDER BY date_telechargement DESC LIMIT 1"
        ).fetchone()
        veille = cur.execute(
            "SELECT statut, COUNT(*) as n FROM veille_log GROUP BY statut"
        ).fetchall()
        last_check = cur.execute(
            "SELECT date_detection, statut FROM veille_log ORDER BY date_detection DESC LIMIT 1"
        ).fetchone()

        conn.close()
        return {
            "status": "ok",
            "documents": [dict(r) for r in docs],
            "articles": [dict(r) for r in arts],
            "total_articles": sum(r["n"] for r in arts),
            "valid_articles": next((r["n"] for r in arts if r["statut"] == "valide"), 0),
            "pending_articles": next((r["n"] for r in arts if r["statut"] == "a_verifier"), 0),
            "last_document": dict(last_doc) if last_doc else None,
            "veille_summary": [dict(r) for r in veille],
            "last_bo_check": last_check["date_detection"] if last_check else None,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline execution
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/pipeline/run")
def pipeline_run(auto_validate: bool = False, skip_download: bool = False):
    """
    Déclenche le pipeline complet :
    init_db → veille CGI → [download] → monitor_bo → extract → [validate] → ingest Supabase
    """
    script = os.path.join(_scripts_dir(), "run_pipeline.py")
    args = [sys.executable, script]
    if skip_download:
        args.append("--skip-download")
    if auto_validate:
        args.append("--auto-validate")

    ts = datetime.datetime.utcnow().isoformat()
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=600,
                                cwd=_scripts_dir())
        entry = {
            "ts": ts,
            "trigger": "manual_full",
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
        }
        _pipeline_log.append(entry)
        return {
            **entry,
            "output": result.stdout[-4000:],
            "error": result.stderr[-1000:] if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        _pipeline_log.append({"ts": ts, "trigger": "manual_full", "status": "timeout"})
        raise HTTPException(status_code=408, detail="Pipeline timeout (> 10 min)")
    except Exception as exc:
        _pipeline_log.append({"ts": ts, "trigger": "manual_full", "status": "exception"})
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/monitor/run")
def monitor_run():
    """
    Déclenche uniquement la veille du Bulletin Officiel (monitor_bo.py).
    Vérifie les nouveaux numéros et les télécharge si disponibles.
    Ne relance pas l'extraction ni l'ingestion Supabase.
    """
    script = os.path.join(_scripts_dir(), "monitor_bo.py")
    ts = datetime.datetime.utcnow().isoformat()
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=120,
            cwd=_scripts_dir(),
        )
        found_new = "Téléchargé" in result.stdout or "Nouveau" in result.stdout
        entry = {
            "ts": ts,
            "trigger": "monitor_bo",
            "status": "ok" if result.returncode == 0 else "error",
            "found_new_bulletins": found_new,
        }
        _pipeline_log.append(entry)
        return {**entry, "output": result.stdout[-2000:]}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Monitor timeout (> 2 min)")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/monitor/cgi/run")
def monitor_cgi_run():
    """Détecte et télécharge le CGI de la nouvelle année fiscale."""
    script = os.path.join(_scripts_dir(), "monitor_cgi.py")
    ts = datetime.datetime.utcnow().isoformat()
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=120,
            cwd=_scripts_dir(),
        )
        found_new = "Nouveau CGI detecte" in result.stdout
        entry = {
            "ts": ts,
            "trigger": "monitor_cgi",
            "status": "ok" if result.returncode == 0 else "error",
            "found_new_cgi": found_new,
        }
        _pipeline_log.append(entry)
        return {**entry, "output": result.stdout[-2000:]}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Monitor CGI timeout (> 2 min)")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ingest/run")
def ingest_run(include_pending: bool = False):
    """Synchronise les articles validés vers Supabase."""
    script = os.path.join(_project_root(), "backend", "scripts", "ingest_to_supabase.py")
    args = [sys.executable, script]
    if include_pending:
        args.append("--include-a-verifier")
    ts = datetime.datetime.utcnow().isoformat()
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=600,
            cwd=os.path.dirname(script),
        )
        entry = {
            "ts": ts, "trigger": "ingest", "status": "ok" if result.returncode == 0 else "error",
        }
        _pipeline_log.append(entry)
        return {**entry, "output": result.stdout[-2000:]}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Ingestion timeout (> 10 min)")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/pipeline/log")
def pipeline_log():
    """Retourne le journal des exécutions de cette session (20 dernières)."""
    return {"log": list(reversed(_pipeline_log[-20:]))}


# ─────────────────────────────────────────────────────────────────────────────
# Recommended sources catalog
# ─────────────────────────────────────────────────────────────────────────────

SOURCES_CATALOG = [
    {
        "id": "cgi_2026",
        "label": "Code Général des Impôts 2026",
        "type": "CGI",
        "status": "integre",
        "priority": "haute",
        "description": (
            "Texte de référence de la fiscalité marocaine — IS, TVA, IR, "
            "Taxe Professionnelle, droits d'enregistrement. "
            "Mis à jour chaque année par la Loi de Finances."
        ),
        "update_frequency": "Annuelle (Loi de Finances)",
        "impact": "Base indispensable du copilote fiscal",
    },
    {
        "id": "bo_lf_2026",
        "label": "Bulletin Officiel — Loi de Finances 2025-2026",
        "type": "BULLETIN_OFFICIEL",
        "status": "en_cours",
        "priority": "haute",
        "description": (
            "Amende le CGI chaque année avec les nouvelles mesures fiscales. "
            "Sans ce document, les réponses sur les taux et plafonds peuvent être obsolètes."
        ),
        "update_frequency": "Annuelle (publication en janvier)",
        "impact": "Réponses à jour sur taux TVA, IS, IR, plafonds 2026",
    },
    {
        "id": "bo_veille",
        "label": "Bulletin Officiel — Veille hebdomadaire automatique",
        "type": "BULLETIN_OFFICIEL",
        "status": "automatise",
        "priority": "haute",
        "description": (
            "Décrets d'application, arrêtés et circulaires publiés au BO. "
            "Détection et téléchargement automatiques via monitor_bo.py "
            "à chaque nouvelle parution."
        ),
        "update_frequency": "Hebdomadaire (détection automatique)",
        "impact": "Veille réglementaire continue",
    },
    {
        "id": "notes_circulaires_dgi",
        "label": "Notes Circulaires DGI",
        "type": "NOTE_CIRCULAIRE",
        "status": "non_integre",
        "priority": "haute",
        "description": (
            "La DGI publie des notes circulaires qui expliquent comment appliquer "
            "le CGI en pratique (procédures de contrôle, interprétations administratives). "
            "Essentiel pour des réponses opérationnelles sur les redressements."
        ),
        "update_frequency": "Irrégulière",
        "impact": "Réponses procédurales et défense en contrôle fiscal",
    },
    {
        "id": "conventions_fiscales",
        "label": "Conventions de Non-Double Imposition",
        "type": "CONVENTION_FISCALE",
        "status": "non_integre",
        "priority": "moyenne",
        "description": (
            "Traités bilatéraux Maroc-France, Maroc-Espagne, Maroc-Belgique… "
            "Couvrent les retenues à la source sur dividendes, intérêts, redevances, "
            "et les règles d'établissement stable."
        ),
        "update_frequency": "Stable (modifications rares)",
        "impact": "Réponses sur les opérations avec des non-résidents",
    },
    {
        "id": "lf_rectificative",
        "label": "Lois de Finances Rectificatives",
        "type": "BULLETIN_OFFICIEL",
        "status": "non_integre",
        "priority": "moyenne",
        "description": (
            "Modifications législatives exceptionnelles en cours d'année. "
            "Peu fréquentes mais impactantes sur les taux et les exonérations."
        ),
        "update_frequency": "Ponctuelle",
        "impact": "Précision sur les changements urgents en cours d'exercice",
    },
    {
        "id": "cgnc",
        "label": "Code Général de la Normalisation Comptable (CGNC)",
        "type": "REFERENTIEL_COMPTABLE",
        "status": "non_integre",
        "priority": "basse",
        "description": (
            "Référentiel comptable marocain — utile pour les questions de rattachement "
            "de charges, d'évaluation des actifs et d'amortissements."
        ),
        "update_frequency": "Stable",
        "impact": "Réponses sur le traitement comptable des opérations fiscales",
    },
]


@router.get("/corpus/sources")
def corpus_sources():
    """Catalogue des sources recommandées pour enrichir le corpus Nisab."""
    return {"sources": SOURCES_CATALOG}
