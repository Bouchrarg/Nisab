from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai_auditor import run_ai_rag_audit
from app.compliance_checker import run_audit
from app.generation import generate_answer
from app.odoo_connector import OdooConnector, get_demo_data
from app.tax_calendar import get_calendar_events
from app.vectorstore import PgVectorStore, VectorStore

router = APIRouter()

# Active Odoo connection (in-memory session + cache file)
_odoo_session: Optional[OdooConnector] = None
_odoo_data: Optional[dict] = None
CACHE_FILE = os.path.join(tempfile.gettempdir(), "nisab_odoo_cache.json")

_audit_cache: Optional[list[dict]] = None
_audit_cache_lock = threading.Lock()


def _hash_data(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _save_cache(data: dict):
    global _odoo_data, _audit_cache
    new_hash = _hash_data(data)
    old_hash = _hash_data(_odoo_data) if _odoo_data is not None else None

    _odoo_data = data
    if new_hash != old_hash:
        _audit_cache = None
        print("[CACHE] Données comptables changées, cache d'audit invalidé.")
    else:
        print("[CACHE] Données identiques, cache d'audit conservé.")

    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"Erreur de sauvegarde du cache Odoo : {e}")


def _get_active_odoo_data() -> dict | None:
    global _odoo_data
    if _odoo_data is not None:
        return _odoo_data
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _odoo_data = json.load(f)
                return _odoo_data
        except Exception as e:
            print(f"Erreur de chargement du cache Odoo : {e}")
    return None


@lru_cache(maxsize=1)
def get_vectorstore() -> VectorStore:
    return PgVectorStore()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = Field(5, ge=1, le=15)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    top_k: int = Field(5, ge=1, le=15)
    context_data: Optional[dict] = None
    active_view: Optional[str] = None


class OdooConnectRequest(BaseModel):
    url: str
    db: str
    username: str
    password: str


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
                "extrait": m.texte.strip()[:280],
                "texte_complet": m.texte.strip(),
            }
            for m in matches
        ],
    }


@router.post("/chat")
def chat(req: ChatRequest):
    store = get_vectorstore()
    matches = store.search(req.query, top_k=req.top_k)

    sources = [
        {
            "id": m.id,
            "reference": m.reference,
            "source_label": m.source_label,
            "score": round(m.score, 4),
            "extrait": m.texte.strip()[:280],
            "texte_complet": m.texte.strip(),
        }
        for m in matches
    ]

    if not sources:
        return {"query": req.query, "answer": "Aucun article pertinent trouvé.", "sources": []}

    try:
        answer = generate_answer(req.query, sources, context_data=req.context_data, active_view=req.active_view)
    except Exception as exc:
        answer = f"Erreur lors de la génération (articles trouvés ci-dessous quand même). Détail : {exc}"

    return {"query": req.query, "answer": answer, "sources": sources}


@router.post("/odoo/connect")
def odoo_connect(req: OdooConnectRequest):
    global _odoo_session
    try:
        connector = OdooConnector(req.url, req.db, req.username, req.password)
        connector.authenticate()
        _odoo_session = connector
        data = connector.fetch_accounting_data()
        _save_cache(data)
        global _audit_cache
        _audit_cache = None
        return {
            "status": "connected",
            "company": data.get("company", {}).get("name", "Inconnu"),
            "nb_moves": len(data.get("moves", [])),
            "nb_partners": len(data.get("partners", [])),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Connexion Odoo échouée : {exc}")


@router.get("/odoo/status")
def odoo_status():
    global _odoo_session
    data = _get_active_odoo_data()
    if _odoo_session or data:
        company_name = data.get("company", {}).get("name") if data else "Odoo"
        return {"connected": True, "company": company_name}
    return {"connected": False}


@router.get("/odoo/demo")
def odoo_demo():
    """Charge les données de démonstration simulées (sans instance Odoo réelle)."""
    data = get_demo_data()
    _save_cache(data)
    global _audit_cache
    _audit_cache = None
    return {
        "status": "demo_loaded",
        "company": data["company"]["name"],
        "nb_moves": len(data["moves"]),
        "nb_partners": len(data["partners"]),
    }


def execute_audit(data: dict) -> list[dict]:
    """Exécute l'audit RAG IA (avec fallback), mis en cache pour éviter de relancer tous les appels LLM."""
    global _audit_cache

    if _audit_cache is not None:
        return _audit_cache

    with _audit_cache_lock:
        if _audit_cache is not None:
            return _audit_cache

        try:
            if os.environ.get("GROQ_API_KEY"):
                ai_findings = run_ai_rag_audit(data)
                if ai_findings:
                    _audit_cache = ai_findings
                    return ai_findings
        except Exception as exc:
            print(f"Audit RAG IA non disponible ({exc}), fallback sur les règles statiques.")

        _audit_cache = run_audit(data)
        return _audit_cache


@router.post("/audit/run")
def audit_run(force: bool = False):
    data = _get_active_odoo_data()
    if data is None:
        raise HTTPException(status_code=400, detail="Aucune donnée comptable chargée. Appelez /odoo/connect ou /odoo/demo d'abord.")
    global _audit_cache
    if force:
        _audit_cache = None
    try:
        findings = execute_audit(data)
        return {"nb_anomalies": len(findings), "findings": findings}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/dashboard/summary")
def dashboard_summary():
    data = _get_active_odoo_data()
    if data is None:
        return {"status": "no_data", "message": "Aucune donnée chargée"}
    try:
        findings = execute_audit(data)
        risks = {"rouge": 0, "orange": 0, "vert": 0}
        for f in findings:
            risks[f.get("severity", "orange")] += 1
        total_exposure = sum(f.get("amount_risk", 0) for f in findings)
        compliance_score = max(0, 100 - len(findings) * 8)

        if len(findings) == 0:
            exec_summary = "✅ Aucune anomalie détectée. Le dossier fiscal est en bonne conformité au regard des règles du CGI 2026 analysées."
        else:
            critical_count = risks["rouge"]
            orange_count = risks["orange"]
            parts = []
            if critical_count > 0:
                parts.append(f"{critical_count} anomalie(s) critique(s) nécessitant une action immédiate")
            if orange_count > 0:
                parts.append(f"{orange_count} alerte(s) modérée(s) à régulariser")
            exposure_str = f"{total_exposure:,.0f} DH".replace(",", " ")
            summary_body = ", ".join(parts)
            exec_summary = f"⚠️ {len(findings)} anomalie(s) détectée(s) : {summary_body}. Exposition fiscale estimée : {exposure_str}."

        top_urgency = None
        if findings:
            rouge_findings = [f for f in findings if f.get("severity") == "rouge"]
            top_f = rouge_findings[0] if rouge_findings else findings[0]
            top_urgency = {
                "title": top_f.get("title", ""),
                "invoice": top_f.get("invoice", ""),
                "amount_risk": top_f.get("amount_risk", 0),
                "severity": top_f.get("severity", "orange"),
            }

        return {
            "company": data.get("company", {}).get("name", "Inconnu"),
            "nb_anomalies": len(findings),
            "risks": risks,
            "total_exposure_dh": round(total_exposure, 2),
            "compliance_score": compliance_score,
            "executive_summary": exec_summary,
            "top_urgency": top_urgency,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/law/feed")
def law_feed(mode: str = "latest", limit: int = 5):
    """Retourne les documents légaux ingérés."""
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
            apercu = (row[3] or "").strip().replace("\n", " ")
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


@router.get("/calendar/events")
def calendar_events(regime: str = "normal", tva_regime: str = "mensuel"):
    """Retourne les prochaines échéances fiscales selon le régime et croise les écritures Odoo."""
    data = _get_active_odoo_data()
    try:
        events = get_calendar_events(regime=regime, tva_regime=tva_regime, odoo_data=data)
        return {"events": events}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
