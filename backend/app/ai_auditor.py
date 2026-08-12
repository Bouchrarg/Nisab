from __future__ import annotations

import json
import os
import re
import threading
import time
from app.llm_client import llm_call_json, GROQ_MODEL_FAST
from app.regles_montant import (
    REFERENCES_AVEC_REGLE,
    CategorieMontant,
    ResultatMontant,
    amortissement_vehicule_tourisme_art10,
    categorie_art106,
    extraire_prix_vehicule,
    facture_mentions_obligatoires_art146,
    paiement_especes_art193,
    remuneration_tiers_non_declaree_art151,
    tva_non_deductible_art106,
)
from app.vectorstore import ArticleMatch, PgVectorStore, VectorStore

MODEL_NAME = "llama-3.3-70b-versatile"

CANDIDATE_TOP_K = 15

# Pause entre appels LLM pour respecter les quotas.
LLM_CALL_DELAY_SECONDS = 1.2

RETRY_PAUSE_SECONDS = 5.0


AUDIT_LEGAL_CONTEXT_CHAR_BUDGET = 6000

# Une note circulaire DGI engage l'administration, pas le contribuable, et ne
# peut pas fonder une anomalie à elle seule (règle d'architecture du projet).
# Exclue du pool de CANDIDATS de l'audit plutôt que filtrée après coup sur la
# sortie du LLM : l'audit ne peut ainsi jamais la citer, par construction. Le
# chat (rag_retrieval.py) reste la seule couche où une circulaire est
# retrouvable, sous réserve d'un article CGI compagnon dans le même lot de
# résultats (filtre appliqué là-bas, pas ici).
TYPES_EXCLUS_AUDIT = ["NOTE_CIRCULAIRE"]


_audit_lock = threading.Lock()


RELEVANCE_FILTER_SYSTEM_PROMPT = """Tu es un assistant qui présélectionne des articles de loi avant une analyse fiscale approfondie.

On te fournit une écriture comptable et une liste d'articles candidats retrouvés par recherche documentaire (donc potentiellement non pertinents malgré une proximité thématique ou lexicale). Chaque article candidat est numéroté (ARTICLE 0, ARTICLE 1, ...) dans l'ordre où il t'est présenté.

Pour CHAQUE article candidat, détermine si ses CONDITIONS D'APPLICATION correspondent raisonnablement aux faits de la transaction :
- secteur d'activité concerné (ex. un régime spécifique à un secteur ne s'applique pas hors de ce secteur) ;
- nature de l'opération ou du bien/service (achat, vente, prestation, type de bien) ;
- seuils de montant éventuels ;
- qualité des parties (assujetti, résident, etc.).

Un article peut partager du vocabulaire fiscal général avec la transaction (TVA, impôt, déclaration...) SANS que ses conditions d'application précises soient réunies. Dans ce cas, marque-le comme non pertinent. Ne suppose jamais qu'une condition est réunie si rien dans l'écriture ne l'indique explicitement.

Quand un article fixe un SEUIL CHIFFRÉ (montant, taux, délai) : ne compare JAMAIS de tête. Écris d'abord, dans la justification, les deux valeurs exactes extraites du texte ("montant transaction : X DH ; seuil de l'article : Y DH"), puis la comparaison arithmétique explicite ("X >= Y donc seuil atteint" ou "X < Y donc seuil non atteint"), et fais découler "pertinent" de ce calcul écrit — jamais l'inverse. Une conclusion sans les deux valeurs et l'opérateur de comparaison écrits noir sur blanc est invalide.

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
  "title": "Titre très court du problème fiscal (ex: Paiement en espèces >= 20 000 DH)",
  "description": "Explication claire de l'incohérence comptable par rapport au texte de loi, incluant pourquoi les conditions d'application de l'article sont réunies dans cette écriture précise.",
  "recommendation": "Action concrète pour régulariser la situation auprès de la DGI."
}

Si l'écriture est parfaitement conforme au regard du contexte fourni :
{
  "status": "conforme",
  "severity": "vert",
  "reference_cgi": "CGI 2026",
  "title": "Conforme",
  "description": "L'opération respecte la réglementation fiscale au regard des textes disponibles.",
  "recommendation": "Aucune action requise."
}

Si, malgré la présélection, le contexte ne permet toujours pas de conclure avec certitude :
{
  "status": "contexte_insuffisant",
  "severity": "vert",
  "reference_cgi": "Aucun article suffisamment concluant",
  "title": "Analyse non concluante",
  "description": "Explique précisément ce qui manque pour conclure.",
  "recommendation": "Vérification manuelle recommandée par un expert-comptable."
}

Règles strictes :
- Base ton analyse UNIQUEMENT sur le contexte juridique fourni ; ne complète jamais avec une connaissance générale non citée.
- N'affirme jamais qu'un régime particulier (ex. auto-liquidation) s'applique sans que la nature de l'opération (secteur, type de bien) l'indique explicitement dans l'écriture.
- Ne calcule et n'indique JAMAIS de montant en dirhams (exposition, amende, majoration). Ce n'est plus ton rôle : un module séparé calcule le montant par une formule déterministe à partir des données comptables réelles, une fois l'article identifié — jamais par estimation. Un chiffre que tu produirais toi-même ne serait vérifiable par personne.
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


QUERY_REFORMULATION_SYSTEM_PROMPT = """Tu aides à préparer une recherche documentaire dans le Code Général des Impôts marocain (CGI) et le Bulletin Officiel.

On te donne le résumé d'une écriture comptable. Identifie CHAQUE fait fiscalement significatif qu'elle contient — il peut y en avoir plusieurs à la fois, ne t'arrête pas au premier que tu remarques :
- le mode de règlement (espèces, virement, chèque...) — un paiement en espèces est fiscalement significatif EN LUI-MÊME, indépendamment de la nature de l'achat ou du service ;
- l'absence d'identifiants fiscaux du tiers (ICE, n° TVA / taxe professionnelle) ;
- la nature de la dépense ou de la prestation (nature du bien/service, secteur, rémunération versée à un tiers...).

Pour CHAQUE fait significatif identifié, génère une requête de recherche COURTE et FOCALISÉE SUR CE SEUL FAIT (une phrase, 8-15 mots), dans le vocabulaire fiscal/juridique utilisé par les textes de loi (ex: "rémunérations allouées à des tiers", "règlement des transactions en espèces"), plutôt que le vocabulaire comptable brut. NE MÉLANGE JAMAIS deux faits différents dans la même requête — une requête qui combine plusieurs sujets retrouve moins bien chaque sujet individuellement qu'une requête focalisée sur un seul.

Génère entre 1 et 3 requêtes selon le nombre de faits significatifs identifiés.

## Format de réponse OBLIGATOIRE (JSON strict)

{"queries": ["requête focalisée 1", "requête focalisée 2"]}

Règles :
- Ne mentionne AUCUN montant, nom de personne/société, ni numéro de pièce dans les requêtes.
- Réponds UNIQUEMENT avec le JSON, sans préambule.
"""


def _reformulate_queries(txn_summary: str, label: str) -> list[str]:
    """
    Reformule le résumé de transaction (vocabulaire comptable brut : montants,
    noms de tiers, "Mode: virement"...) en 1 à 3 requêtes courtes, chacune
    focalisée sur UN SEUL fait fiscalement significatif, dans le vocabulaire
    du corpus. Une requête unique qui mélange plusieurs faits (ex. rémunération
    non déclarée + paiement en espèces) dilue le signal et retrouve moins bien
    chaque article que des requêtes séparées — mesuré : Article 193 passe du
    41e rang (requête combinée) au 1er-2e rang (requête focalisée espèces
    seule). Retourne [] si l'appel échoue techniquement — l'appelant retombe
    alors sur _build_search_query().
    """
    result = llm_call_json(
        QUERY_REFORMULATION_SYSTEM_PROMPT, txn_summary,
        label=f"reformulation_{label}", model=GROQ_MODEL_FAST,
    )
    if not result:
        return []
    queries = result.get("queries", [])
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()][:3]



def _normalize_ref(ref: str) -> str:
    """
    Normalise une référence d'article pour comparaison (casse, espaces).

    ATTENTION — cette fonction alimente `_cle_metier` (routes_dossiers.py) :
    la clé métier d'une alerte vaut `"{pièce}|{ref normalisée}"`. En modifier
    le résultat changerait la clé de TOUTES les alertes existantes, qui
    seraient recréées au prochain audit et perdraient leur statut et leurs
    corrections validées. Pour assouplir une comparaison de références, ne
    touchez pas à celle-ci : utilisez `_cle_article` ci-dessous.
    """
    return " ".join((ref or "").lower().split())


#: Suffixes qui font partie de l'IDENTITÉ de l'article : « Article 45 bis »
#: est un article distinct de « Article 45 » dans le CGI, pas un paragraphe
#: de celui-ci. Ils doivent survivre à la canonicalisation.
_SUFFIXES_ARTICLE = "bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies"

_RE_ARTICLE = re.compile(rf"^(?:art\.?|articles?)\s*(\d+)(?:\s*-?\s*({_SUFFIXES_ARTICLE}))?\b")


def _cle_article(ref: str) -> str:
    """
    Réduit une référence à l'article qui la porte, subdivision retirée.

    « Article 11-II », « Article 11 II », « Article 10 (I-A, B et E) » et
    « Art. 11 » désignent tous le même article du corpus : le CGI est indexé
    au niveau de l'article, ses divisions romaines vivent DANS le texte. Un
    LLM à qui l'on donne le texte intégral de l'Article 11 cite naturellement
    « Article 11-II » puisque c'est le paragraphe applicable — refuser cette
    citation reviendrait à sanctionner une réponse plus précise que la
    question.

    En revanche « Article 45 bis » n'est PAS « Article 45 » : le suffixe latin
    est conservé (cf. `_SUFFIXES_ARTICLE`), sinon on rattacherait une citation
    à un texte de loi différent — exactement ce que le garde-fou empêche.

    Distincte de `_normalize_ref` À DESSEIN : celle-ci sert aux comparaisons,
    l'autre à l'identité persistée (clé métier). Les fusionner ferait dépendre
    l'identité des alertes d'une règle de comparaison qui, elle, a vocation à
    s'assouplir.
    """
    normalisee = _normalize_ref(ref)
    correspondance = _RE_ARTICLE.match(normalisee)
    if not correspondance:
        # Référence de forme inattendue : on retombe sur la comparaison
        # stricte plutôt que de deviner.
        return normalisee
    numero, suffixe = correspondance.group(1), correspondance.group(2)
    return f"article {numero} {suffixe}" if suffixe else f"article {numero}"


def _resolve_partner(move: dict, partner_map: dict) -> dict | None:
    pid = move.get("partner_id", [None])[0] if isinstance(move.get("partner_id"), list) else None
    return partner_map.get(pid) if pid else None


def _lignes_du_move(move: dict, lignes: list[dict]) -> list[dict]:
    move_id = move.get("id")
    return [l for l in lignes if isinstance(l.get("move_id"), list) and l["move_id"][0] == move_id]


def calculer_montant_regle(reference_cgi: str, move: dict, lignes: list[dict]) -> ResultatMontant:
    """
    Calcule le montant d'une anomalie déjà identifiée par le RAG, via
    `app.regles_montant` — jamais via le LLM (voir la règle retirée du
    AUDIT_SYSTEM_PROMPT). `reference_cgi` est déjà passé par le garde-fou
    anti-hallucination de `_audit_single_move` avant d'arriver ici : cette
    fonction se contente d'extraire, depuis `move`/`lignes` (le pivot Odoo
    déjà en mémoire, aucun nouvel appel réseau), les arguments que la règle
    correspondante attend.

    Toute référence sans règle enregistrée retombe sur `non_calculable` —
    c'est le comportement par défaut, pas une exception à gérer : un article
    nouvellement retrouvé par le RAG (ex. un article encore non couvert par
    `regles_montant`) ne doit jamais silencieusement hériter d'un montant.
    """
    ref = _normalize_ref(reference_cgi)
    if ref not in REFERENCES_AVEC_REGLE:
        return ResultatMontant(
            CategorieMontant.non_calculable, None,
            f"Aucune règle de calcul déterministe n'existe encore pour « {reference_cgi} » : "
            "montant non chiffré automatiquement, vérification manuelle requise.",
        )

    lignes_move = _lignes_du_move(move, lignes)

    if ref == "article 193":
        return paiement_especes_art193(move, lignes)

    if ref == "article 10":
        # Le prix d'acquisition TTC n'est pas un champ structuré du pivot
        # Odoo (voir regles_montant.extraire_prix_vehicule) : on le cherche
        # dans tout texte libre disponible sur ce move — d'où
        # `calculable_hypothese` en sortie, jamais `calculable` pur.
        textes = " ".join(filter(None, [
            move.get("ref"), move.get("name"),
            *(str(l.get("name") or "") for l in lignes_move),
        ]))
        prix = extraire_prix_vehicule(textes)
        dotation = sum(float(l.get("debit") or 0) for l in lignes_move) or None
        return amortissement_vehicule_tourisme_art10(prix, dotation)

    if ref == "article 106":
        # tax_line_id truthy = ligne de TVA elle-même (convention Odoo) ;
        # les autres lignes du move portent la nature de la dépense, seule
        # source qu'on interroge pour catégoriser (mots-clés, pas de LLM).
        montant_tva = sum(float(l.get("debit") or 0) for l in lignes_move if l.get("tax_line_id"))
        morceaux_charge: list[str] = []
        for l in lignes_move:
            if l.get("tax_line_id"):
                continue
            compte = l.get("account_id")
            if isinstance(compte, list) and len(compte) > 1:
                morceaux_charge.append(str(compte[1]))
            if l.get("name"):
                morceaux_charge.append(str(l["name"]))
        categorie = categorie_art106(" ".join(morceaux_charge))
        return tva_non_deductible_art106(montant_tva, categorie)

    if ref == "article 11":
        # Seule règle du module qui ne se calcule PAS écriture par écriture :
        # les limites de l'Art. 11-II sont par (fournisseur, jour) et par
        # (fournisseur, mois), donc il faut le lot complet des écritures du
        # fournisseur — que cette fonction, appelée move par move, n'a pas.
        # Le chiffrage est fait par `detection_reglee.detecter()`, qui voit
        # tout le pivot d'un coup. Si on arrive ici, c'est que le RAG a
        # retenu l'Art. 11 sans que la détection déterministe ait pu établir
        # un règlement en espèces : on ne chiffre pas plutôt que d'annoncer
        # un 0 DH qui vaudrait "aucun risque".
        return ResultatMontant(
            CategorieMontant.non_calculable, None,
            "Les limites de l'Art. 11-II CGI s'apprécient par fournisseur et par jour "
            "(5 000 DH), sous plafond mensuel (50 000 DH) : elles ne peuvent pas être "
            "chiffrées sur une écriture isolée. Aucun règlement en espèces n'a par ailleurs "
            "été identifié automatiquement sur cette pièce — vérification manuelle requise.",
        )

    if ref == "article 146":
        return facture_mentions_obligatoires_art146()

    if ref == "article 151":
        # Le statut du bénéficiaire au regard de la retenue à la source
        # (Art. 15 bis / 45 bis) n'est jamais deviné automatiquement — c'est
        # un statut fiscal du tiers, aucune donnée comptable ne le porte.
        # Retourne systématiquement non_calculable ; voir regles_montant.py.
        return remuneration_tiers_non_declaree_art151(None, None, None)

    # Ne devrait jamais arriver : ref est dans REFERENCES_AVEC_REGLE mais
    # aucune branche ci-dessus ne le traite — les deux ont divergé, à
    # corriger plutôt qu'à masquer derrière un montant par défaut.
    raise AssertionError(
        f"'{ref}' déclaré dans REFERENCES_AVEC_REGLE mais aucun dispatch codé dans _calculer_montant_regle."
    )


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


def _audit_single_move(
    move: dict,
    lines: list[dict],
    partner: dict | None,
    store: PgVectorStore | None,
    has_llm: bool,
    top_k_legal: int,
    document_id: str | None = None,
) -> tuple[dict | None, bool, dict | None]:
    """
    Audite une écriture comptable unique : retrieval -> filtrage LLM ->
    analyse de conformité. Utilisée à la fois pour le passage principal et
    pour la passe de retry, afin de garantir un comportement identique.

    Retourne (finding, technical_failure, inconclusive) :
    - finding est un dict d'anomalie, ou None si conforme / contexte
      insuffisant / échec technique ;
    - technical_failure est True UNIQUEMENT si l'absence de finding est due
      à un problème technique (pas un vrai résultat), pour permettre un
      retry ciblé côté appelant ;
    - inconclusive est un dict {invoice, description} UNIQUEMENT quand le
      contexte a été jugé insuffisant pour conclure (un vrai résultat, pas
      un échec) — cf. cahier des charges, "zones grises renvoyées à
      l'expert" : ne doit jamais être silencieusement confondu avec
      "conforme" côté appelant.
    """
    move_label = move.get("name", f"move_{move.get('id')}")
    txn_summary = _build_transaction_summary(move, lines, partner)

    # 1. Retrieval large (rappel) — la requête est reformulée en 1-3 requêtes
    # focalisées (vocabulaire fiscal) avant recherche quand un LLM est
    # disponible : le vocabulaire comptable brut (montants, noms de tiers,
    # "Mode: virement", numéros de pièce) noie le signal sémantique et fait
    # manquer des articles pourtant pertinents ; une requête unique qui
    # mélangerait plusieurs faits fiscaux à la fois dilue aussi le signal
    # (mesuré sur des cas réels). Une recherche par requête focalisée,
    # candidats fusionnés et dédupliqués par référence. Fallback sur
    # _build_search_query() si la reformulation échoue techniquement, ne
    # renvoie rien, ou si aucun LLM n'est disponible.
    candidates: list[ArticleMatch] = []
    if store:
        reformulated_queries = _reformulate_queries(txn_summary, move_label) if has_llm else []
        if reformulated_queries:
            time.sleep(LLM_CALL_DELAY_SECONDS)
            seen_refs: set[str] = set()
            merged: list[ArticleMatch] = []
            for q in reformulated_queries:
                for m in store.search(q, top_k=10, document_id=document_id, exclude_types=TYPES_EXCLUS_AUDIT):
                    if m.reference not in seen_refs:
                        seen_refs.add(m.reference)
                        merged.append(m)
            merged.sort(key=lambda m: m.score, reverse=True)
            candidates = merged[:top_k_legal]
        else:
            search_query = _build_search_query(move, txn_summary, partner)
            candidates = store.search(
                search_query, top_k=top_k_legal, document_id=document_id, exclude_types=TYPES_EXCLUS_AUDIT,
            )

    if not candidates:
        print(f"[RAG] {move_label} — aucun candidat retrouvé, contexte insuffisant (résultat réel, pas un échec).")
        return None, False, {
            "invoice": move_label,
            "description": "Aucun article du corpus fiscal retrouvé pour cette écriture.",
        }

    if not has_llm:
        print(f"[RAG] {move_label} — aucun LLM disponible (GROQ_API_KEY et OPENROUTER_KEY absents), audit ignoré.")
        return None, True, None

    # 2. Filtrage de pertinence
    relevant_articles, justifications, filter_ok = _filter_relevant_articles(txn_summary, candidates, move_label)

    if not filter_ok:
        print(f"[RAG] {move_label} — ÉCHEC TECHNIQUE du filtrage (pas un vrai résultat), écriture non auditée cette fois-ci.")
        return None, True, None

    print(f"[RAG] {move_label} — {len(candidates)} candidat(s) -> {len(relevant_articles)} jugé(s) pertinent(s) "
          f"({', '.join(m.reference for m in candidates)})")

    if not relevant_articles:
        print(f"[RAG] {move_label} — aucun candidat jugé applicable après filtrage, contexte insuffisant (résultat réel).")
        return None, False, {
            "invoice": move_label,
            "description": f"{len(candidates)} article(s) retrouvé(s) mais aucun jugé applicable à cette écriture après analyse de pertinence.",
        }

    time.sleep(LLM_CALL_DELAY_SECONDS)

    # 3. Analyse de conformité, uniquement sur les articles filtrés. Budget
    # de caractères réparti entre les articles retenus plutôt qu'un cutoff
    # fixe (voir AUDIT_LEGAL_CONTEXT_CHAR_BUDGET).
    per_article_budget = max(500, AUDIT_LEGAL_CONTEXT_CHAR_BUDGET // max(1, len(relevant_articles)))
    legal_context = "\n\n".join(
        f"=== ARTICLE {m.reference} ({m.source_label}) ===\n{m.texte[:per_article_budget]}\n"
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
        return None, True, None

    status = audit_result.get("status", "contexte_insuffisant")

    if status == "anomalie":
        # Garde-fou anti-hallucination : reference_cgi est du texte libre
        # renvoyé par le LLM, jamais garanti correspondre à un article
        # réellement fourni. On ne fait pas confiance au prompt seul.
        reference_cgi = audit_result.get("reference_cgi", "") or ""
        valid_refs = {_normalize_ref(m.reference) for m in relevant_articles}
        if _normalize_ref(reference_cgi) not in valid_refs:
            fallback_ref = relevant_articles[0].reference
            print(f"[RAG] {move_label} — référence '{reference_cgi}' non reconnue parmi les sources fournies, "
                  f"remplacée par '{fallback_ref}' (garde-fou anti-hallucination).")
            reference_cgi = fallback_ref

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

        # Montant calculé APRÈS le garde-fou anti-hallucination ci-dessus :
        # reference_cgi est ici garanti correspondre à un article réellement
        # fourni, jamais à du texte libre inventé par le LLM. Le LLM ne
        # produit plus aucun chiffre en DH (voir AUDIT_SYSTEM_PROMPT) — c'est
        # cette fonction, déterministe, qui décide s'il y a un montant et
        # lequel.
        resultat_montant = calculer_montant_regle(reference_cgi, move, lines)

        finding = {
            "rule": f"ai_rag_{move.get('id')}",
            "status": status,
            "severity": audit_result.get("severity", "orange"),
            "reference_cgi": reference_cgi,
            "title": audit_result.get("title", "Anomalie détectée par l'IA"),
            "description": audit_result.get("description", ""),
            "amount_risk": resultat_montant.montant,
            "categorie_montant": resultat_montant.categorie.value,
            "montant_detail": resultat_montant.detail,
            "montant_hypothese": resultat_montant.hypothese,
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
        }
        return finding, False, None

    if status == "contexte_insuffisant":
        print(f"[RAG] {move_label} — contexte jugé insuffisant même après filtrage (résultat réel) : "
              f"{audit_result.get('description', '')}")
        return None, False, {
            "invoice": move_label,
            "description": audit_result.get("description") or "Le contexte juridique retrouvé ne permet pas de conclure avec certitude.",
        }

    # status == "conforme" -> rien à ajouter
    return None, False, None


def run_ai_rag_audit(
    odoo_data: dict, top_k_legal: int = CANDIDATE_TOP_K, document_id: str | None = None
) -> tuple[list[dict], list[str], list[dict]]:
    """
    Exécute l'audit RAG IA en deux étapes par écriture. Protégé par un verrou
    global (_audit_lock) : si cette fonction est appelée alors qu'une exécution
    est déjà en cours, l'appel attend son tour.

    `document_id` (optionnel) contraint le RAG à un seul document du corpus
    (ex: "cgi_2024") au lieu de chercher sans distinction parmi tous les
    millésimes valides — utile pour auditer explicitement contre une version
    donnée du CGI plutôt que contre "tout ce qui est valide aujourd'hui".

    Retourne (findings, technical_failures, inconclusive) :
    - technical_failures liste les écritures non concluantes à cause d'un
      échec technique (rate limit persistant, JSON invalide), après une
      passe de retry ;
    - inconclusive liste les écritures pour lesquelles le contexte juridique
      disponible ne permet pas de conclure (un vrai résultat d'audit, pas un
      échec) — cf. cahier des charges, "zones grises renvoyées à l'expert".
    Ni l'une ni l'autre ne doit être confondue avec des écritures jugées
    conformes.
    """
    with _audit_lock:
        return _run_ai_rag_audit_locked(odoo_data, top_k_legal, document_id)


def _run_ai_rag_audit_locked(
    odoo_data: dict, top_k_legal: int, document_id: str | None = None
) -> tuple[list[dict], list[str], list[dict]]:
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

    findings: list[dict] = []
    inconclusive: list[dict] = []
    failed_moves: list[dict] = []  # écritures en échec technique, conservées pour la passe de retry
    auditable_moves = [m for m in moves if m.get("move_type") in ("in_invoice", "entry")]

    for idx, move in enumerate(auditable_moves):
        if idx > 0:
            time.sleep(LLM_CALL_DELAY_SECONDS)
        partner = _resolve_partner(move, partner_map)
        finding, technical_failure, inconclusive_info = _audit_single_move(
            move, lines, partner, store, has_llm, top_k_legal, document_id
        )
        if finding is not None:
            findings.append(finding)
        elif technical_failure:
            failed_moves.append(move)
        elif inconclusive_info is not None:
            inconclusive.append(inconclusive_info)

    technical_failures: list[str] = []
    if failed_moves:
        move_labels = [m.get("name", f"move_{m.get('id')}") for m in failed_moves]
        print(f"\n[RAG] {len(failed_moves)} écriture(s) en échec technique après le run principal, "
              f"retry unique après une pause de {RETRY_PAUSE_SECONDS:.0f}s : {move_labels}")
        time.sleep(RETRY_PAUSE_SECONDS)

        for idx, move in enumerate(failed_moves):
            if idx > 0:
                time.sleep(LLM_CALL_DELAY_SECONDS)
            partner = _resolve_partner(move, partner_map)
            finding, technical_failure, inconclusive_info = _audit_single_move(
            move, lines, partner, store, has_llm, top_k_legal, document_id
        )
            if finding is not None:
                findings.append(finding)
            elif technical_failure:
                technical_failures.append(move.get("name", f"move_{move.get('id')}"))
            elif inconclusive_info is not None:
                inconclusive.append(inconclusive_info)

        if technical_failures:
            print(f"\n[RAG] ATTENTION : {len(technical_failures)} écriture(s) toujours non auditée(s) après retry "
                  f"(échec technique persistant), PAS parce qu'elles sont conformes ou sans risque : {technical_failures}")

    severity_order = {"rouge": 0, "orange": 1, "vert": 2}
    findings.sort(key=lambda f: severity_order.get(f.get("severity", "vert"), 99))
    return findings, technical_failures, inconclusive


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
    _store = PgVectorStore()
    for _label, _query in {
        "auto-liquidation déchets": "Achat déchets métalliques et de récupération industrielle",
        "ICE manquant": "Facture fournisseur sans ICE ni numéro de TVA renseigné",
        "frais restaurant": "Note de frais restaurant équipe commerciale",
        "fournitures bureau": "Achat de fournitures de bureau papeterie",
    }.items():
        print(f"\n--- {_label} ---")
        debug_retrieval(_store, _query)