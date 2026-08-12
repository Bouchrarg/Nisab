"""
control_simulator.py — Simulation de contrôle fiscal .

Rejoue, dossier par dossier, les points qu'un inspecteur DGI examinerait :
regroupe les AlerteRisque ouvertes par thème de contrôle, puis demande au
LLM, pour chaque thème, un argumentaire de défense sourcé + un plan de
remédiation concret.

Ne relance AUCUNE recherche RAG : réutilise directement reference_cgi /
rag_sources_json déjà persistés sur chaque AlerteRisque au moment de
l'audit (voir routes_dossiers._execute_audit). Même exigence
anti-hallucination que generation.py — zéro affirmation sans source déjà
établie ailleurs dans le pipeline.

Usage interne au cabinet uniquement : rien n'est transmis à la DGI .
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.api import get_vectorstore
from app.llm_client import llm_call_json
from app.models import AlerteRisque

CORPUS_VERSION = "CGI 2026"

# Classification par mots-clés plutôt que par appel LLM supplémentaire :
# suffisant vu le nombre de thèmes fixes et le vocabulaire relativement
# stable des titres/descriptions produits par ai_auditor.py. Si le nombre
# de thèmes ou leur diversité augmente significativement, remplacer par une
# classification LLM légère .
THEME_KEYWORDS: dict[str, list[str]] = {
    "TVA déductible": ["tva déductible", "tva non déductible", "auto-liquidation"],
    "Charges non déductibles": ["charge non déductible", "charges non déductibles", "amortissement", "véhicule tourisme"],
    "Facturation et pièces justificatives": [
        "facture régulière", "factures régulières", "pièce probante", "pièces probantes",
        "pièce justificative", "pièces justificatives", "facture irrégulière", "facture irrégulières",
        "ice", "n° tva",
    ],
    "Cotisation minimale": ["cotisation minimale"],
    "Retenue à la source": ["retenue à la source", "rémunérations allouées"],
    # "espèces" seul suffit à couvrir la classification (voir _classify_theme) ;
    # le seuil vérifié dans le corpus est 20 000 DH, pas 5 000 DH (cf.
    # regles_montant.SEUIL_ESPECES_ART193) — mots-clés alignés en conséquence.
    "Paiement en espèces": ["espèces", ">= 20 000 dh", "20000 dh"],
}
FALLBACK_THEME = "Autres points de vigilance"

# Capture le titre officiel d'un article à partir de son texte de loi, ex.
# "Article 102.- Régime des biens amortissables" -> "Régime des biens amortissables".
_ARTICLE_TITLE_RE = re.compile(r"Article\s+\S+\s*\.-\s*(.+)")


def _extract_article_titles(references: list[str]) -> dict[str, str]:
    """
    Va chercher, pour chaque référence citée, le titre officiel de l'article
    dans le corpus (texte de loi vérifié, pas une paraphrase LLM). Best-effort :
    une référence absente du corpus ou sans titre extractible est simplement
    absente du dict retourné, `_classify_theme` retombe alors sur le texte de
    l'alerte seul.
    """
    texts = get_vectorstore().get_texts_by_references(references)
    titles: dict[str, str] = {}
    for ref, texte in texts.items():
        m = _ARTICLE_TITLE_RE.search(texte)
        if m:
            titles[ref] = m.group(1).strip()
    return titles


@dataclass
class ThemeGroup:
    theme: str
    alertes: list[AlerteRisque] = field(default_factory=list)

    @property
    def exposition_totale(self) -> float:
        # cf. app.regles_montant : une alerte "non_calculable" a
        # montant_exposition=None, exactement comme une alerte antérieure au
        # moteur de règles — mais ce N'EST PAS un 0 DH vérifié. La compter
        # comme telle sous-estimerait silencieusement l'exposition présentée
        # dans un argumentaire de défense censé être honnête sur les points
        # fragiles (cf. SIMULATION_SYSTEM_PROMPT). Voir nb_non_chiffrables.
        return sum(float(a.montant_exposition) for a in self.alertes
                   if a.categorie_montant != "non_calculable" and a.montant_exposition is not None)

    @property
    def nb_non_chiffrables(self) -> int:
        return sum(1 for a in self.alertes if a.categorie_montant == "non_calculable")

    @property
    def articles_cites(self) -> list[str]:
        refs: set[str] = set()
        for a in self.alertes:
            if a.reference_cgi:
                refs.add(a.reference_cgi)
            for s in (a.rag_sources_json or []):
                refs.add(s)
        return sorted(refs)


def _classify_theme(alerte: AlerteRisque, article_titles: dict[str, str]) -> str:
    # Le titre officiel de l'article (texte de loi, verifié) est ajouté au
    # texte libre généré par l'audit plutôt que de le remplacer : un titre
    # d'article est parfois trop générique à lui seul (ex. Article 193 ne
    # mentionne pas "espèces" dans son titre), alors que la description de
    # l'alerte, elle, décrit le fait précis constaté.
    refs = [alerte.reference_cgi] if alerte.reference_cgi else []
    refs += list(alerte.rag_sources_json or [])
    titres = " ".join(article_titles[r] for r in refs if r in article_titles)

    haystack = f"{titres} {alerte.titre} {alerte.description} {alerte.reference_cgi or ''}".lower()
    # Score = nombre de mots-clés touchés, pas premier thème qui matche : une
    # alerte peut légitimement toucher plusieurs thèmes (ex. "ice" évoque à la
    # fois la facturation et la TVA) — c'est le thème le PLUS représenté dans
    # le texte qui doit l'emporter, pas celui déclaré en premier dans le dict.
    best_theme, best_score = FALLBACK_THEME, 0
    for theme, keywords in THEME_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in haystack)
        if score > best_score:
            best_theme, best_score = theme, score
    return best_theme


def _group_by_theme(alertes: list[AlerteRisque]) -> list[ThemeGroup]:
    all_refs: set[str] = set()
    for a in alertes:
        if a.reference_cgi:
            all_refs.add(a.reference_cgi)
        all_refs |= set(a.rag_sources_json or [])
    article_titles = _extract_article_titles(sorted(all_refs))

    groups: dict[str, ThemeGroup] = {}
    for a in alertes:
        theme = _classify_theme(a, article_titles)
        groups.setdefault(theme, ThemeGroup(theme=theme)).alertes.append(a)
    # Thèmes les plus exposés en premier — c'est ce qu'un inspecteur regarderait d'abord.
    return sorted(groups.values(), key=lambda g: g.exposition_totale, reverse=True)


SIMULATION_SYSTEM_PROMPT = """Tu es Nisab, un copilote fiscal qui aide un cabinet comptable marocain à se préparer à un contrôle fiscal.

On te fournit un THÈME de contrôle et la liste des anomalies déjà détectées par l'audit sur ce thème, avec les articles du CGI déjà retenus comme base légale pour chacune. Tu ne dois PAS chercher ou inventer de nouveaux articles : base-toi UNIQUEMENT sur ceux fournis.

Produis :
1. Un ARGUMENTAIRE DE DÉFENSE : comment le cabinet peut présenter/justifier chaque point face à un inspecteur, en citant explicitement les articles fournis, et en étant honnête sur les points réellement fragiles (ne minimise pas un risque réel).
2. Un PLAN DE RÉMÉDIATION : actions concrètes et priorisées pour régulariser la situation avant un contrôle réel.

## Format de réponse OBLIGATOIRE (JSON strict)

{
  "argumentaire": "Texte structuré, plusieurs paragraphes si besoin, citant les articles fournis par leur référence exacte.",
  "plan_remediation": "Liste d'actions concrètes, priorisées, sous forme de texte structuré (peut utiliser des tirets)."
}

Règles strictes :
- N'invente aucun article ni aucune règle non fournie dans le contexte.
- Reste concis, opérationnel, rédigé pour un collaborateur de cabinet qui doit défendre le dossier.
- Si les alertes fournies pour ce thème sont contradictoires ou insuffisantes pour un argumentaire solide, dis-le explicitement plutôt que de forcer une justification.
"""


def _montant_alerte_pour_prompt(a: AlerteRisque) -> str:
    # "0.00 DH" pour une alerte non_calculable affirmerait un fait vérifié
    # (aucun risque financier) là où la vérité est "on ne sait pas encore
    # chiffrer" — deux choses très différentes pour un argumentaire censé
    # rester honnête sur les points fragiles.
    if a.categorie_montant == "non_calculable":
        return "montant non chiffrable automatiquement (vérification manuelle requise)"
    return f"exposition estimée : {float(a.montant_exposition or 0):,.2f} DH"


def _build_theme_prompt(group: ThemeGroup) -> str:
    alertes_block = "\n\n".join(
        f"- {a.titre} (référence : {a.reference_cgi or 'non renseignée'}, "
        f"{_montant_alerte_pour_prompt(a)})\n"
        f"  Constat : {a.description}"
        for a in group.alertes
    )
    caveat = (
        f" (+ {group.nb_non_chiffrables} anomalie(s) du thème sans montant chiffrable automatiquement, "
        "hors ce total — ne pas en déduire une absence de risque)"
        if group.nb_non_chiffrables else ""
    )
    return f"""THÈME DE CONTRÔLE : {group.theme}
Exposition financière cumulée sur ce thème : {group.exposition_totale:,.2f} DH{caveat}

ANOMALIES DÉTECTÉES SUR CE THÈME :
{alertes_block}

Articles déjà retenus pour ce thème (base légale à utiliser, ne pas en ajouter d'autres) :
{', '.join(group.articles_cites) or 'Aucun article de référence disponible'}
"""


def run_simulation(dossier_id, alertes_ouvertes: list[AlerteRisque]) -> dict:
    """
    Construit le rapport de simulation à partir des alertes ouvertes déjà
    chargées (fournies par l'appelant, filtrées par RLS en amont).

    Retourne {"rapport_json": {...}, "plan_remediation_json": {...},
    "articles_cites": [...]} — prêt à être persisté par l'appelant dans
    SimulationControle + CitationSimulation.
    """
    if not alertes_ouvertes:
        return {
            "rapport_json": {
                "themes": [],
                "message": "Aucune alerte de risque ouverte sur ce dossier — rien à simuler pour le moment. "
                           "Lancez d'abord (ou relancez) l'audit fiscal.",
            },
            "plan_remediation_json": {"themes": []},
            "articles_cites": [],
        }

    groups = _group_by_theme(alertes_ouvertes)

    themes_rapport = []
    themes_plan = []
    all_articles: set[str] = set()

    for group in groups:
        prompt = _build_theme_prompt(group)
        result = llm_call_json(
            SIMULATION_SYSTEM_PROMPT, prompt,
            label=f"simulation_{group.theme}",
        )
        argumentaire = (result or {}).get("argumentaire") or (
            "Analyse indisponible pour ce thème (échec du provider LLM) — à traiter manuellement."
        )
        plan_remediation = (result or {}).get("plan_remediation") or (
            "Plan de remédiation indisponible pour ce thème — vérification manuelle recommandée."
        )

        all_articles |= set(group.articles_cites)

        themes_rapport.append({
            "theme": group.theme,
            "nb_alertes": len(group.alertes),
            "exposition_totale_mad": group.exposition_totale,
            "nb_non_chiffrables": group.nb_non_chiffrables,
            "articles_cites": group.articles_cites,
            "alerte_ids": [str(a.id) for a in group.alertes],
            "argumentaire": argumentaire,
        })
        themes_plan.append({
            "theme": group.theme,
            "plan_remediation": plan_remediation,
        })

    return {
        "rapport_json": {"themes": themes_rapport},
        "plan_remediation_json": {"themes": themes_plan},
        "articles_cites": sorted(all_articles),
    }
