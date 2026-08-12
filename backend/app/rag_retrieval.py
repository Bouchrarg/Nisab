"""
rag_retrieval.py — Filtrage de pertinence par LLM pour l'assistant fiscal
sourcé (Module 2), sur le même principe que ai_auditor.py (Module 3) :
retrieval large (rappel) via recherche dense, puis un LLM juge CHAQUE
candidat sur ses conditions d'application réelles avant de servir de base
à la génération de réponse.

Pourquoi ce fichier existe séparément d'ai_auditor.py plutôt que de
réutiliser _filter_relevant_articles directement : le prompt d'ai_auditor
est calibré sur une ÉCRITURE COMPTABLE (montants, tiers, ICE...), alors
qu'ici le contexte est une QUESTION EN LANGAGE NATUREL d'un collaborateur.
Le format de sortie (JSON indexé) et la mécanique (candidats numérotés,
matching par index avec repli sur position) sont identiques par design —
c'est le même principe éprouvé, appliqué à un contexte différent — mais on
évite de forcer un seul prompt à couvrir deux registres de langage très
différents.

Avant cette correction, le chat (routes_dossiers.py::chat et
api.py::chat_general) envoyait directement les résultats bruts de
store.search() (dense pur, scores compressés 0.81-0.84 sur ce corpus,
cf. ai_auditor.py) au LLM de génération, sans étape de filtrage — seul
module RAG de la plateforme sans ce garde-fou, alors que
"citation systématique... anti-hallucination" est décrit comme le cœur
produit dans le cahier des charges.
"""

from __future__ import annotations

import json
import time

from app.langue import est_arabe
from app.llm_client import llm_call, llm_call_json, GROQ_MODEL_FAST
from app.vectorstore import ArticleMatch, VectorStore

CANDIDATE_TOP_K = 15

# Pause avant l'appel de filtrage qui suit (respect des quotas Groq) —
# alignée sur ai_auditor.LLM_CALL_DELAY_SECONDS.
LLM_CALL_DELAY_SECONDS = 1.2

QUERY_REFORMULATION_SYSTEM_PROMPT = """Tu aides à préparer une recherche documentaire dans le Code Général des Impôts marocain (CGI) et le Bulletin Officiel.

On te donne une question posée par un collaborateur de cabinet comptable. Reformule-la en une COURTE requête de recherche (une phrase, 10-20 mots maximum), dans le vocabulaire fiscal/juridique utilisé par les textes de loi, pour maximiser les chances de retrouver l'article pertinent par recherche sémantique.

Règles :
- Garde le sens exact de la question, ne réponds pas à la question elle-même.
- La requête doit TOUJOURS être en FRANÇAIS, même si la question est posée en arabe, en darija ou dans une autre langue. Le corpus interrogé est exclusivement en français.
- Réponds UNIQUEMENT avec la requête reformulée, sans préambule ni guillemets.
"""


def _reformulate_question(query: str, label: str) -> str | None:
    """
    Reformule une question en langage naturel en requête de recherche dans le
    vocabulaire fiscal du corpus. Impact généralement plus faible que pour
    l'audit (ai_auditor.py) car les questions du chat sont déjà en langage
    naturel plutôt qu'un résumé comptable brut, mais garde les deux pipelines
    de retrieval cohérents. Retourne None si l'appel échoue techniquement —
    l'appelant retombe alors sur la requête brute de l'utilisateur.

    ## Cette étape porte aussi la traduction, et ce n'est pas un détail

    Le modèle d'embedding (multilingual-e5-base) est annoncé cross-lingue, ce
    qui laissait espérer qu'une question arabe retrouve directement les
    articles français. **Mesuré sur ce corpus : 13 % de recouvrement** entre
    les résultats d'une même question posée en français et en arabe (protocole
    et chiffres dans test_langue.py). Autrement dit, une question en arabe
    tombait sur d'autres articles — pas moins bons en apparence, mais pas les
    bons, ce qui est pire : la réponse serait sourcée et fausse.

    Plutôt que d'ajouter un appel de traduction, on charge la reformulation —
    qui tourne de toute façon à chaque question — de produire du français.
    Coût marginal nul, un seul endroit à comprendre.
    """
    result = llm_call(
        QUERY_REFORMULATION_SYSTEM_PROMPT, query,
        label=f"reformulation_chat_{label}", model=GROQ_MODEL_FAST,
    )
    if not result:
        return None
    return result.strip().strip('"').strip()

CHAT_RELEVANCE_FILTER_SYSTEM_PROMPT = """Tu es un assistant qui présélectionne des articles de loi avant de répondre à une question fiscale posée par un collaborateur de cabinet comptable marocain.

On te fournit une QUESTION et une liste d'articles candidats retrouvés par recherche documentaire (donc potentiellement non pertinents malgré une proximité thématique ou lexicale). Chaque article candidat est numéroté (ARTICLE 0, ARTICLE 1, ...) dans l'ordre où il t'est présenté.

Pour CHAQUE article candidat, détermine s'il répond raisonnablement à ce qui est demandé dans la question :
- il couvre le bon impôt/la bonne taxe (TVA, IS, IR, CNSS...) ou la bonne procédure ;
- il couvre le bon régime ou la bonne situation évoquée dans la question (pas seulement un mot-clé fiscal en commun) ;
- s'il pose une condition, un seuil ou un champ d'application, rien dans la question ne doit le contredire.

Un article peut partager du vocabulaire fiscal général avec la question (TVA, impôt, déclaration...) SANS répondre réellement à ce qui est demandé. Dans ce cas, marque-le comme non pertinent.

## Format de réponse OBLIGATOIRE (JSON strict, EXACTEMENT un objet par article candidat, dans le MÊME ordre que fourni)

{
  "evaluations": [
    {
      "index": 0,
      "reference": "Référence exacte de l'article telle que fournie",
      "pertinent": true,
      "justification": "Phrase courte expliquant pourquoi cet article répond, ou ne répond pas, à la question posée."
    }
  ]
}

IMPORTANT : le champ "index" doit correspondre exactement au numéro ARTICLE indiqué dans le bloc candidat (0 pour le premier article, 1 pour le second, etc.). Ne saute aucun article et n'en ajoute aucun.
"""


def filter_relevant_articles_for_question(
    query: str, candidates: list[ArticleMatch], label: str
) -> tuple[list[ArticleMatch], bool]:
    """
    Retourne (articles_pertinents, filter_ok). filter_ok=False signifie un
    échec technique du LLM de filtrage (pas un jugement "rien de pertinent")
    — à distinguer du cas légitime où filter_ok=True mais la liste est vide.
    """
    if not candidates:
        return [], True

    candidates_block = "\n\n".join(
        f"=== ARTICLE {i} : {m.reference} ({m.source_label}) ===\n{m.texte[:500]}"
        for i, m in enumerate(candidates)
    )

    prompt = f"""QUESTION DE L'UTILISATEUR :
{query}

ARTICLES CANDIDATS À ÉVALUER :
{candidates_block}

Évalue la pertinence de chaque article candidat pour répondre à cette question précise. Utilise le numéro ARTICLE indiqué comme valeur du champ "index".
"""

    result = llm_call_json(
        CHAT_RELEVANCE_FILTER_SYSTEM_PROMPT, prompt,
        label=f"filtrage_chat_{label}", model=GROQ_MODEL_FAST,
    )
    if result is None:
        return [], False

    evaluations = result.get("evaluations", [])
    print(f"[RAG-CHAT-DEBUG] {label} — brut du LLM : {json.dumps(evaluations, ensure_ascii=False)}")

    relevant = []
    for pos, e in enumerate(evaluations):
        idx = e.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
            idx = pos
            if idx >= len(candidates):
                continue
        if e.get("pertinent") is True:
            relevant.append(candidates[idx])

    return relevant, True


#: Séparateur utilisé par extract_circulaire.py pour articles_cgi_commentes.
_SEPARATEUR_REFERENCES_CIRCULAIRE = " | "


def _filtrer_circulaires_isolees(matches: list[ArticleMatch]) -> list[ArticleMatch]:
    """
    Une note circulaire DGI engage l'administration, pas le contribuable, et
    ne peut pas contredire le CGI — elle ne doit donc jamais être citée
    SEULE. Ce filtre retire tout résultat de type NOTE_CIRCULAIRE dont AUCUN
    des articles CGI qu'il commente (`articles_cgi_commentes`) n'apparaît
    parmi les AUTRES résultats du même lot.

    Ne s'applique qu'au chat (`retrieve_sourced_articles`) : l'audit
    n'atteint jamais ce point, les circulaires étant exclues dès le
    retrieval côté ai_auditor.py (`exclude_types=TYPES_EXCLUS_AUDIT`).
    """
    references_presentes = {m.reference for m in matches if m.type != "NOTE_CIRCULAIRE"}

    retenus = []
    for m in matches:
        if m.type != "NOTE_CIRCULAIRE":
            retenus.append(m)
            continue
        references_commentees = {
            r.strip() for r in (m.articles_cgi_commentes or "").split(_SEPARATEUR_REFERENCES_CIRCULAIRE) if r.strip()
        }
        if references_commentees & references_presentes:
            retenus.append(m)
        else:
            print(
                f"[RAG-CHAT] Circulaire écartée (isolée) : '{m.reference}' — aucun de ses articles CGI "
                f"commentés ({references_commentees or '—'}) n'est présent dans ce lot de résultats."
            )
    return retenus


def retrieve_sourced_articles(
    store: VectorStore, query: str, label: str, top_k_final: int = 5,
    top_k_candidates: int = CANDIDATE_TOP_K, langue: str | None = None,
) -> list[ArticleMatch]:
    """
    Point d'entrée unique pour le chat (dossier-scopé et général) :
    retrieval large + filtrage LLM. Si le filtrage échoue TECHNIQUEMENT
    (LLM indisponible), on se rabat sur les meilleurs candidats bruts
    plutôt que de bloquer complètement la réponse — le chat reste
    interactif, et generate_answer() a lui-même l'instruction de rester
    prudent / de signaler une incertitude si le contexte est faible. C'est
    un compromis assumé, différent du choix fait pour l'audit (module 3,
    non interactif) qui préfère échouer proprement plutôt que répondre sur
    un contexte non filtré.
    """
    search_query = _reformulate_question(query, label)
    if search_query:
        time.sleep(LLM_CALL_DELAY_SECONDS)
    else:
        # Repli sur la question brute. Acceptable en français ; pour une
        # question arabe c'est une recherche dégradée (13 % de recouvrement
        # mesuré, voir _reformulate_question), donc on le signale au lieu de
        # laisser croire à un fonctionnement normal.
        if est_arabe(langue):
            print(
                f"[RAG-CHAT] {label} — reformulation indisponible sur une question en {langue} : "
                "recherche dégradée, la question n'a pas pu être traduite en français."
            )
        search_query = query

    candidates = store.search(search_query, top_k=top_k_candidates)
    if not candidates:
        return []

    relevant, filter_ok = filter_relevant_articles_for_question(query, candidates, label)
    if not filter_ok:
        print(f"[RAG-CHAT] {label} — échec technique du filtrage LLM, repli sur les {top_k_final} meilleurs candidats bruts (non filtrés).")
        # Le filtre d'isolement s'applique même sur ce repli non jugé par le
        # LLM : une circulaire sans article CGI compagnon reste interdite de
        # citation seule, filtrage de pertinence disponible ou non.
        return _filtrer_circulaires_isolees(candidates)[:top_k_final]

    print(f"[RAG-CHAT] {label} — {len(candidates)} candidat(s) -> {len(relevant)} jugé(s) pertinent(s)")
    # Filtré AVANT la troncature à top_k_final : sinon un article CGI qui
    # justifie la présence d'une circulaire pourrait être coupé par la
    # limite alors que la circulaire, mieux classée, resterait — ce qui la
    # rendrait ensuite isolée par accident de tri plutôt que par un vrai
    # défaut de pertinence.
    return _filtrer_circulaires_isolees(relevant)[:top_k_final]
