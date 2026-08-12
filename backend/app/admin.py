
from __future__ import annotations

import datetime
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import unicodedata
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user, require_role
from app.db_admin import get_admin_db
from app.models import (
    AlerteRisque,
    Dossier,
    Echeance,
    Invitation,
    Organisation,
    RoleUtilisateur,
    SimulationControle,
    StatutAlerte,
    StatutInvitation,
    TypeOrganisation,
    Utilisateur,
)
from app.routes_invitations import INVITATION_VALIDITY_DAYS
from app.veille import diffuser as diffuser_veille


router = APIRouter(prefix="/admin", tags=["Administration"], dependencies=[Depends(require_role("admin_plateforme"))])

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
        "SELECT id, label, type, statut, date_version, statut_juridique FROM documents ORDER BY id"
    ).fetchall()
    conn.close()
    return {"documents": [dict(r) for r in rows]}


def _ensure_documents_columns(conn: sqlite3.Connection) -> None:
    """
    `statut_juridique` n'existe pas dans le schéma historique (init_db.py) —
    même idempotence que extract_circulaire.py::ensure_schema (SQLite n'a pas
    ADD COLUMN IF NOT EXISTS, on avale l'erreur "duplicate column").

    Uniquement significatif pour BO et notes circulaires : un CGI n'est
    jamais "remplacé", ses millésimes coexistent côté à côté (cgi_2024,
    cgi_2025, cgi_2026...) — cf. règle d'architecture. Cette colonne ne
    s'applique donc jamais aux documents CGI (refusé par la route PATCH
    ci-dessous), pour ne pas ouvrir une deuxième façon, incohérente avec la
    première, de dire qu'un millésime CGI est dépassé.
    """
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN statut_juridique TEXT")
        conn.commit()
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


class DocumentQualificationRequest(BaseModel):
    #: Date de PUBLICATION réelle (YYYY-MM-DD), à confirmer par un humain
    #: après lecture du PDF — cf. monitor_bo.py, qui ne l'invente plus.
    date_version: Optional[str] = None
    #: 'en_vigueur' | 'remplacee_par:<document_id>'. None = ne pas modifier.
    statut_juridique: Optional[str] = None


@router.patch("/documents/{document_id}")
def qualifier_document(document_id: str, req: DocumentQualificationRequest):
    """
    Confirme la date de publication réelle et/ou le statut juridique d'un
    document non-CGI — le geste humain qui referme la boucle ouverte par
    monitor_bo.py : un BO fraîchement détecté est enregistré avec
    `date_version=NULL` (date de publication réellement inconnue à ce
    stade) plutôt qu'avec la date de détection, qui aurait fait raisonner la
    veille sur une chronologie fausse.
    """
    if req.date_version is None and req.statut_juridique is None:
        raise HTTPException(status_code=400, detail="Fournissez date_version et/ou statut_juridique.")
    if req.date_version is not None:
        try:
            datetime.date.fromisoformat(req.date_version.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="date_version doit être au format YYYY-MM-DD.")

    conn = _db_connect()
    _ensure_documents_columns(conn)
    row = conn.execute("SELECT type FROM documents WHERE id=?", (document_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Document introuvable.")
    if row["type"] == "CGI":
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Un document CGI ne se qualifie pas ainsi — ses millésimes coexistent côté à côté, "
                   "ils ne sont jamais marqués remplacés (cf. règle d'architecture du projet).",
        )

    updates, params = [], []
    if req.date_version is not None:
        updates.append("date_version = ?")
        params.append(req.date_version.strip())
    if req.statut_juridique is not None:
        updates.append("statut_juridique = ?")
        params.append(req.statut_juridique.strip())
    params.append(document_id)
    conn.execute(f"UPDATE documents SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    updated = dict(conn.execute(
        "SELECT id, label, type, statut, date_version, statut_juridique FROM documents WHERE id=?", (document_id,)
    ).fetchone())
    conn.close()
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Notes circulaires DGI — 3ᵉ couche du corpus (upload manuel)
#
# CGI = la norme (ce qui est dû) ; Bulletin Officiel = la provenance
# temporelle (depuis quand) ; note circulaire DGI = l'interprétation par
# l'administration de sa propre application (procédures, tolérances,
# exemples). Contrairement au CGI/BO, une circulaire n'a pas la structure
# "Article N" — extract_corpus.py (découpage par ARTICLE_PATTERN) ne lui
# correspond pas. Chaque circulaire devient donc UN SEUL article en base,
# rattaché explicitement aux références CGI qu'elle commente
# (`articles_cgi_commentes`), saisies ici par l'admin plutôt que devinées.
#
# Ce rattachement n'est pas cosmétique : c'est ce qui permet à
# rag_retrieval._filtrer_circulaires_isolees d'empêcher qu'une circulaire
# soit citée SEULE (elle engage l'administration, pas le contribuable, et ne
# peut pas contredire le CGI), et à ai_auditor.py de l'exclure entièrement du
# retrieval de l'audit (exclude_types=TYPES_EXCLUS_AUDIT) — une circulaire ne
# fonde jamais une anomalie à elle seule.
#
# Extraction déléguée à un script du pipeline (extract_circulaire.py) via
# subprocess, comme le reste de ce fichier (pipeline_run, monitor_run,
# ingest_run) : admin.py n'importe jamais directement du code corpus-pipeline.
# ─────────────────────────────────────────────────────────────────────────────

_EXTENSIONS_CIRCULAIRE = (".pdf",)
#: Une note circulaire est un texte administratif, pas un scan haute
#: résolution : la même marge que le modèle CSV serait généreuse, celle de
#: l'OCR (5 Mo) est la bonne taille pour un PDF texte de quelques pages.
_TAILLE_MAX_OCTETS_CIRCULAIRE = 5 * 1024 * 1024


def _slugify_document_id(reference: str) -> str:
    """'Note circulaire n° 728' -> 'note_circulaire_728' (ids de document
    Alphanumériques uniquement, cohérent avec 'cgi_2026' / 'bo_7465_bis_2025')."""
    normalized = unicodedata.normalize("NFKD", reference).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_").lower()
    return slug or "circulaire"


@router.post("/corpus/circulaires/upload")
async def upload_circulaire(
    label: str = Form(..., description='Ex: "Note circulaire n° 728"'),
    reference: str = Form(..., description="Référence citée dans les réponses de l'assistant"),
    date_version: str = Form(..., description="Date de PUBLICATION de la circulaire, YYYY-MM-DD"),
    articles_cgi_commentes: str = Form(..., description="Références CGI commentées, séparées par des virgules"),
    fichier: UploadFile = File(...),
):
    """
    Dépose un PDF de note circulaire DGI et déclenche son extraction
    (corpus-pipeline/scripts/extract_circulaire.py), en `statut='a_verifier'`
    comme tout nouvel article — la relecture (`POST /admin/articles/validate`)
    reste le geste qui la rend citable par l'assistant, exactement comme pour
    le CGI/BO.
    """
    nom = (fichier.filename or "circulaire.pdf").strip()
    if not nom.lower().endswith(_EXTENSIONS_CIRCULAIRE):
        raise HTTPException(status_code=400, detail="Seul le PDF est accepté pour une note circulaire.")

    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(contenu) > _TAILLE_MAX_OCTETS_CIRCULAIRE:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (limite 5 Mo).")

    try:
        datetime.date.fromisoformat(date_version.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="date_version doit être au format YYYY-MM-DD.")

    references = [r.strip() for r in articles_cgi_commentes.split(",") if r.strip()]
    if not references:
        # Non négociable, cf. le bandeau ci-dessus : sans rattachement, la
        # circulaire ne pourrait jamais être filtrée correctement au
        # retrieval et resterait indéfiniment invisible du chat (le filtre
        # d'isolement l'écarterait systématiquement) — mieux vaut refuser
        # l'upload que produire un article mort.
        raise HTTPException(status_code=400, detail="Au moins un article CGI commenté est requis.")

    document_id = f"note_circulaire_{_slugify_document_id(reference)}"
    raw_pdf_dir = os.path.join(_project_root(), "corpus-pipeline", "data", "raw_pdfs")
    os.makedirs(raw_pdf_dir, exist_ok=True)
    pdf_path = os.path.join(raw_pdf_dir, f"{document_id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(contenu)

    script = os.path.join(_scripts_dir(), "extract_circulaire.py")
    args = [
        sys.executable, script,
        "--pdf", pdf_path,
        "--document-id", document_id,
        "--label", label,
        "--reference", reference,
        "--date-version", date_version.strip(),
        "--articles-cgi-commentes", ",".join(references),
    ]
    ts = datetime.datetime.utcnow().isoformat()
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120, cwd=_scripts_dir())
        entry = {
            "ts": ts, "trigger": "upload_circulaire", "document_id": document_id,
            "status": "ok" if result.returncode == 0 else "error",
        }
        _pipeline_log.append(entry)
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Extraction en échec : {result.stdout[-500:]}\n{result.stderr[-500:]}",
            )
        return {**entry, "output": result.stdout[-2000:], "articles_cgi_commentes": references}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Extraction timeout (> 2 min)")


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


class DiffusionVeilleRequest(BaseModel):
    #: ISO 8601. None = tout le corpus validé (première diffusion sur un corpus
    #: déjà constitué). En exploitation, la date du dernier run.
    since: Optional[str] = None
    #: Par défaut True : on ne notifie pas de vrais cabinets par accident.
    dry_run: bool = True
    limite_articles: Optional[int] = None


@router.post("/veille/diffuser")
def veille_diffuser(req: DiffusionVeilleRequest, db: Session = Depends(get_admin_db)):
    """
    Relie les articles nouvellement validés aux dossiers qui les citent déjà.

    Utilise `get_admin_db` et non `get_tenant_db` : c'est la SEULE route du
    produit dans ce cas, et c'est délibéré. La diffusion doit écrire des
    notifications pour les dossiers de toutes les organisations ; sous contexte
    RLS elle n'en verrait qu'une. Le garde-fou reste le `require_role
    ("admin_plateforme")` porté par le routeur entier (voir sa déclaration).

    `dry_run` vaut True par défaut : on regarde qui serait notifié avant de
    notifier. Passer `dry_run: false` écrit réellement.
    """
    corpus_path = _corpus_db_path()
    if not os.path.exists(corpus_path):
        raise HTTPException(status_code=400, detail=f"Corpus introuvable : {corpus_path}")
    try:
        return diffuser_veille(
            db, corpus_path,
            since_iso=req.since, dry_run=req.dry_run, limite_articles=req.limite_articles,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diffusion de la veille en échec : {exc}")


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
        # "en_cours" et non "automatise" : contrairement au BO (monitor_bo.py),
        # l'ingestion est un upload manuel par circulaire (POST
        # /admin/corpus/circulaires/upload) — pas de découverte automatique
        # équivalente à tax.gov.ma pour l'instant (portail dynamique, hors
        # périmètre, cf. corpus-pipeline/README.md).
        "status": "en_cours",
        "priority": "haute",
        "description": (
            "La DGI publie des notes circulaires qui expliquent comment appliquer "
            "le CGI en pratique (procédures de contrôle, interprétations administratives). "
            "Essentiel pour des réponses opérationnelles sur les redressements. "
            "Rattachées explicitement aux articles CGI qu'elles commentent — jamais "
            "citées seules (une circulaire engage l'administration, pas le contribuable)."
        ),
        "update_frequency": "Irrégulière (upload manuel par circulaire)",
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


# ─────────────────────────────────────────────────────────────────────────────
# Vue plateforme : organisations, utilisateurs, dossiers, tous tenants confondus
#
# IMPORTANT (même limite que documentée dans la migration initiale) : ces
# requêtes lisent volontairement across-tenant (aucun set_tenant_context
# n'est appelé) — c'est le but d'un back-office admin_plateforme. Tant que
# DATABASE_URL pointe vers un rôle Postgres avec BYPASSRLS (cas par défaut
# d'une connexion Supabase), la RLS ne bloque rien ici. Si un rôle applicatif
# dédié sans BYPASSRLS est mis en place plus tard (voir la note dans
# migrations/versions/834f91da7e7e...), il faudra alors soit garder un rôle
# séparé pour ces routes admin, soit ajouter une policy explicite
# "admin_plateforme voit tout". Pas fait ici pour ne pas complexifier le MVP.
# ─────────────────────────────────────────────────────────────────────────────

def _org_dict(o: Organisation, nb_users: int = 0, nb_dossiers: int = 0) -> dict:
    return {
        "id": str(o.id),
        "nom": o.nom,
        "type_organisation": o.type_organisation.value if hasattr(o.type_organisation, "value") else o.type_organisation,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "nb_users": nb_users,
        "nb_dossiers": nb_dossiers,
    }


@router.get("/platform/overview")
def platform_overview(db: Session = Depends(get_admin_db)):
    """
    KPIs globaux de la plateforme, tous cabinets/PME confondus : organisations,
    utilisateurs (par rôle), dossiers, alertes de risque, échéances,
    simulations de contrôle, plus un flux d'activité récente pour donner à
    l'admin_plateforme un overview complet en un seul appel.
    """
    total_orgs = db.scalar(select(func.count()).select_from(Organisation)) or 0
    nb_cabinets = db.scalar(
        select(func.count()).select_from(Organisation).where(Organisation.type_organisation == TypeOrganisation.cabinet)
    ) or 0
    nb_pme = db.scalar(
        select(func.count()).select_from(Organisation).where(Organisation.type_organisation == TypeOrganisation.pme)
    ) or 0

    total_users = db.scalar(select(func.count()).select_from(Utilisateur)) or 0
    users_by_role = {
        r.value: 0 for r in RoleUtilisateur
    }
    for role, n in db.execute(select(Utilisateur.role, func.count()).group_by(Utilisateur.role)).all():
        users_by_role[role.value if hasattr(role, "value") else role] = n

    total_dossiers = db.scalar(select(func.count()).select_from(Dossier)) or 0

    total_alertes = db.scalar(select(func.count()).select_from(AlerteRisque)) or 0
    # « Ouverte » ne suffit pas : une alerte disparue des données comptables passe
    # actif=False et garde son statut (on ne DELETE jamais, cf. AlerteRisque.actif
    # dans models.py). Sans le filtre actif, l'overview plateforme continuerait de
    # compter et de chiffrer des anomalies que le dernier audit ne détecte plus —
    # d'où un montant d'exposition figé alors que le dashboard dossier affiche 0.
    alerte_en_cours = (AlerteRisque.statut == StatutAlerte.ouverte, AlerteRisque.actif.is_(True))
    alertes_ouvertes = db.scalar(
        select(func.count()).select_from(AlerteRisque).where(*alerte_en_cours)
    ) or 0
    alertes_par_niveau = {"faible": 0, "moyen": 0, "eleve": 0}
    for niveau, n in db.execute(
        select(AlerteRisque.niveau_risque, func.count())
        .where(*alerte_en_cours)
        .group_by(AlerteRisque.niveau_risque)
    ).all():
        alertes_par_niveau[niveau.value if hasattr(niveau, "value") else niveau] = n
    exposition_totale = db.scalar(
        select(func.coalesce(func.sum(AlerteRisque.montant_exposition), 0)).where(*alerte_en_cours)
    ) or 0

    total_simulations = db.scalar(select(func.count()).select_from(SimulationControle)) or 0

    total_echeances = db.scalar(select(func.count()).select_from(Echeance)) or 0
    echeances_a_venir = db.scalar(
        select(func.count()).select_from(Echeance).where(Echeance.statut == "a_venir")
    ) or 0

    # Organisations les plus récentes, avec leurs compteurs
    recent_orgs = db.execute(select(Organisation).order_by(Organisation.created_at.desc()).limit(6)).scalars().all()
    recent_organisations = []
    for o in recent_orgs:
        nb_u = db.scalar(select(func.count()).select_from(Utilisateur).where(Utilisateur.organisation_id == o.id)) or 0
        nb_d = db.scalar(select(func.count()).select_from(Dossier).where(Dossier.organisation_id == o.id)) or 0
        recent_organisations.append(_org_dict(o, nb_u, nb_d))

    # Utilisateurs les plus récents, avec le nom de leur organisation
    recent_users_rows = db.execute(
        select(Utilisateur, Organisation.nom)
        .join(Organisation, Organisation.id == Utilisateur.organisation_id)
        .order_by(Utilisateur.created_at.desc())
        .limit(8)
    ).all()
    recent_users = [
        {
            "id": str(u.id),
            "nom_complet": u.nom_complet,
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else u.role,
            "organisation_nom": org_nom,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u, org_nom in recent_users_rows
    ]

    # Dossiers récents (activité côté data), tous cabinets confondus
    recent_dossiers_rows = db.execute(
        select(Dossier, Organisation.nom)
        .join(Organisation, Organisation.id == Dossier.organisation_id)
        .order_by(Dossier.created_at.desc())
        .limit(6)
    ).all()
    recent_dossiers = [
        {
            "id": str(d.id),
            "raison_sociale": d.raison_sociale,
            "secteur_activite": d.secteur_activite,
            "organisation_nom": org_nom,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d, org_nom in recent_dossiers_rows
    ]

    # Alertes de risque récentes, tous dossiers confondus
    # Même filtre actif que les KPIs ci-dessus : afficher une alerte désactivée
    # avec son statut « ouverte » ferait croire à une anomalie encore présente.
    recent_alertes_rows = db.execute(
        select(AlerteRisque, Dossier.raison_sociale, Organisation.nom)
        .join(Dossier, Dossier.id == AlerteRisque.dossier_id)
        .join(Organisation, Organisation.id == Dossier.organisation_id)
        .where(AlerteRisque.actif.is_(True))
        .order_by(AlerteRisque.created_at.desc())
        .limit(6)
    ).all()
    recent_alertes = [
        {
            "id": str(a.id),
            "titre": a.titre,
            "niveau_risque": a.niveau_risque.value if hasattr(a.niveau_risque, "value") else a.niveau_risque,
            "statut": a.statut.value if hasattr(a.statut, "value") else a.statut,
            "dossier_raison_sociale": raison_sociale,
            "organisation_nom": org_nom,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a, raison_sociale, org_nom in recent_alertes_rows
    ]

    return {
        "organisations": {"total": total_orgs, "cabinets": nb_cabinets, "pme": nb_pme},
        "utilisateurs": {"total": total_users, "par_role": users_by_role},
        "dossiers": {"total": total_dossiers},
        "alertes": {
            "total": total_alertes,
            "ouvertes": alertes_ouvertes,
            "par_niveau": alertes_par_niveau,
            "exposition_totale_mad": float(exposition_totale),
        },
        "simulations": {"total": total_simulations},
        "echeances": {"total": total_echeances, "a_venir": echeances_a_venir},
        "recent_organisations": recent_organisations,
        "recent_users": recent_users,
        "recent_dossiers": recent_dossiers,
        "recent_alertes": recent_alertes,
    }


@router.get("/platform/organisations")
def list_organisations(
    q: Optional[str] = None,
    type_organisation: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_admin_db),
):
    """Liste paginée des organisations (cabinets + PME), avec compteurs."""
    base_filters = []
    if q:
        base_filters.append(Organisation.nom.ilike(f"%{q}%"))
    if type_organisation:
        base_filters.append(Organisation.type_organisation == type_organisation)

    count_stmt = select(func.count()).select_from(Organisation)
    for f in base_filters:
        count_stmt = count_stmt.where(f)
    total = db.scalar(count_stmt) or 0

    stmt = select(Organisation).order_by(Organisation.created_at.desc())
    for f in base_filters:
        stmt = stmt.where(f)
    stmt = stmt.limit(limit).offset((page - 1) * limit)
    orgs = db.execute(stmt).scalars().all()

    results = []
    for o in orgs:
        nb_u = db.scalar(select(func.count()).select_from(Utilisateur).where(Utilisateur.organisation_id == o.id)) or 0
        nb_d = db.scalar(select(func.count()).select_from(Dossier).where(Dossier.organisation_id == o.id)) or 0
        results.append(_org_dict(o, nb_u, nb_d))

    pages = max(1, (total + limit - 1) // limit)
    return {"organisations": results, "total": total, "page": page, "pages": pages}


@router.get("/platform/organisations/{organisation_id}")
def get_organisation_detail(organisation_id: str, db: Session = Depends(get_admin_db)):
    """Détail d'une organisation : ses utilisateurs et ses dossiers."""
    org = db.get(Organisation, organisation_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    users = db.execute(
        select(Utilisateur).where(Utilisateur.organisation_id == org.id).order_by(Utilisateur.created_at.desc())
    ).scalars().all()
    dossiers = db.execute(
        select(Dossier).where(Dossier.organisation_id == org.id).order_by(Dossier.created_at.desc())
    ).scalars().all()

    dossiers_out = []
    for d in dossiers:
        nb_alertes_ouvertes = db.scalar(
            select(func.count()).select_from(AlerteRisque)
            .where(
                AlerteRisque.dossier_id == d.id,
                AlerteRisque.statut == StatutAlerte.ouverte,
                AlerteRisque.actif.is_(True),  # cf. AlerteRisque.actif (models.py)
            )
        ) or 0
        dossiers_out.append({
            "id": str(d.id),
            "raison_sociale": d.raison_sociale,
            "secteur_activite": d.secteur_activite,
            "regime_is": d.regime_is,
            "regime_tva": d.regime_tva,
            "nb_alertes_ouvertes": nb_alertes_ouvertes,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })

    return {
        **_org_dict(org, len(users), len(dossiers)),
        "utilisateurs": [
            {
                "id": str(u.id),
                "nom_complet": u.nom_complet,
                "email": u.email,
                "role": u.role.value if hasattr(u.role, "value") else u.role,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "dossiers": dossiers_out,
    }


@router.get("/platform/users")
def list_platform_users(
    q: Optional[str] = None,
    role: Optional[str] = None,
    organisation_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_admin_db),
):
    """Liste paginée de tous les utilisateurs de la plateforme, tous cabinets/PME confondus."""
    filters = []
    if q:
        filters.append(or_(Utilisateur.nom_complet.ilike(f"%{q}%"), Utilisateur.email.ilike(f"%{q}%")))
    if role:
        filters.append(Utilisateur.role == role)
    if organisation_id:
        filters.append(Utilisateur.organisation_id == organisation_id)

    count_stmt = select(func.count()).select_from(Utilisateur)
    for f in filters:
        count_stmt = count_stmt.where(f)
    total = db.scalar(count_stmt) or 0

    stmt = (
        select(Utilisateur, Organisation.nom, Organisation.type_organisation)
        .join(Organisation, Organisation.id == Utilisateur.organisation_id)
        .order_by(Utilisateur.created_at.desc())
    )
    for f in filters:
        stmt = stmt.where(f)
    stmt = stmt.limit(limit).offset((page - 1) * limit)
    rows = db.execute(stmt).all()

    users = [
        {
            "id": str(u.id),
            "nom_complet": u.nom_complet,
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else u.role,
            "organisation_id": str(u.organisation_id),
            "organisation_nom": org_nom,
            "organisation_type": org_type.value if hasattr(org_type, "value") else org_type,
            "actif": u.actif,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u, org_nom, org_type in rows
    ]

    pages = max(1, (total + limit - 1) // limit)
    return {"users": users, "total": total, "page": page, "pages": pages}


class UserStatusRequest(BaseModel):
    actif: bool


@router.patch("/platform/users/{user_id}/status")
def set_user_status(
    user_id: str,
    req: UserStatusRequest,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_admin_db),
):
    """
    Désactivation réversible plutôt qu'une suppression (pas de FK à gérer,
    pas de perte de données). Effective au prochain login/refresh de
    l'utilisateur concerné — voir routes_auth.py, pas de vérification DB à
    chaque requête pour rester cohérent avec le design stateless de
    get_current_user.
    """
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas désactiver votre propre compte.")
    user = db.get(Utilisateur, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    user.actif = req.actif
    db.commit()
    return {"id": str(user.id), "actif": user.actif}


# Rôles qu'un admin_plateforme peut attribuer via invitation — jamais
# admin_plateforme lui-même (règle non négociable, voir
# scripts/create_platform_admin.py : ce rôle ne se crée QUE via le script
# de bootstrap, jamais via une route HTTP, publique ou non).
ROLES_INVITABLES_PLATEFORME = {RoleUtilisateur.collaborateur, RoleUtilisateur.dirigeant_pme, RoleUtilisateur.admin_cabinet}


class PlatformInvitationRequest(BaseModel):
    email: EmailStr
    role: RoleUtilisateur
    organisation_id: str


class PlatformInvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    organisation_id: str
    lien: str


@router.post("/platform/users/invite", response_model=PlatformInvitationResponse, status_code=201)
def invite_platform_user(
    req: PlatformInvitationRequest,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_admin_db),
):
    """
    Ajout d'un utilisateur par l'admin plateforme, dans N'IMPORTE QUELLE
    organisation (contrairement à POST /invitations, réservé à admin_cabinet
    et scopé à sa propre organisation). Réutilise le même modèle Invitation
    et le même flux d'acceptation (POST /invitations/accept, inchangé —
    l'acceptation ne dépend pas de qui a créé l'invitation).
    """
    if req.role not in ROLES_INVITABLES_PLATEFORME:
        raise HTTPException(status_code=400, detail="Rôle non invitable.")

    org = db.get(Organisation, uuid.UUID(req.organisation_id))
    if not org:
        raise HTTPException(status_code=404, detail="Organisation introuvable.")

    existing_user = db.execute(select(Utilisateur).where(Utilisateur.email == req.email)).scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email.")

    invitation = Invitation(
        id=uuid.uuid4(),
        organisation_id=org.id,
        email=req.email,
        role=req.role,
        dossier_id=None,
        token=secrets.token_urlsafe(32),
        statut=StatutInvitation.en_attente,
        invite_par_id=uuid.UUID(current.id),
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=INVITATION_VALIDITY_DAYS),
    )
    db.add(invitation)
    db.commit()

    return PlatformInvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role.value,
        organisation_id=str(org.id),
        lien=f"/accepter-invitation?token={invitation.token}",
    )
