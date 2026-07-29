"""
ai_auditor.py — Moteur d'audit fiscal hybride RAG + LLM pour Nisab.

ARCHITECTURE (revue après diagnostic empirique) :

  1. RETRIEVAL LARGE (rappel) : hybrid_search() combine recherche vectorielle --- Annulé 
     dense (embeddings) et recherche plein-texte PostgreSQL (mots-clés), fusionnées
     par Reciprocal Rank Fusion. On retrouve un nombre généreux de candidats
     (CANDIDATE_TOP_K) sans essayer de trancher la pertinence à ce stade.

  2. FILTRAGE DE PERTINENCE PAR LE LLM (précision) : plutôt que de fixer un seuil
     numérique sur un score de similarité, on demande explicitement au LLM d'évaluer,
     pour chaque article candidat, si ses CONDITIONS D'APPLICATION (secteur, nature
     de l'opération, seuils, qualité des parties) correspondent aux faits réels de
     la transaction. Seuls les articles jugés applicables passent à l'étape suivante.

  3. ANALYSE DE CONFORMITÉ : le LLM qualifie l'écriture (anomalie / conforme /
     contexte_insuffisant) UNIQUEMENT à partir des articles filtrés comme pertinents.
     S'il n'en reste aucun après filtrage, on économise même cet appel et on
     journalise directement "contexte_insuffisant".

POURQUOI CE CHANGEMENT D'ARCHITECTURE :
  Diagnostic empirique (voir historique du projet) : le modèle d'embedding
  (intfloat/multilingual-e5-base) produit des similarités cosinus très compressées
  sur ce corpus fiscal (souvent 0.81-0.84 pour du contenu pertinent ET non pertinent),
  un effet d'anisotropie connu sur du texte juridique au vocabulaire technique partagé.
  La recherche plein-texte seule ne comble pas totalement ce trou : le vocabulaire
  courant des écritures comptables ("frais restaurant", "fournitures de bureau") ne
  correspond pas au registre juridique formel du CGI, donc les correspondances exactes
  de mots-clés sont rares. Aucun seuil numérique unique sur ces scores ne s'est révélé
  fiable pour séparer les cas pertinents des cas non pertinents.
  Le LLM, en revanche, peut raisonner sur le contenu réel de chaque article candidat
  et sur les faits de la transaction — c'est un filtre plus coûteux (un appel
  supplémentaire) mais nettement plus robuste que n'importe quel seuil sur un score.
"""

from __future__ import annotations

import json
import os
import threading
import time
from app.llm_client import llm_call_json, GROQ_MODEL_FAST
from app.vectorstore import ArticleMatch, PgVectorStore, VectorStore

MODEL_NAME = "llama-3.3-70b-versatile"

CANDIDATE_TOP_K = 15

# Pause entre appels LLM pour respecter les quotas.
LLM_CALL_DELAY_SECONDS = 1.2

# Verrou global : empêche deux exécutions de run_ai_rag_audit de tourner en même
# temps dans ce process. Nécessaire car des appels concurrents (double clic,
# rechargement à chaud du frontend, requêtes /audit/run qui se chevauchent) ont
# été observés en pratique — ils multiplient la charge sur Groq simultanément et
# provoquent une cascade de rate limits qui fait échouer presque tous les appels,
# masquant complètement le comportement réel du filtrage de pertinence.
# Limite connue : ce verrou protège un seul process Python. S'il y a plusieurs
# workers/process (ex. plusieurs workers uvicorn), il faudrait un verrou partagé
# (ex. via la base de données ou Redis) plutôt qu'un threading.Lock en mémoire.
_audit_lock = threading.Lock()


RELEVANCE_FILTER_SYSTEM_PROMPT = """Tu es un assistant qui présélectionne des articles de loi avant une analyse fiscale approfondie.

On te fournit une écriture comptable et une liste d'articles candidats retrouvés par recherche documentaire (donc potentiellement non pertinents malgré une proximité thématique ou lexicale). Chaque article candidat est numéroté (ARTICLE 0, ARTICLE 1, ...) dans l'ordre où il t'est présenté.

Pour CHAQUE article candidat, détermine si ses CONDITIONS D'APPLICATION correspondent raisonnablement aux faits de la transaction :
- secteur d'activité concerné (ex. un régime spécifique à un secteur ne s'applique pas hors de ce secteur) ;
- nature de l'opération ou du bien/service (achat, vente, prestation, type de bien) ;
- seuils de montant éventuels ;
- qualité des parties (assujetti, résident, etc.).

Un article peut partager du vocabulaire fiscal général avec la transaction (TVA, impôt, déclaration...) SANS que ses conditions d'application précises soient réunies. Dans ce cas, marque-le comme non pertinent. Ne suppose jamais qu'une condition est réunie si rien dans l'écriture ne l'indique explicitement.

## Format de réponse OBLIGATOIRE (JSON strict, EXACTEMENT un objet par article candidat, dans le MÊME ordre que fourni)

{
  "evaluations": [
    {
      "index": 0,
      "reference": "Référence exacte de l'article telle que fournie",
      "pertinent": true,
      "justification": "Phrase courte expliquant pourquoi les conditions d'application sont, ou ne sont pas, réunies pour cette transaction précise."
    }
  ]
}

IMPORTANT : le champ "index" doit correspondre exactement au numéro ARTICLE indiqué dans le bloc candidat (0 pour le premier article, 1 pour le second, etc.). Ne saute aucun article et n'en ajoute aucun.
"""

AUDIT_SYSTEM_PROMPT = """Tu es Nisab, un auditeur fiscal expert au Maroc.

Tu analyses une écriture comptable d'une entreprise marocaine en la confrontant aux articles de loi du Code Général des Impôts (CGI) et du Bulletin Officiel fournis en contexte. Ces articles ont déjà été présélectionnés comme pertinents pour cette transaction — mais reste rigoureux : si en les lisant attentivement tu identifies qu'ils ne permettent finalement pas de conclure, dis-le plutôt que d'inventer un rattachement.

Tu dois évaluer si l'écriture présente un risque fiscal (non-conformité, charge non déductible, TVA non déductible, absence de pièce/ICE, dépassement de plafond, régime d'auto-liquidation, etc.).

## Format de réponse OBLIGATOIRE (JSON strict)

Retourne UNIQUEMENT un objet JSON valide avec la structure suivante :

{
  "status": "anomalie" | "conforme" | "contexte_insuffisant",
  "severity": "rouge" | "orange" | "vert",
  "reference_cgi": "Nom et numéro de l'article exact (ex: Article 193 du CGI)",
  "title": "Titre très court du problème fiscal (ex: Paiement en espèces > 5 000 DH)",
  "description": "Explication claire de l'incohérence comptable par rapport au texte de loi, incluant pourquoi les conditions d'application de l'article sont réunies dans cette écriture précise.",
  "amount_risk": 1500.0,
  "recommendation": "Action concrète pour régulariser la situation auprès de la DGI."
}

Si l'écriture est parfaitement conforme au regard du contexte fourni :
{
  "status": "conforme",
  "severity": "vert",
  "reference_cgi": "CGI 2026",
  "title": "Conforme",
  "description": "L'opération respecte la réglementation fiscale au regard des textes disponibles.",
  "amount_risk": 0.0,
  "recommendation": "Aucune action requise."
}

Si, malgré la présélection, le contexte ne permet toujours pas de conclure avec certitude :
{
  "status": "contexte_insuffisant",
  "severity": "vert",
  "reference_cgi": "Aucun article suffisamment concluant",
  "title": "Analyse non concluante",
  "description": "Explique précisément ce qui manque pour conclure.",
  "amount_risk": 0.0,
  "recommendation": "Vérification manuelle recommandée par un expert-comptable."
}

Règles strictes :
- Base ton analyse UNIQUEMENT sur le contexte juridique fourni ; ne complète jamais avec une connaissance générale non citée.
- N'affirme jamais qu'un régime particulier (ex. auto-liquidation) s'applique sans que la nature de l'opération (secteur, type de bien) l'indique explicitement dans l'écriture.
- Calcule ou estime l'exposition financière en DH (amount_risk) uniquement pour le statut "anomalie".
- Sois rigoureux, concis et opérationnel.
"""


def _build_transaction_summary(move: dict, lines: list[dict], partner: dict | None) -> str:
    """Construit un résumé textuel clair d'une transaction Odoo pour la recherche RAG et le LLM."""
    name = move.get("name", "Inconnu")
    date_str = move.get("date", "Date inconnue")
    amount = move.get("amount_total", 0.0)
    journal = move.get("journal_id", [0, "General"])[1] if isinstance(move.get("journal_id"), list) else "General"

    partner_name = partner.get("name", "Inconnu") if partner else "Aucun"
    partner_ice = partner.get("vat") if partner else None

    move_id = move.get("id")
    line_details = []
    for l in lines:
        lm = l.get("move_id")
        if isinstance(lm, list) and lm[0] == move_id:
            account_name = l.get("account_id", [0, "Compte"])[1] if isinstance(l.get("account_id"), list) else ""
            line_name = l.get("name") or ""
            debit = l.get("debit", 0.0)
            credit = l.get("credit", 0.0)
            pmode = l.get("payment_mode") or ""
            line_details.append(f"- Ligne: {account_name} ({line_name}) | Débit: {debit} DH | Crédit: {credit} DH | Mode: {pmode}")

    lines_str = "\n".join(line_details) if line_details else "Aucune ligne détaillée"

    summary = f"""ÉCRITURE COMPTABLE A ANALYSER :
N° Pièce / Facture : {name}
Date : {date_str}
Journal comptable : {journal}
Fournisseur / Tiers : {partner_name} (ICE / N° TVA : {partner_ice or 'NON RENSEIGNÉ / MANQUANT'})
Montant Total TTC : {amount:,.2f} DH

Détail des écritures comptables :
{lines_str}
"""
    return summary


def _build_search_query(move: dict, txn_summary: str, partner: dict | None) -> str:
    """
    Construit la requête de recherche à partir du contenu réel de la transaction
    (pièce, journal, tiers, libellés de ligne), plutôt que d'un ensemble de
    catégories fiscales devinées à l'avance.
    """
    parts = [move.get("name", "")]

    journal = move.get("journal_id")
    if isinstance(journal, list) and len(journal) > 1:
        parts.append(str(journal[1]))

    if partner and partner.get("name"):
        parts.append(str(partner["name"]))

    for line in txn_summary.splitlines():
        if line.strip().startswith("- Ligne:"):
            parts.append(line.strip())

    query = " ".join(p for p in parts if p).strip()
    if not query:
        query = txn_summary[:300]

    return query




def _filter_relevant_articles(
    txn_summary: str, candidates: list[ArticleMatch], label: str
) -> tuple[list[ArticleMatch], dict[str, str], bool]:
    if not candidates:
        return [], {}, True

    candidates_block = "\n\n".join(
        f"=== ARTICLE {i} : {m.reference} ({m.source_label}) ===\n{m.texte[:500]}"
        for i, m in enumerate(candidates)
    )

    prompt = f"""{txn_summary}

ARTICLES CANDIDATS À ÉVALUER :
{candidates_block}

Évalue la pertinence de chaque article candidat pour cette transaction précise. Utilise le numéro ARTICLE indiqué comme valeur du champ "index".
"""

    result = llm_call_json(
        RELEVANCE_FILTER_SYSTEM_PROMPT, prompt,
        label=f"filtrage_{label}", model=GROQ_MODEL_FAST,
    )
    if result is None:
        return [], {}, False

    evaluations = result.get("evaluations", [])
    print(f"[RAG-DEBUG] {label} — brut du LLM : {json.dumps(evaluations, ensure_ascii=False)}")

    # Matching par index déclaré par le LLM, avec repli sur la position
    # brute si l'index est absent ou invalide (robustesse supplémentaire).
    relevant_articles = []
    relevant_refs = {}
    for pos, e in enumerate(evaluations):
        idx = e.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
            print(f"[RAG-DEBUG] {label} — index absent/invalide ({idx!r}) pour l'évaluation en position {pos}, "
                  f"repli sur la position brute.")
            idx = pos
            if idx >= len(candidates):
                continue

        if e.get("pertinent") is True:
            m = candidates[idx]
            relevant_articles.append(m)
            relevant_refs[m.reference] = e.get("justification", "")

    return relevant_articles, relevant_refs, True


def run_ai_rag_audit(odoo_data: dict, top_k_legal: int = CANDIDATE_TOP_K) -> list[dict]:
    """
    Exécute l'audit RAG IA en deux étapes par écriture. Protégé par un verrou
    global (_audit_lock) : si cette fonction est appelée alors qu'une exécution
    est déjà en cours, l'appel attend son tour.
    """
    with _audit_lock:
        return _run_ai_rag_audit_locked(odoo_data, top_k_legal)


def _run_ai_rag_audit_locked(odoo_data: dict, top_k_legal: int) -> list[dict]:
    moves: list[dict] = odoo_data.get("moves", [])
    lines: list[dict] = odoo_data.get("lines", [])
    partners: list[dict] = odoo_data.get("partners", [])

    partner_map = {p["id"]: p for p in partners if "id" in p}

    try:
        store = PgVectorStore()
    except Exception as exc:
        print(f"VectorStore non disponible pour l'audit RAG : {exc}")
        store = None

    groq_key = os.environ.get("GROQ_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_KEY")
    has_llm = bool(groq_key or openrouter_key)

    findings = []
    technical_failures = []  # traçabilité séparée : écritures non concluantes à cause d'un échec technique
    auditable_moves = [m for m in moves if m.get("move_type") in ("in_invoice", "entry")]

    for idx, move in enumerate(auditable_moves):
        if idx > 0:
            time.sleep(LLM_CALL_DELAY_SECONDS)

        pid = move.get("partner_id", [None])[0] if isinstance(move.get("partner_id"), list) else None
        partner = partner_map.get(pid) if pid else None
        txn_summary = _build_transaction_summary(move, lines, partner)
        move_label = move.get("name", f"move_{move.get('id')}")

        # 1. Retrieval large (rappel)
        candidates: list[ArticleMatch] = []
        if store:
            search_query = _build_search_query(move, txn_summary, partner)
            candidates = store.search(search_query, top_k=top_k_legal)

        if not candidates:
            print(f"[RAG] {move_label} — aucun candidat retrouvé, contexte insuffisant (résultat réel, pas un échec).")
            continue

        if not has_llm:
            print(f"[RAG] {move_label} — aucun LLM disponible (GROQ_API_KEY et OPENROUTER_KEY absents), audit ignoré.")
            technical_failures.append(move_label)
            continue

        relevant_articles, justifications, filter_ok = _filter_relevant_articles(txn_summary, candidates, move_label)

        if not filter_ok:
            print(f"[RAG] {move_label} — ÉCHEC TECHNIQUE du filtrage (pas un vrai résultat), écriture non auditée cette fois-ci.")
            technical_failures.append(move_label)
            continue

        print(f"[RAG] {move_label} — {len(candidates)} candidat(s) -> {len(relevant_articles)} jugé(s) pertinent(s) "
              f"({', '.join(m.reference for m in candidates)})")

        if not relevant_articles:
            print(f"[RAG] {move_label} — aucun candidat jugé applicable après filtrage, contexte insuffisant (résultat réel).")
            continue

        time.sleep(LLM_CALL_DELAY_SECONDS)

        # 3. Analyse de conformité, uniquement sur les articles filtrés
        legal_context = "\n\n".join(
            f"=== ARTICLE {m.reference} ({m.source_label}) ===\n{m.texte[:500]}\n"
            f"[Pertinence retenue : {justifications.get(m.reference, '')}]"
            for m in relevant_articles
        )

        audit_prompt = f"""CONTEXTE JURIDIQUE (articles présélectionnés comme pertinents pour cette transaction) :
{legal_context}

--------------------------------------------------
{txn_summary}

Analyse cette écriture comptable au regard du contexte juridique fourni et génère ton rapport d'audit au format JSON.
"""

        audit_result = llm_call_json(AUDIT_SYSTEM_PROMPT, audit_prompt, label=f"audit_{move_label}")
        if audit_result is None:
            print(f"[RAG] {move_label} — ÉCHEC TECHNIQUE de l'audit final (pas un vrai résultat), écriture non auditée cette fois-ci.")
            technical_failures.append(move_label)
            continue

        status = audit_result.get("status", "contexte_insuffisant")

        if status == "anomalie":
            move_type = move.get("move_type", "entry")
            if move_type == "in_invoice":
                odoo_section = "Comptabilité > Fournisseurs > Factures"
            elif move_type == "out_invoice":
                odoo_section = "Comptabilité > Clients > Factures"
            elif move_type == "in_refund":
                odoo_section = "Comptabilité > Fournisseurs > Avoirs"
            elif move_type == "out_refund":
                odoo_section = "Comptabilité > Clients > Avoirs"
            else:
                odoo_section = "Comptabilité > Écritures Comptables > Pièces"

            findings.append({
                "rule": f"ai_rag_{move.get('id')}",
                "status": status,
                "severity": audit_result.get("severity", "orange"),
                "reference_cgi": audit_result.get("reference_cgi", "CGI 2026"),
                "title": audit_result.get("title", "Anomalie détectée par l'IA"),
                "description": audit_result.get("description", ""),
                "amount_risk": float(audit_result.get("amount_risk", 0.0)),
                "invoice": move.get("name"),
                "partner": partner.get("name") if partner else "Inconnu",
                "date": move.get("date"),
                "recommendation": audit_result.get("recommendation", ""),
                "rag_sources": [m.reference for m in relevant_articles],
                "odoo_path": {
                    "section": odoo_section,
                    "record_name": move.get("name"),
                    "move_id": move.get("id"),
                    "move_type": move_type,
                },
            })
        elif status == "contexte_insuffisant":
            print(f"[RAG] {move_label} — contexte jugé insuffisant même après filtrage (résultat réel) : "
                  f"{audit_result.get('description', '')}")
        # status == "conforme" -> rien à ajouter

    if technical_failures:
        print(f"\n[RAG] ATTENTION : {len(technical_failures)} écriture(s) non auditée(s) à cause d'un échec technique "
              f"(rate limit persistant), PAS parce qu'elles sont conformes ou sans risque : {technical_failures}")
        print("[RAG] Recommandation : relancer l'audit séparément sur ces écritures une fois la charge Groq redescendue.")

    severity_order = {"rouge": 0, "orange": 1, "vert": 2}
    findings.sort(key=lambda f: severity_order.get(f.get("severity", "vert"), 99))
    return findings


def debug_retrieval(store: PgVectorStore, query: str, top_k: int = CANDIDATE_TOP_K) -> None:
    """
    Utilitaire de diagnostic (exécution manuelle) : affiche les candidats bruts
    remontés par hybrid_search pour une requête donnée, sans passer par le LLM.
    Utile pour vérifier rapidement que le retrieval ramène des candidats plausibles
    avant de déboguer le filtrage LLM séparément.
    """
    matches = store.search(query, top_k=top_k)
    print(f"Requête : {query}")
    for m in matches:
        apercu = m.texte[:120].replace("\n", " ")
        print(f"  {m.reference:30s} | score={m.score:.4f} | {apercu}...")


if __name__ == "__main__":
    # Exécution manuelle de diagnostic : python -m app.ai_auditor
    _store = PgVectorStore()
    for _label, _query in {
        "auto-liquidation déchets": "Achat déchets métalliques et de récupération industrielle",
        "ICE manquant": "Facture fournisseur sans ICE ni numéro de TVA renseigné",
        "frais restaurant": "Note de frais restaurant équipe commerciale",
        "fournitures bureau": "Achat de fournitures de bureau papeterie",
    }.items():
        print(f"\n--- {_label} ---")
        debug_retrieval(_store, _query)