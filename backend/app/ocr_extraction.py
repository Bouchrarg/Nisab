"""
ocr_extraction.py — Extraction de champs sur une facture scannée (image).

## Pourquoi ce n'est PAS un AccountingConnector

`connectors/base.py` documente le schéma pivot : un `move` a besoin de
`lines` en partie double (compte, débit, crédit) pour être audité par
`ai_auditor`. `fichier_connecteur.py` peut construire ça parce qu'un export
CSV/Excel CONTIENT déjà ces comptes.

Une image de facture ne les contient pas. Elle donne du texte : une date, un
montant TTC, un ICE, un numéro de pièce — jamais quel compte du plan CGNC
mouvementer. Inventer "TTC 10 200 DH → 611x débit / 4411 crédit" à partir
d'un OCR serait une affirmation fabriquée, pas une extraction — exactement ce
que la règle "zéro affirmation sans source" interdit côté citations légales.
La même discipline s'applique ici : ce module extrait des champs à VÉRIFIER
par un humain, il ne produit jamais de `PieceComptable` ni n'alimente
`ai_auditor`. C'est documenté dans les règles d'architecture du projet
(rapprochement pièce-par-pièce = hors scope) ; ce module est le "petit peu"
qui reste honnête vis-à-vis de cette limite plutôt que de la contourner en
silence.

## Limite connue et assumée

`lang="fr"` uniquement. Une facture rédigée en arabe (fréquent au Maroc) ne
sera pas lue correctement — le cahier des charges scope l'arabe à
l'assistant conversationnel, pas à l'OCR. À rouvrir si besoin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EXTENSIONS_ACCEPTEES = (".jpg", ".jpeg", ".png")

AVERTISSEMENT_NON_VERIFIE = (
    "Extraction automatique non vérifiée par un humain. Aucune écriture "
    "comptable n'est générée à partir de ces champs — à confirmer avant "
    "toute saisie manuelle."
)

#: ICE marocain : exactement 15 chiffres (Identifiant Commun de l'Entreprise).
_RE_ICE = re.compile(r"\b\d{15}\b")

#: JJ/MM/AAAA, JJ-MM-AAAA, JJ.MM.AAAA — les séparateurs varient selon le
#: modèle de facture, le format n'est jamais fiable à 100%.
_RE_DATE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")

#: Numéro de pièce : "FACT-2026-045", "N° 2026/045", "Facture no 118"...
_RE_NUMERO_PIECE = re.compile(
    r"(?:FACT(?:URE)?[\s.:°N-]*|N[°o][\s.:]*)([A-Z0-9][A-Z0-9/\-]{2,20})",
    re.IGNORECASE,
)

#: Une ligne de montant total : "Total TTC", "Net à payer", "Montant TTC".
_RE_LIGNE_TOTAL = re.compile(r"(?:total\s*ttc|net\s*[àa]\s*payer|montant\s*ttc)", re.IGNORECASE)

#: Un nombre décimal avec séparateur milliers espace/point et décimal virgule/point.
_RE_NOMBRE = re.compile(r"\d[\d\s.,]*\d|\d")


class OcrError(Exception):
    """Image illisible ou moteur OCR indisponible — traduit en 4xx côté route."""


@dataclass
class LigneReconnue:
    texte: str
    confiance: float


@dataclass
class ChampsExtraits:
    date: str | None = None
    montant_ttc: float | None = None
    ice: str | None = None
    numero_piece: str | None = None


@dataclass
class ResultatOcr:
    champs: ChampsExtraits
    texte_brut: list[LigneReconnue] = field(default_factory=list)
    confiance_moyenne: float = 0.0
    avertissement: str = AVERTISSEMENT_NON_VERIFIE

    def to_dict(self) -> dict:
        return {
            "champs": {
                "date": self.champs.date,
                "montant_ttc": self.champs.montant_ttc,
                "ice": self.champs.ice,
                "numero_piece": self.champs.numero_piece,
            },
            "texte_brut": [{"texte": l.texte, "confiance": round(l.confiance, 3)} for l in self.texte_brut],
            "confiance_moyenne": round(self.confiance_moyenne, 3),
            "avertissement": self.avertissement,
        }


# ── moteur OCR (singleton, chargement coûteux) ──────────────────────────────

_moteur = None


def _moteur_ocr():
    """
    Charge PaddleOCR une seule fois par process — l'initialisation lit les
    modèles depuis le disque (et les télécharge au tout premier appel), un
    coût qu'on ne veut pas payer à chaque requête.
    """
    global _moteur
    if _moteur is None:
        try:
            from paddleocr import PaddleOCR  # import local : voir docstring du module
        except ImportError as exc:
            raise OcrError(
                "paddleocr n'est pas installé. Voir requirements.txt (section OCR)."
            ) from exc
        _moteur = PaddleOCR(
            lang="fr",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
    return _moteur


def _lignes_reconnues(contenu: bytes) -> list[LigneReconnue]:
    import numpy as np
    from PIL import Image
    import io

    try:
        image = Image.open(io.BytesIO(contenu)).convert("RGB")
    except Exception as exc:
        raise OcrError(f"Image illisible : {exc}") from exc

    resultat = _moteur_ocr().predict(np.array(image))
    if not resultat:
        return []

    page = resultat[0]
    textes = page.get("rec_texts", []) if hasattr(page, "get") else getattr(page, "rec_texts", [])
    scores = page.get("rec_scores", []) if hasattr(page, "get") else getattr(page, "rec_scores", [])
    return [LigneReconnue(texte=t, confiance=float(s)) for t, s in zip(textes, scores)]


# ── extraction de champs (regex, tolérant) ──────────────────────────────────


def _nombre(texte: str) -> float | None:
    """Tolère « 10 200,00 », « 10.200,00 », « 10200.00 »."""
    t = texte.strip().replace(" ", "").replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _extraire_date(lignes: list[str]) -> str | None:
    for ligne in lignes:
        m = _RE_DATE.search(ligne)
        if not m:
            continue
        jour, mois, annee = m.groups()
        if len(annee) == 2:
            annee = "20" + annee
        try:
            return f"{int(annee):04d}-{int(mois):02d}-{int(jour):02d}"
        except ValueError:
            continue
    return None


def _extraire_ice(lignes: list[str]) -> str | None:
    for ligne in lignes:
        m = _RE_ICE.search(ligne.replace(" ", ""))
        if m:
            return m.group(0)
    return None


def _extraire_numero_piece(lignes: list[str]) -> str | None:
    for ligne in lignes:
        m = _RE_NUMERO_PIECE.search(ligne)
        if m:
            return m.group(1).strip("-/")
    return None


def _extraire_montant_ttc(lignes: list[str]) -> float | None:
    """
    Cherche d'abord une ligne contenant "Total TTC" / "Net à payer" : le
    nombre qui s'y trouve (ou, sinon, sur la ligne suivante — l'OCR sépare
    souvent le libellé du montant en deux lignes) est pris en priorité sur
    n'importe quel autre nombre du document.
    """
    for i, ligne in enumerate(lignes):
        if not _RE_LIGNE_TOTAL.search(ligne):
            continue
        candidats = _RE_NOMBRE.findall(ligne)
        if not candidats and i + 1 < len(lignes):
            candidats = _RE_NOMBRE.findall(lignes[i + 1])
        for c in candidats:
            valeur = _nombre(c)
            if valeur:
                return valeur
    return None


def extraire_champs_facture(contenu: bytes, nom_fichier: str) -> ResultatOcr:
    """
    Point d'entrée du module : image → champs à vérifier.

    Ne lève ConnectorError-like que sur une image illisible ou un moteur OCR
    absent (OcrError) ; une facture sans aucun champ détecté n'est pas une
    erreur, `champs` revient simplement rempli de `None` — c'est à l'humain
    de compléter, pas à Nisab de deviner.
    """
    nom = (nom_fichier or "").lower()
    if not nom.endswith(EXTENSIONS_ACCEPTEES):
        raise OcrError(
            f"Format non pris en charge pour l'OCR. Extensions acceptées : "
            f"{', '.join(EXTENSIONS_ACCEPTEES)}."
        )

    lignes_reconnues = _lignes_reconnues(contenu)
    if not lignes_reconnues:
        raise OcrError("Aucun texte détecté dans l'image.")

    textes = [l.texte for l in lignes_reconnues]
    champs = ChampsExtraits(
        date=_extraire_date(textes),
        montant_ttc=_extraire_montant_ttc(textes),
        ice=_extraire_ice(textes),
        numero_piece=_extraire_numero_piece(textes),
    )
    confiance_moyenne = (
        sum(l.confiance for l in lignes_reconnues) / len(lignes_reconnues)
        if lignes_reconnues else 0.0
    )
    return ResultatOcr(champs=champs, texte_brut=lignes_reconnues, confiance_moyenne=confiance_moyenne)
