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

# Variante appliquée quand format_reponse="bref" (generate_answer). La
# structure à 4 sections a un coût réel : sur une question fermée qui n'a
# qu'un seul article pertinent retenu par le filtre RAG (ex. "le taux normal
# de TVA c'est bien 20% ?"), elle force une génération à 4 paragraphes pour
# une réponse qui tient en une phrase. Le contenu vérifié (citation exacte,
# refus d'inventer, langue de réponse) reste identique — seule la mise en
# forme change, pour ne pas payer en tokens ce que la question ne demandait
# pas.
_SYSTEM_PROMPT_BREF = """Tu es Nisab, un copilote fiscal expert pour les cabinets comptables et PME au Maroc.

Tu réponds UNIQUEMENT à partir des articles du Code Général des Impôts (CGI) et du Bulletin Officiel fournis ci-dessous.

## Format de réponse

Réponds en 2 à 3 phrases maximum, sans les 4 sections habituelles (pas de titres, pas de liste) : va directement à la règle applicable, en citant l'article exact entre parenthèses (ex : "... (Article 10-I-A du CGI)."). N'ajoute une mise en garde sur le niveau de risque que si l'enjeu est réellement significatif — pas systématiquement.

## Règles strictes

- Tu réponds **uniquement** à partir du contexte fourni. Si le contexte est insuffisant, dis-le en une phrase plutôt que d'improviser.
- **Ne jamais inventer** une règle fiscale, un taux, ou une date qui ne figurent pas dans les articles fournis.
- Cite systématiquement la **référence complète** de l'article utilisé.
- Si la question est en **darija ou en arabe**, réponds dans la même langue, en conservant les références d'articles en français.
"""

#: Longueur maximale d'un article dans le PROMPT de génération (pas dans ce
#: qui est persisté/affiché : CitationPills et Citation.reponse lisent le
#: texte complet stocké en base, jamais cette version tronquée). 5 articles
#: non tronqués pouvaient dépasser 10 000 caractères de contexte pour une
#: question qui n'en utilise souvent qu'un seul dans sa réponse — la
#: troncature vise l'usage réel, pas la lisibilité (déjà garantie côté
#: affichage par CitationPills).
_MAX_CHARS_PAR_ARTICLE_PROMPT = 1500


# Bloc ajouté quand la question est en arabe ou en darija.
#
# ## Pourquoi les citations restent en français, sans exception
#
# Le corpus est français. Traduire une citation légale produirait une
# PARAPHRASE présentée comme du texte de loi : l'utilisateur ne pourrait plus
# vérifier la réponse contre la source, et c'est précisément la garantie que
# vend le produit. Une paraphrase arabe de l'article 106 n'est pas l'article
# 106 — devant un contrôle, elle ne vaut rien.
#
# C'est aussi ce qui rend cohérente la décision de ne pas traduire les 401
# articles du corpus : ce n'est pas une économie, c'est le refus d'introduire
# une couche non vérifiable entre le texte légal et l'utilisateur.
_CONSIGNE_ARABE = """

## LANGUE DE LA RÉPONSE

La question est posée en {langue_lisible}. Réponds dans cette langue.

- Traduis les titres de sections : الأساس القانوني (Base légale), التحليل الضريبي (Analyse fiscale), التوصية (Recommandation), مستوى المخاطر (Niveau de risque).
- **Garde EN FRANÇAIS, mot pour mot** : les références d'articles (« Article 106 du CGI »), les intitulés officiels d'articles, et toute citation littérale du texte de loi. Ne les traduis jamais, même partiellement.
- Tu peux expliquer en arabe ce que dit un article, mais la citation elle-même reste en français, entre guillemets.
- Les montants restent en chiffres occidentaux suivis de « DH » (ex. 5 000 DH), conformément à l'usage comptable marocain.
"""

_LANGUES_LISIBLES = {
    "ar": "arabe standard",
    "ar_latin": "darija marocaine écrite en caractères latins (arabizi) — réponds en darija, transcrite en caractères arabes",
}


def generate_answer(
    query: str,
    sources: list[dict],
    context_data: dict | None = None,
    active_view: str | None = None,
    langue: str | None = None,
    format_reponse: str = "complet",
) -> str:
    """
    Génère une réponse RAG avec injection optionnelle du contexte de la vue active.

    `langue` ('ar', 'ar_latin' ou 'fr') vient de langue.detecter_langue().
    La SYSTEM_PROMPT demandait déjà de « répondre dans la même langue », mais
    rien ne le vérifiait ni ne précisait quoi faire des citations : en pratique
    le modèle traduisait tout, références comprises, ce qui rend la réponse
    invérifiable. Le bloc explicite lève l'ambiguïté.

    `format_reponse` ('complet' par défaut, ou 'bref') : bascule le prompt
    système sur `_SYSTEM_PROMPT_BREF`, qui abandonne les 4 sections
    obligatoires pour une question qui n'en a pas besoin. Ne change ni le
    contenu vérifié (citations, refus d'inventer) ni la langue — uniquement
    la forme. La consigne de langue arabe reste compatible avec les deux :
    ses instructions de traduction des TITRES DE SECTIONS ne s'appliquent
    simplement pas quand le format bref n'en produit aucun.
    """

    # Build view context block if provided
    view_context_block = ""
    if context_data or active_view:
        view_name_map = {
            "dashboard": "Tableau de bord",
            "audit": "Audit fiscal",
            "simulation": "Simulation de contrôle",
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

    consigne_langue = ""
    if langue in _LANGUES_LISIBLES:
        consigne_langue = _CONSIGNE_ARABE.format(langue_lisible=_LANGUES_LISIBLES[langue])

    # Bloc ajouté SEULEMENT quand une note circulaire DGI figure parmi les
    # sources (jamais pour le CGI/BO seuls) : la circulaire n'est jamais
    # présente sans un article CGI compagnon dans le même lot (garanti par
    # rag_retrieval._filtrer_circulaires_isolees), mais rien n'empêchait
    # encore le modèle de présenter les deux au même niveau d'autorité — une
    # interprétation administrative rendue comme si elle était la loi.
    consigne_circulaire = ""
    if any(s.get("type") == "NOTE_CIRCULAIRE" for s in sources):
        consigne_circulaire = (
            "\n\n## SOURCES DE NATURE DIFFÉRENTE\n\n"
            "Le contexte ci-dessous mélange des articles du CGI (la LOI) et une ou plusieurs notes "
            "circulaires DGI (l'INTERPRÉTATION de l'administration). Distingue toujours explicitement "
            "les deux : dis \"le CGI dispose que...\" pour un article de loi, et \"la DGI précise/tolère "
            "que...\" pour une circulaire — jamais la même formulation pour les deux. Une circulaire "
            "n'engage que l'administration et ne peut jamais contredire le CGI qu'elle commente."
        )

    base_prompt = _SYSTEM_PROMPT_BREF if format_reponse == "bref" else SYSTEM_PROMPT
    system_with_context = base_prompt + view_context_block + consigne_langue + consigne_circulaire

    # Troncature du PROMPT uniquement — ce qui est persisté (Citation.reponse)
    # et affiché (CitationPills, via la route qui construit `sources`) reste le
    # texte complet ; seul ce qu'on envoie au modèle est raccourci. 5 articles
    # non tronqués pouvaient dépasser 10 000 caractères de contexte pour une
    # question qui n'en exploite souvent qu'un seul dans sa réponse.
    context = "\n\n---\n\n".join(
        f"[{s['reference']} — {s['source_label']}]\n{s['texte_complet'][:_MAX_CHARS_PAR_ARTICLE_PROMPT]}"
        for s in sources
    )

    prompt = f"""Contexte juridique :

{context}

Question :
{query}
"""

    # max_tokens n'est posé qu'en mode "bref" : une réponse "complet" a besoin
    # des 4 sections en entier, la plafonner risquerait de la couper au milieu
    # d'une citation légale — pire qu'une réponse simplement plus longue.
    max_tokens = 220 if format_reponse == "bref" else None
    result = llm_call(system_with_context, prompt, label="chat_generation", max_tokens=max_tokens)
    if result is None:
        raise RuntimeError("Aucun provider LLM disponible (Groq + OpenRouter en échec)")
    return result