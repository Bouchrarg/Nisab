"""
intention.py — Routage d'intention de l'assistant, AVANT tout appel RAG/LLM.

## Le problème que ce module corrige

`generate_answer` (generation.py) traite chaque question de la même façon :
reformulation LLM, retrieval, filtrage LLM, génération LLM avec structure à 4
sections obligatoires. Trois appels au modèle et 5 articles CGI complets dans
le prompt, quelle que soit la question.

Or une classe entière de questions n'a pas sa réponse dans le corpus fiscal :
« quand est ma prochaine déclaration de TVA ? » ne se trouve dans aucun
article du CGI, elle se CALCULE (voir tax_calendar.py, qui le fait déjà pour
GET /calendar/events). Envoyer cette question au RAG revenait à demander à un
LLM de lire l'Art. 110 pour en extraire une date d'échéance — cher, lent, et
moins fiable qu'un calcul déterministe qui existe déjà dans le produit.

## Pourquoi une regex d'abord, un LLM seulement en repli

Même logique que `detection_reglee.py` face à `ai_auditor.py` : ce qui peut
être CONSTATÉ (cette question porte-t-elle sur une date d'échéance ?) ne doit
pas être laissé au jugement d'un LLM, qui ajoute de la variance sans ajouter
d'information. Un classifieur LLM coûterait un appel de plus pour reproduire
ce qu'une liste de mots-clés fait déjà, gratuitement et de façon reproductible.
Le LLM rapide n'est sollicité que si aucune règle ne tranche — et seulement
pour distinguer "legale" de "hors_perimetre", jamais pour "echeance" (trop
risqué : un faux positif y court-circuiterait complètement le RAG).
"""

from __future__ import annotations

import re
from datetime import date

from app.llm_client import GROQ_MODEL_FAST, llm_call_json

#: Question porte sur UNE ÉCHÉANCE (date de dépôt/paiement). Calculable par
#: tax_calendar.py, jamais dans le corpus CGI en tant que tel.
_MARQUEURS_TEMPORELS = {
    "fr": re.compile(
        r"\b(quand|prochaine?s?|prochain|date limite|échéance|deadline|"
        r"avant quand|combien de temps|délai)\b", re.IGNORECASE,
    ),
    "ar_latin": re.compile(
        r"\b(imta|fuqach|chhal.{0,15}(baqi|delai)|akhir\s*ajal)\b", re.IGNORECASE,
    ),
    # Arabe standard : متى (quand), آخر أجل (délai limite), الموعد (l'échéance).
    "ar": re.compile(r"(متى|آخر\s*أجل|الموعد|موعد)"),
}

#: Objet fiscal concerné — sans ce second croisement, "quand" seul matcherait
#: trop de questions non temporelles ("quand une charge est-elle déductible").
_MARQUEURS_OBLIGATION = {
    "fr": re.compile(
        r"\b(déclaration|déclarer|d[ée]poser|paiement|payer|tva|is\b|ir\b|"
        r"acompte|cotisation|taxe professionnelle|liasse)\b", re.IGNORECASE,
    ),
    "ar_latin": re.compile(r"\b(tva|is|ir|déclaration|iqrar|khalass)\b", re.IGNORECASE),
    # التصريح (déclaration), الأداء/الدفع (paiement), الضريبة (impôt/taxe).
    "ar": re.compile(r"(التصريح|الأداء|الدفع|الضريبة|الإقرار)"),
}

_CLASSIFIEUR_SYSTEM_PROMPT = """Tu classes une question fiscale posée à un assistant marocain en une seule catégorie :

- "legale" : la question porte sur une règle de droit fiscal marocain (taux, déductibilité, obligation, sanction, procédure) — répondable à partir d'articles du Code Général des Impôts.
- "hors_perimetre" : la question ne porte pas sur la fiscalité marocaine (salutation, question générale, autre sujet).

Réponds uniquement en JSON : {"categorie": "legale"} ou {"categorie": "hors_perimetre"}."""


def classifier_intention(query: str, langue: str = "fr") -> str:
    """
    Retourne 'echeance' | 'legale' | 'hors_perimetre'.

    Déterministe d'abord (voir docstring du module). Le LLM n'est appelé que
    si aucun marqueur temporel n'a matché ET qu'aucune regex ne peut trancher
    entre "legale" et "hors_perimetre" — en pratique rare, la plupart des
    questions posées à un copilote fiscal parlent de fiscalité.
    """
    if not query or not query.strip():
        return "hors_perimetre"

    temporel = _MARQUEURS_TEMPORELS.get(langue, _MARQUEURS_TEMPORELS["fr"])
    obligation = _MARQUEURS_OBLIGATION.get(langue, _MARQUEURS_OBLIGATION["fr"])
    if temporel.search(query) and obligation.search(query):
        return "echeance"

    # Repli LLM, un seul appel, modèle rapide (le même GROQ_MODEL_FAST que la
    # reformulation/le filtrage RAG — cf. rag_retrieval.py). Sur échec
    # technique (aucun provider disponible, JSON invalide) : "legale" par
    # défaut — le pipeline RAG existant sait déjà répondre "aucune source"
    # proprement, alors que classer à tort en "hors_perimetre" rejetterait une
    # vraie question fiscale sans même essayer.
    result = llm_call_json(
        _CLASSIFIEUR_SYSTEM_PROMPT, query, label="intention_chat", model=GROQ_MODEL_FAST,
    )
    if result and result.get("categorie") == "hors_perimetre":
        return "hors_perimetre"
    return "legale"


def choisir_format_reponse(sources: list) -> str:
    """
    'bref' | 'complet', destiné à `generation.generate_answer`.

    Heuristique volontairement simple plutôt qu'un appel LLM de plus pour la
    trancher : quand le filtrage RAG (rag_retrieval.filter_relevant_articles_
    for_question) n'a retenu qu'UN SEUL article pertinent, la question a une
    réponse ponctuelle — pas besoin des 4 sections obligatoires du format
    complet pour dire "oui, à ce taux, sur cet article". Dès que plusieurs
    articles sont en jeu, la question mérite l'articulation complète (base
    légale de chacun, hiérarchisation) que le format bref ne permet pas.
    """
    return "bref" if len(sources) <= 1 else "complet"


#: Catégories de `tax_calendar.get_calendar_events` (champ "category"),
#: reconnues dans la question pour cibler l'échéance demandée plutôt que de
#: répondre "la prochaine" toutes obligations confondues. Ordre volontaire :
#: "Taxes Locales" avant "IS"/"IR", sinon "taxe professionnelle" ne matcherait
#: jamais son propre motif après un match trop tôt sur un mot plus court.
_CATEGORIES_ECHEANCE = {
    "TVA": re.compile(r"\btva\b", re.IGNORECASE),
    "Taxes Locales": re.compile(r"\btaxes?\s+professionnelles?\b|\btaxes?\s+locales?\b", re.IGNORECASE),
    "IS": re.compile(r"\bis\b|imp[oô]t\s+sur\s+les\s+soci[ée]t[ée]s", re.IGNORECASE),
    "IR": re.compile(r"\bir\b|imp[oô]t\s+sur\s+le\s+revenu", re.IGNORECASE),
    "CNSS": re.compile(r"\bcnss\b", re.IGNORECASE),
}

_MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _date_lisible(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {_MOIS_FR[d.month]} {d.year}"


def repondre_echeance(query: str, events: list[dict]) -> dict:
    """
    Construit une réponse d'UNE phrase à partir des échéances déjà calculées
    par `tax_calendar.get_calendar_events` — jamais de RAG, jamais de LLM.

    `events` est attendu trié par date croissante et déjà filtré sur des
    échéances futures (comportement par défaut de get_calendar_events).

    Renvoie toujours `sourced: False` : ces dates sont des littéraux Python
    (voir l'avertissement en tête de tax_calendar.py), pas des citations
    vérifiées contre le corpus. Répondre vite ne doit pas faire croire que la
    réponse est sourcée comme le reste du produit — c'est le même principe
    que `e["sourced"] = False` déjà posé par tax_calendar.py.
    """
    categorie = None
    for cat, pattern in _CATEGORIES_ECHEANCE.items():
        if pattern.search(query):
            categorie = cat
            break

    candidats = [e for e in events if categorie is None or e.get("category") == categorie]
    if not candidats:
        objet = f" pour {categorie}" if categorie else ""
        return {
            "answer": f"Aucune échéance à venir n'a pu être calculée{objet} sur l'horizon actuel de ce dossier.",
            "sourced": False,
            "category": categorie,
            "event": None,
        }

    prochaine = candidats[0]
    phrase = f"{prochaine['title']} — à déposer avant le {_date_lisible(prochaine['date'])}."
    if prochaine.get("penalty"):
        phrase += f" En cas de retard : {prochaine['penalty']}."
    phrase += (
        " (Date calculée depuis le calendrier fiscal du dossier, non issue d'une recherche "
        "dans le corpus légal — voir l'onglet Calendrier pour le détail.)"
    )

    return {
        "answer": phrase,
        "sourced": False,
        "category": prochaine.get("category"),
        "event": prochaine,
    }
