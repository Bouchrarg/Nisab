"""
langue.py — Détection de la langue d'une question posée à l'assistant.

## Pourquoi pas une librairie

`langdetect` ou `fasttext` pèsent ~1 Mo et un modèle statistique pour résoudre
ici un problème à trois issues, dont deux se décident sur l'alphabet. Sur un
PFA où chaque ligne doit pouvoir être expliquée à l'oral, une règle de vingt
lignes qu'on comprend bat un modèle qu'on subit.

Et surtout : aucune librairie généraliste ne reconnaît la **darija en
caractères latins** (« chhal ghadi n7ess f TVA »), qui est précisément le cas
d'usage visé par le cahier des charges. Elle serait classée « français »,
« turc » ou « indonésien » selon les jours.

## Les trois issues

    'ar'        arabe en alphabet arabe        -> réponse en arabe standard
    'ar_latin'  darija en caractères latins    -> réponse en darija
    'fr'        français (défaut)              -> réponse en français

## Le seuil de 0,30

Une question arabe contient des chiffres, de la ponctuation et souvent des
termes techniques en français (« TVA », « IS »). Exiger une majorité de
caractères arabes raterait « شحال غادي ندفع ف TVA ». 30 % de codepoints arabes
est atteint dès qu'une phrase est réellement en arabe, et jamais par une
question française qui citerait un mot arabe isolé.
"""

from __future__ import annotations

import re

#: Plage Unicode de l'arabe (U+0600–U+06FF), qui couvre l'arabe standard et
#: les lettres additionnelles utilisées au Maghreb.
_ARABE = re.compile(r"[؀-ۿ]")

#: Proportion de caractères arabes au-delà de laquelle la question est arabe.
SEUIL_ARABE = 0.30

#: Marqueurs de darija translittérée. Choisis pour être discriminants : ce sont
#: des mots-outils très fréquents en darija et absents du français. Les chiffres
#: (3 pour ع, 7 pour ح, 9 pour ق) sont la convention d'écriture de l'arabizi et
#: n'apparaissent pas ainsi en français.
_MARQUEURS_DARIJA = {
    "chhal", "ch7al", "kifach", "kifash", "wach", "wash", "bghit", "bghina",
    "chnou", "chno", "achno", "3lach", "3la", "daba", "dyal", "dyali", "mzyan",
    "khass", "khassni", "wakha", "safi", "bezzaf", "chwiya", "3endi", "kayn",
    "ghadi", "ndir", "n7ess", "nkhalles", "tkhalles", "hna", "smiti",
}

#: Deux marqueurs minimum : « safi » ou « hna » peuvent apparaître par accident
#: (nom propre, mot étranger). Deux mots-outils de darija dans la même phrase,
#: c'est de la darija.
MIN_MARQUEURS_DARIJA = 2


def detecter_langue(texte: str) -> str:
    """
    Retourne 'ar', 'ar_latin' ou 'fr'.

    Ne lève jamais : une entrée vide ou illisible retombe sur 'fr', qui est la
    langue de travail du produit. Se tromper vers le français est le repli le
    moins coûteux — le corpus, les articles et l'interface y sont déjà.
    """
    if not texte or not texte.strip():
        return "fr"

    lettres = [c for c in texte if c.isalpha()]
    if lettres:
        ratio_arabe = sum(1 for c in lettres if _ARABE.match(c)) / len(lettres)
        if ratio_arabe >= SEUIL_ARABE:
            return "ar"

    mots = set(re.findall(r"[a-z0-9']+", texte.lower()))
    if len(mots & _MARQUEURS_DARIJA) >= MIN_MARQUEURS_DARIJA:
        return "ar_latin"

    return "fr"


def est_arabe(langue: str | None) -> bool:
    """La réponse doit-elle être rédigée en arabe (standard ou darija) ?"""
    return langue in ("ar", "ar_latin")
