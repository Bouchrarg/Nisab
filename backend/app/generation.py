"""
generation.py - Génération de réponse à partir des articles récupérés.
"""

from __future__ import annotations

from app.llm_client import llm_call

SYSTEM_PROMPT = """Tu es Nisab, un copilote fiscal expert pour les cabinets comptables et PME au Maroc.

Tu analyses les questions fiscales UNIQUEMENT à partir des articles du Code Général des Impôts (CGI) et du Bulletin Officiel fournis ci-dessous.

## Structure obligatoire de ta réponse

1. **Base légale** : Cite l'article exact (ex: *Article 10-I-A du CGI*) applicable à la question.
2. **Analyse fiscale** : Explique clairement la règle applicable, ses conditions et ses exceptions.
3. **Recommandation** : Fournis une recommandation concrète et opérationnelle pour le cabinet ou la PME.
4. **Niveau de risque** : Indique le niveau de risque en cas de non-conformité (🔴 Élevé / 🟠 Moyen / 🟢 Faible).

## Règles strictes

- Tu réponds **uniquement** à partir du contexte fourni. Si le contexte est insuffisant, dis-le clairement en indiquant les sources manquantes.
- **Ne jamais inventer** une règle fiscale, un taux, ou une date qui ne figurent pas dans les articles fournis.
- Cite systématiquement la **référence complète** de chaque article utilisé.
- Si la question est en **darija ou en arabe**, réponds dans la même langue, en conservant les références d'articles en français.
- Reste concis, professionnel et opérationnel.
- Si plusieurs articles sont pertinents, hiérarchise-les par importance.
"""


def generate_answer(
    query: str,
    sources: list[dict],
    context_data: dict | None = None,
    active_view: str | None = None,
) -> str:
    """Génère une réponse RAG avec injection optionnelle du contexte de la vue active."""

    # Build view context block if provided
    view_context_block = ""
    if context_data or active_view:
        view_name_map = {
            "dashboard": "Tableau de bord",
            "audit": "Audit fiscal",
            "calendar": "Calendrier fiscal",
            "odoo": "Synchronisation ERP",
            "admin": "Administration",
        }
        view_label = view_name_map.get(active_view or "", active_view or "Inconnue")
        view_context_block = f"\n\n## CONTEXTE DE LA VUE ACTIVE ({view_label})\n"
        if context_data:
            import json as _json
            # Limit context data to avoid token explosion
            ctx_str = _json.dumps(context_data, ensure_ascii=False, default=str)[:2000]
            view_context_block += f"Données affichées à l'écran :\n{ctx_str}\n"
            view_context_block += "\nUtilise ces données pour répondre de façon contextuelle si la question y fait référence.\n"

    system_with_context = SYSTEM_PROMPT + view_context_block

    context = "\n\n---\n\n".join(
        f"[{s['reference']} — {s['source_label']}]\n{s['texte_complet']}"
        for s in sources
    )

    prompt = f"""Contexte juridique :

{context}

Question :
{query}
"""

    result = llm_call(system_with_context, prompt, label="chat_generation")
    if result is None:
        raise RuntimeError("Aucun provider LLM disponible (Groq + OpenRouter en échec)")
    return result