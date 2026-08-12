"""
text_cleaning.py — Nettoyage des artefacts d'extraction PDF dans le texte des
articles du corpus fiscal (numéros de notes de bas de page collés aux mots,
ruptures de page avec en-tête répété, blocs de définitions de notes insérés
en plein milieu d'un article).

Appliqué UNIQUEMENT à l'affichage (réponses HTTP consommées par le
frontend) — jamais au texte stocké en base ni à ce qui nourrit les
embeddings ou les prompts LLM. La recherche RAG et l'audit ne sont donc pas
concernés par ce nettoyage.
"""

from __future__ import annotations

import re

# Bloc de définition de note de bas de page sur sa propre ligne : dans ce
# corpus, un paragraphe de corps de texte ne commence jamais une ligne par un
# nombre brut suivi d'une majuscule — seules les notes le font ("685 Article
# 6 de la loi...", "1070 Loi n° 47-06 relative à...", "1075 Dahir..."). On
# généralise plutôt que d'énumérer chaque formule d'introduction possible
# (Article/Articles/Loi/Dahir/Décret/Cf. ...).
_FOOTNOTE_DEF_RE = re.compile(r"(?m)^\d{3,4}[ \t]+[A-ZÀ-Ÿ].*$\n?")

# Rupture de page CGI : numéro de page seul suivi de l'en-tête courant répété,
# insérés au milieu d'une phrase par l'extraction PDF.
_PAGE_BREAK_CGI_RE = re.compile(r"\n\d{1,4}\nCODE GÉNÉRAL DES IMPÔTS\n")

# Numéro de note de bas de page collé sans espace à la fin d'un mot, d'un
# chiffre romain (ex: "VIII1075") ou d'une ponctuation fermante (ex:
# "déduite688", "Bitamlik »698"). Les vrais nombres du texte légal sont
# toujours précédés d'un espace ou d'une parenthèse ("60 mois", "n° 38-16") :
# jamais collés directement à une lettre, donc ce pattern ne les touche pas.
_FOOTNOTE_MARKER_RE = re.compile(r"(?<=[a-zà-ÿA-ZÀ-Ÿ»’”])\d{1,4}(?=[\s.,;:)\]—]|$)")

# Numéro de note de bas de page isolé sur sa propre ligne, sans texte de
# définition à la suite (ex: "de la compensation.\n2019\nToutefois, ...").
# 3-4 chiffres seulement (comme _FOOTNOTE_DEF_RE) pour ne pas risquer de
# retirer un vrai nombre court qui se retrouverait seul sur une ligne à
# cause d'un retour à la ligne PDF.
_ORPHAN_FOOTNOTE_RE = re.compile(r"(?m)^\d{3,4}\n")

_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def clean_article_text(text: str | None) -> str | None:
    if not text:
        return text
    t = _FOOTNOTE_DEF_RE.sub("", text)
    t = _PAGE_BREAK_CGI_RE.sub("\n", t)
    t = _ORPHAN_FOOTNOTE_RE.sub("", t)
    t = _FOOTNOTE_MARKER_RE.sub("", t)
    t = _MULTI_BLANK_RE.sub("\n\n", t)
    return t.strip()
