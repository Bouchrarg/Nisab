"""
regles_montant.py — Moteur de règles fiscales déterministe pour les montants
d'impact financier, séparé de l'interprétation sémantique faite par le LLM.

## Le problème que ce module règle

`ai_auditor.py` détecte une anomalie par RAG (retrieval + jugement LLM) et
laissait jusqu'ici le même appel LLM inventer `amount_risk` — un chiffre en DH
sans aucune vérification arithmétique, contrairement aux citations légales
(filtrées, cf. `_filtrer_references`) ou aux écritures de correction
(rééquilibrées par `correction_agent.valider_equilibre`). Un montant est une
affirmation comme une autre : il doit être **sourcé et vérifiable**, ou
explicitement marqué comme ne l'étant pas (règle d'architecture du projet :
"Zéro affirmation sans source").

## Le principe : séparer la sémantique du calcul

Le LLM reste seul juge de CE QUI cloche (interprétation d'un libellé, d'un
tiers, d'un contexte juridique — tâche pour laquelle il est bon). Il n'est
plus jamais seul juge de COMBIEN ça coûte (arithmétique — tâche pour laquelle
il est mauvais et invérifiable). Une fois qu'un article est identifié, CE
module calcule le montant à partir des données comptables, avec une formule
figée et testée.

## Les trois catégories (et pourquoi il en faut trois, pas deux)

Une seule dichotomie "chiffrable / pas chiffrable" ne suffit pas : beaucoup de
règles ont une formule légale exacte, mais butent sur une donnée qui n'existe
pas dans le pivot Odoo actuel (ex. le prix d'acquisition d'un véhicule n'est
nulle part un champ structuré). Ce n'est pas la loi qui est floue, c'est la
donnée qui manque — un cas différent d'une règle qui ne prévoit tout
simplement aucun montant chiffré.

- `calculable`        : formule légale exacte + toutes les données requises
                         sont présentes dans le pivot Odoo. Zéro hypothèse.
- `calculable_hypothese` : formule légale exacte, mais au moins une donnée
                         d'entrée est déduite (regex sur un libellé, valeur
                         saisie manuellement) plutôt que directement
                         disponible. Le résultat est affiché avec la mention
                         de l'hypothèse — jamais présenté comme un fait acquis.
- `non_calculable`     : soit la loi elle-même ne prévoit pas de sanction
                         chiffrée automatique (ex. Art. 146 : le rejet de
                         déduction suppose un jugement définitif qu'un audit
                         ne peut pas constater), soit une donnée déterminante
                         est un statut fiscal du tiers qu'aucune donnée
                         comptable ne porte (ex. Art. 151/194 : le tiers
                         relève-t-il d'un régime de retenue à la source ?).
                         Dans ce cas, AUCUN montant n'est produit, ni par ce
                         module ni par le LLM (cf. règle du prompt, ai_auditor).

## Ce que ce module NE fait PAS

Il ne détecte rien. Il ne décide pas quel article s'applique à quelle
écriture — ça reste le travail du RAG (`ai_auditor.py`), parce que juger la
pertinence d'un article à un contexte est exactement le genre de jugement
sémantique pour lequel un LLM a du sens et une fonction Python n'en a aucun.
Ce module prend en entrée un article déjà identifié et des données déjà
extraites, et répond une seule question : quel est le montant, s'il existe.

## Sources légales

Textes vérifiés dans le corpus CGI (édition 2025-2026, `corpus-pipeline/data/
corpus.db`, table `articles`) au moment d'écrire ce module.

Une vérification du 07/08/2026 a conclu à tort que les seuils de 5 000 DH et
50 000 DH/mois présents dans le code étaient inventés : ils appartiennent en
réalité à l'Art. 11-II, qui n'avait pas été consulté. Voir la note détaillée
en bas de fichier — c'est le meilleur exemple du piège que ce module est
censé fermer, cette fois-ci sur nous plutôt que sur le LLM : un chiffre juste
peut être déclaré faux si on le confronte au mauvais article.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CategorieMontant(str, Enum):
    calculable = "calculable"
    calculable_hypothese = "calculable_hypothese"
    non_calculable = "non_calculable"


def dh(montant: float, decimales: int = 2) -> str:
    """
    Formate un montant à la française : « 20 000,00 », pas « 20,000.00 ».

    Le format par défaut de Python (`{:,.2f}`) est anglo-saxon : virgule pour
    les milliers, point pour les décimales. C'est exactement l'inverse de la
    convention marocaine/française, où la virgule EST le séparateur décimal.
    Écrire « 20,000.00 DH » dans un `detail` destiné à être relu par un
    comptable, à côté d'un frontend qui affiche `toLocaleString('fr-MA')`,
    c'est inviter à lire vingt dirhams là où il y en a vingt mille.

    Le séparateur de milliers est une espace INSÉCABLE (U+00A0), écrite ici en
    échappement plutôt qu'en clair pour rester visible dans le source. C'est la
    convention typographique française, et c'est aussi ce que produit
    `toLocaleString('fr-MA')` côté frontend — les deux affichages coïncident donc
    au caractère près. Ne pas la remplacer par une espace ordinaire : un montant
    pourrait alors se couper en fin de ligne (« 20 » d'un côté, « 000 » de
    l'autre).
    """
    return f"{montant:,.{decimales}f}".replace(",", " ").replace(".", ",")


@dataclass
class ResultatMontant:
    """
    Sortie uniforme de toute règle. `detail` est la phrase qu'un contrôleur
    DGI ou un comptable doit pouvoir vérifier de tête — pas un résumé, le
    calcul lui-même en toutes lettres.
    """
    categorie: CategorieMontant
    montant: float | None
    detail: str
    hypothese: str | None = None


# ── Constantes légales — une seule source de vérité, jamais dupliquées ─────

#: CGI Art. 193 — seuil de règlement en espèces déclenchant l'amende.
#: Vérifié dans le corpus (texte 2025-2026) : "vingt mille (20.000) dirhams".
SEUIL_ESPECES_ART193 = 20_000.0
TAUX_AMENDE_ART193 = 0.06

#: CGI Art. 11-II — limites de déductibilité d'une charge réglée autrement que
#: par un moyen traçable. Vérifié dans le corpus (cgi_2026) : "Ne sont
#: déductibles du résultat fiscal que dans la limite de cinq mille (5.000)
#: dirhams par jour et par fournisseur sans dépasser cinquante mille (50.000)
#: dirhams par mois et par fournisseur".
#:
#: C'EST LA RÈGLE CÔTÉ ACHETEUR — celle qui s'applique à l'entreprise auditée
#: quand ELLE paie en espèces. À ne pas confondre avec l'Art. 193, qui vise
#: l'entreprise VENDERESSE (voir la docstring de paiement_especes_art193).
#: Les deux articles parlent de règlement en espèces, avec des seuils, des
#: sanctions et des redevables différents : les mélanger produit un chiffre
#: faux avec une citation qui a l'air juste.
PLAFOND_ESPECES_JOUR_ART11 = 5_000.0
PLAFOND_ESPECES_MOIS_ART11 = 50_000.0

#: CGI Art. 10-I-F-1°-b — plafond fiscalement déductible d'un véhicule de
#: tourisme, TVA comprise. Vérifié dans le corpus : "quatre cent mille
#: (400 000) dirhams par véhicule, taxe sur la valeur ajoutée comprise."
PLAFOND_VEHICULE_TOURISME_TTC = 400_000.0
TAUX_AMORT_VEHICULE_MIN = 0.20

#: CGI Art. 194 — majoration pour infraction déclarative Art. 151, par palier
#: de retard. Plancher vérifié dans le corpus : "ne peut être inférieur à
#: cinq cents (500) dirhams."
TAUX_MAJORATION_ART194 = {"moins_30j": 0.05, "plus_30j": 0.15, "defaut": 0.20}
PLANCHER_MAJORATION_ART194 = 500.0


# ── Règle 1 : paiement en espèces ≥ 20 000 DH (CGI Art. 193) ───────────────

def paiement_especes_art193(move: dict, lignes: list[dict]) -> ResultatMontant:
    """
    Amende de 6% pour règlement en espèces d'une transaction >= 20 000 DH.

    ## Qui paie cette amende — la question que ce module a d'abord ratée

    Le texte (corpus cgi_2026) est explicite sur le redevable : le règlement
    non traçable "donne lieu à l'application à l'encontre de **l'entreprise
    venderesse ou prestataire de services**, vérifiée, d'une amende de 6% du
    montant de la transaction". L'amende frappe le VENDEUR qui a accepté
    l'espèce, pas l'acheteur qui l'a versée.

    Conséquence directe : sur une facture d'ACHAT (`in_invoice`), l'entreprise
    auditée est l'acheteuse — cet article ne met rien à sa charge. Chiffrer
    ici une amende de 6% reviendrait à lui imputer la sanction d'un tiers,
    avec une citation qui a pourtant l'air correcte. C'est exactement le
    genre d'erreur qu'un montant "sourcé mais mal attribué" rend invisible.

    La règle qui s'applique à l'acheteur qui règle en espèces est l'Art. 11-II
    (limites de déductibilité), voir `repartir_deductible_especes_art11` —
    articles voisins, redevables opposés.

    Données Odoo requises : `move.move_type`, `move.amount_total` et le mode de
    règlement des lignes. Le texte de l'Art. 193 ne prévoit AUCUN cumul
    mensuel par fournisseur : le seuil s'apprécie transaction par transaction
    (le cumul de 50 000 DH/mois, lui, appartient à l'Art. 11-II — c'est la
    confusion d'origine entre les deux articles, cf. la note en fin de fichier).
    """
    # `entry` (OD) est laissé passer : une écriture diverse peut porter une
    # vente encaissée en espèces. Seul l'achat est exclu avec certitude.
    move_type = (move.get("move_type") or "").strip()
    if move_type in ("in_invoice", "in_refund"):
        return ResultatMontant(
            CategorieMontant.calculable, 0.0,
            "Facture d'achat : l'amende de 6% de l'Art. 193 CGI est due par l'entreprise "
            "venderesse, pas par l'acheteur. Aucune sanction à ce titre pour l'entreprise "
            "auditée sur cette écriture — la règle applicable à l'acheteur qui règle en "
            "espèces est l'Art. 11-II (limites de déductibilité).",
        )

    montant = float(move.get("amount_total") or 0)
    move_id = move.get("id")
    paye_especes = any(
        isinstance(l.get("move_id"), list) and l["move_id"][0] == move_id
        and (l.get("payment_mode") or "").strip().lower() in ("cash", "especes", "espèces", "espece")
        for l in lignes
    )
    if not paye_especes:
        return ResultatMontant(CategorieMontant.calculable, 0.0,
                                "Aucun règlement en espèces identifié sur cette pièce : Art. 193 non applicable.")
    if montant < SEUIL_ESPECES_ART193:
        return ResultatMontant(
            CategorieMontant.calculable, 0.0,
            f"Règlement en espèces de {dh(montant)} DH, sous le seuil de {dh(SEUIL_ESPECES_ART193, 0)} DH "
            "(Art. 193) : aucune amende.",
        )
    amende = round(montant * TAUX_AMENDE_ART193, 2)
    return ResultatMontant(
        CategorieMontant.calculable, amende,
        f"Amende Art. 193 CGI : {TAUX_AMENDE_ART193:.0%} x {dh(montant)} DH "
        f"(règlement espèces >= {dh(SEUIL_ESPECES_ART193, 0)} DH) = {dh(amende)} DH.",
    )


# ── Règle 1 bis : règlement en espèces côté ACHETEUR (CGI Art. 11-II) ──────

@dataclass
class ChargeEspeces:
    """Une charge réglée autrement que par un moyen traçable, pour UN fournisseur."""
    piece: str
    date_piece: str  # "AAAA-MM-JJ"
    montant_ht: float


def repartir_deductible_especes_art11(
    charges: list[ChargeEspeces],
    origine_signal: str = "mode de règlement des lignes comptables",
) -> dict[str, ResultatMontant]:
    """
    Réintégration des charges réglées en espèces au-delà des limites Art. 11-II.

    ## Pourquoi cette règle ne peut pas être « par écriture »

    Les quatre autres règles du module regardent une écriture isolée. Celle-ci
    ne le peut pas : le texte fixe une limite **par jour ET par fournisseur**,
    plafonnée **par mois et par fournisseur**. Deux factures du même
    fournisseur le même jour partagent une seule enveloppe de 5 000 DH ; la
    onzième journée d'espèces du mois peut tomber sous le plafond mensuel
    alors que, prise isolément, elle serait sous la limite journalière.
    Chiffrer écriture par écriture donnerait un total faux. D'où une fonction
    qui prend TOUTES les charges espèces d'un fournisseur et rend un résultat
    par pièce.

    ## La convention d'allocation, et pourquoi elle est neutre

    L'enveloppe déductible d'une journée est répartie entre les pièces de
    cette journée **au prorata de leur montant**. C'est une convention : le
    texte fixe un plafond global par jour, il ne dit pas quelle facture
    consomme l'enveloppe en premier. Le prorata est le seul partage qui ne
    privilégie aucune pièce, et surtout la SOMME des réintégrations est
    exacte quelle que soit la convention retenue — seule la ventilation par
    pièce en dépend. C'est ce total qui est opposable, la ventilation ne sert
    qu'à rattacher l'alerte à une écriture consultable.

    ## Toujours `calculable_hypothese`, jamais `calculable`

    Deux entrées reposent sur un jugement, pas sur un champ garanti : que le
    règlement soit bien non traçable (déduit d'un signal comptable, cf.
    `origine_signal`), et que les charges concernées relèvent des catégories
    visées par l'Art. 10 (I-A, B et E) auxquelles l'Art. 11-II renvoie. Le
    calcul, lui, est exact — d'où la catégorie intermédiaire prévue par ce
    module plutôt qu'un chiffre présenté comme un fait acquis.
    """
    resultats: dict[str, ResultatMontant] = {}

    par_mois: dict[str, list[ChargeEspeces]] = {}
    for c in charges:
        if c.montant_ht <= 0 or not c.date_piece:
            continue
        par_mois.setdefault(str(c.date_piece)[:7], []).append(c)

    for mois, charges_mois in par_mois.items():
        par_jour: dict[str, list[ChargeEspeces]] = {}
        for c in charges_mois:
            par_jour.setdefault(str(c.date_piece)[:10], []).append(c)

        enveloppe_mois_restante = PLAFOND_ESPECES_MOIS_ART11
        total_mois = round(sum(c.montant_ht for c in charges_mois), 2)

        # Ordre chronologique : le plafond mensuel se consomme dans l'ordre où
        # les règlements ont eu lieu, pas dans l'ordre d'arrivée des données.
        for jour in sorted(par_jour):
            lot = par_jour[jour]
            total_jour = round(sum(c.montant_ht for c in lot), 2)
            if total_jour <= 0:
                continue

            enveloppe_jour = min(PLAFOND_ESPECES_JOUR_ART11, total_jour, enveloppe_mois_restante)
            plafond_mois_atteint = enveloppe_jour < min(PLAFOND_ESPECES_JOUR_ART11, total_jour)
            enveloppe_mois_restante = round(enveloppe_mois_restante - enveloppe_jour, 2)

            for c in lot:
                part_deductible = round(enveloppe_jour * (c.montant_ht / total_jour), 2)
                reintegration = round(c.montant_ht - part_deductible, 2)
                if reintegration <= 0:
                    # Entièrement déductible : un vrai résultat (0 DH de
                    # risque), pas une absence de calcul.
                    resultats[c.piece] = ResultatMontant(
                        CategorieMontant.calculable, 0.0,
                        f"Règlement en espèces de {dh(c.montant_ht)} DH le {jour}, sous la limite "
                        f"de {dh(PLAFOND_ESPECES_JOUR_ART11, 0)} DH par jour et par fournisseur "
                        "(Art. 11-II CGI) : charge intégralement déductible.",
                    )
                    continue

                detail = (
                    f"Réintégration Art. 11-II CGI : {dh(total_jour)} DH de charges réglées en "
                    f"espèces auprès de ce fournisseur le {jour}, déductibles dans la limite de "
                    f"{dh(PLAFOND_ESPECES_JOUR_ART11, 0)} DH par jour et par fournisseur"
                )
                if len(lot) > 1:
                    detail += (
                        f" ; quote-part de cette pièce au prorata ({dh(c.montant_ht)} / "
                        f"{dh(total_jour)}) = {dh(part_deductible)} DH déductibles"
                    )
                if plafond_mois_atteint:
                    detail += (
                        f" ; plafond mensuel de {dh(PLAFOND_ESPECES_MOIS_ART11, 0)} DH par fournisseur "
                        f"atteint sur {mois} ({dh(total_mois)} DH réglés en espèces sur le mois), "
                        f"l'enveloppe du jour est ramenée à {dh(enveloppe_jour)} DH"
                    )
                detail += (
                    f". Réintégration = {dh(c.montant_ht)} - {dh(part_deductible)} "
                    f"= {dh(reintegration)} DH."
                )

                resultats[c.piece] = ResultatMontant(
                    CategorieMontant.calculable_hypothese, reintegration, detail,
                    hypothese=(
                        f"Suppose que le règlement n'est pas justifié par un moyen traçable au sens "
                        f"de l'Art. 11-II (chèque barré non endossable, effet de commerce, moyen "
                        f"magnétique, virement, procédé électronique ou compensation) — établi ici à "
                        f"partir de : {origine_signal} ; et que la charge relève bien des catégories "
                        f"visées à l'article 10 (I-A, B et E) auxquelles l'Art. 11-II renvoie."
                    ),
                )

    return resultats


# ── Règle 2 : amortissement véhicule de tourisme (CGI Art. 10-I-F-1°-b) ────

def amortissement_vehicule_tourisme_art10(
    prix_acquisition_ttc: float | None,
    dotation_annuelle: float | None,
) -> ResultatMontant:
    """
    Réintègre la part de dotation aux amortissements correspondant au
    dépassement du plafond de 400 000 DH TTC par véhicule.

    Donnée manquante aujourd'hui dans le pivot `AccountingConnector` : le prix
    d'acquisition TTC du véhicule n'est PAS un champ structuré (le connecteur
    ne remonte que la dotation comptabilisée sur la ligne d'amortissement).
    D'où `calculable_hypothese` dès que le prix vient d'ailleurs qu'un champ
    dédié — typiquement une extraction depuis le libellé de l'écriture.
    """
    if not prix_acquisition_ttc or not dotation_annuelle:
        return ResultatMontant(
            CategorieMontant.non_calculable, None,
            "Prix d'acquisition TTC du véhicule non disponible dans les données comptables : "
            f"impossible de vérifier le dépassement du plafond de {dh(PLAFOND_VEHICULE_TOURISME_TTC, 0)} DH.",
        )
    if prix_acquisition_ttc <= PLAFOND_VEHICULE_TOURISME_TTC:
        return ResultatMontant(
            CategorieMontant.calculable, 0.0,
            f"Prix d'acquisition {dh(prix_acquisition_ttc)} DH sous le plafond de "
            f"{dh(PLAFOND_VEHICULE_TOURISME_TTC, 0)} DH : aucune réintégration.",
        )
    part_excedentaire = (prix_acquisition_ttc - PLAFOND_VEHICULE_TOURISME_TTC) / prix_acquisition_ttc
    reintegration = round(dotation_annuelle * part_excedentaire, 2)
    return ResultatMontant(
        CategorieMontant.calculable_hypothese, reintegration,
        f"Réintégration Art. 10-I-F CGI : dotation {dh(dotation_annuelle)} DH x "
        f"(prix {dh(prix_acquisition_ttc)} - {dh(PLAFOND_VEHICULE_TOURISME_TTC, 0)}) / prix "
        f"= {dh(reintegration)} DH.",
        hypothese="Suppose que le prix d'acquisition TTC saisi est exact (extrait du libellé "
                   "comptable, pas d'un champ dédié) et que la dotation annuelle communiquée "
                   "correspond bien à ce véhicule.",
    )


#: Un nombre de 5 à 7 chiffres suivi ou précédé de DH/MAD, ou simplement un
#: nombre de 6 chiffres (prix de véhicule plausible : 100 000-9 999 999 DH).
#: Volontairement étroit : un seuil bas attraperait des années ("2026") ou
#: des taux ("20%"), donc plus de faux positifs que d'utilité.
_RE_PRIX_VEHICULE = re.compile(r"(\d{6,7})(?:[.,]\d+)?\s*(?:dh|dhs|mad)?", re.IGNORECASE)


def extraire_prix_vehicule(libelle: str) -> float | None:
    """
    Best-effort : cherche un prix de véhicule dans un libellé texte libre
    (ex. "Amort. véhicule tourisme 450000DH (taux 20%)"). PAS une lecture de
    champ structuré — le pivot Odoo n'en a pas (voir la note en fin de
    fichier). C'est précisément CE qui range le résultat de
    `amortissement_vehicule_tourisme_art10` dans `calculable_hypothese`
    plutôt que `calculable` : on extrait une donnée d'un texte, on ne la lit
    pas d'un champ garanti.
    """
    if not libelle:
        return None
    match = _RE_PRIX_VEHICULE.search(libelle)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


# ── Règle 3 : TVA non déductible sur catégorie exclue (CGI Art. 106-I) ─────

#: Les 4 catégories que l'Art. 106-I exclut EXPLICITEMENT du droit à
#: déduction. Volontairement fermée : une 5e catégorie qu'on croirait
#: reconnaître (ex. "frais de réception/restaurant") mais qui ne figure PAS
#: dans le texte vérifié ne doit jamais entrer ici par extension implicite —
#: c'est exactement le genre de rattachement bancal que ce module existe
#: pour empêcher.
CATEGORIES_EXCLUES_ART106 = {
    "vehicule_tourisme",        # 106-I-3° : véhicules de transport de personnes
    "immeuble_non_lie",         # 106-I-2° : immeubles/locaux non liés à l'exploitation
    "produit_petrolier_exclu",  # 106-I-4° : produits pétroliers hors liste dérogatoire
    "bien_non_exploitation",    # 106-I-1° : biens/services non utilisés pour l'exploitation
}


def tva_non_deductible_art106(montant_tva_ligne: float, categorie: str | None) -> ResultatMontant:
    """
    Réintègre la TVA déduite à tort sur une catégorie explicitement exclue du
    droit à déduction par l'Art. 106-I.

    `categorie` doit être une des 4 valeurs de `CATEGORIES_EXCLUES_ART106`,
    décidée EN AMONT par un détecteur déterministe (mapping mots-clés sur le
    libellé/compte comptable — voir `_categorie_art106` dans ai_auditor.py),
    JAMAIS par un jugement libre du LLM : une catégorisation fausse présentée
    comme un fait alimenterait directement un montant, exactement le risque
    que ce module existe pour éliminer. `None` = catégorie non détectée avec
    certitude -> `non_calculable`, PAS `calculable` à 0 : on ne sait pas,
    on ne dit pas "aucun risque".
    """
    if categorie is None:
        return ResultatMontant(
            CategorieMontant.non_calculable, None,
            "Catégorie de dépense exclue du droit à déduction (Art. 106-I) non détectée "
            "automatiquement avec certitude à partir du libellé comptable : vérification "
            "manuelle requise avant de conclure à une réintégration.",
        )
    if categorie not in CATEGORIES_EXCLUES_ART106:
        return ResultatMontant(CategorieMontant.calculable, 0.0,
                                "Catégorie non exclue du droit à déduction (Art. 106-I) : aucune réintégration.")
    montant = round(float(montant_tva_ligne or 0), 2)
    return ResultatMontant(
        CategorieMontant.calculable, montant,
        f"TVA non déductible Art. 106-I CGI : {dh(montant)} DH (montant intégral de la TVA "
        f"comptabilisée sur la ligne, catégorie « {categorie} »).",
    )


#: Détection par mots-clés, volontairement restreinte aux catégories qu'on
#: peut reconnaître sans ambiguïté dans un libellé français standard. Les
#: catégories "immeuble_non_lie" et "bien_non_exploitation" ne sont PAS
#: détectées ici — trop dépendantes du contexte pour un mot-clé seul, elles
#: resteront `non_calculable` (vérification manuelle) tant qu'aucun détecteur
#: fiable n'existe pour elles.
_MOTS_VEHICULE_TOURISME = ("véhicule de tourisme", "vehicule de tourisme", "véhicule tourisme",
                            "vehicule tourisme", "voiture de tourisme", "voiture tourisme",
                            "véhicule de transport de personnes")
_MOTS_PRODUIT_PETROLIER = ("carburant", "essence", "gasoil", "diesel")


def categorie_art106(libelle: str) -> str | None:
    """
    Détecteur déterministe (mots-clés, pas de LLM) pour les 2 catégories
    Art. 106-I qu'on peut reconnaître sans ambiguïté dans un libellé
    comptable français standard. Retourne None si aucun mot-clé ne matche —
    ce n'est pas une preuve d'absence, juste "pas détecté ici".
    """
    texte = (libelle or "").strip().lower()
    if not texte:
        return None
    if any(mot in texte for mot in _MOTS_VEHICULE_TOURISME):
        return "vehicule_tourisme"
    if any(mot in texte for mot in _MOTS_PRODUIT_PETROLIER):
        return "produit_petrolier_exclu"
    return None


# ── Règle 4 : facture sans mentions obligatoires (CGI Art. 145-III / 146) ──

def facture_mentions_obligatoires_art146() -> ResultatMontant:
    """
    Non calculable PAR CONSTRUCTION, pas par manque de données.

    L'Art. 146 ne chiffre un rejet de déduction que si l'administration a
    établi, par un jugement ayant acquis la force de la chose jugée, que le
    fournisseur est "défaillant" au sens de la procédure de l'Art. 231 — une
    condition qu'un audit automatisé ne peut jamais constater à partir des
    seules données comptables ("pas d'ICE renseigné" n'est PAS équivalent à
    "fournisseur défaillant par jugement définitif", même si c'est souvent le
    signe avant-coureur). Retourner un montant ici serait fabriquer une
    pénalité que le texte ne prévoit pas dans ce contexte.
    """
    return ResultatMontant(
        CategorieMontant.non_calculable, None,
        "L'Art. 146 CGI ne chiffre un rejet de déduction qu'après constat, par jugement "
        "définitif, du caractère défaillant du fournisseur (procédure Art. 231) — une "
        "condition que l'audit ne peut pas établir lui-même. Risque qualitatif uniquement, "
        "sans montant.",
    )


# ── Règle 5 : rémunérations à des tiers non déclarées (Art. 151 / 194) ─────

def remuneration_tiers_non_declaree_art151(
    retenue_source_applicable: bool | None,
    montant_retenue_due: float | None,
    jours_retard: int | None,
) -> ResultatMontant:
    """
    Majoration Art. 194 pour infraction à l'obligation déclarative Art. 151.

    La majoration ne s'applique QUE si la rémunération relevait d'un régime de
    retenue à la source (Art. 15 bis / 45 bis) — ce n'est pas systématique
    pour un simple honoraire de consultant. Ce statut est une caractéristique
    fiscale du bénéficiaire, PAS une donnée comptable : rien dans le pivot
    Odoo ne le porte. Par défaut, `non_calculable` tant que ce statut n'est
    pas confirmé explicitement (saisie manuelle du comptable).
    """
    if retenue_source_applicable is None:
        return ResultatMontant(
            CategorieMontant.non_calculable, None,
            "Statut du bénéficiaire au regard de la retenue à la source (Art. 15 bis / 45 bis) "
            "inconnu : impossible de dire si la majoration Art. 194 s'applique. Vérification "
            "manuelle requise avant tout chiffrage — l'obligation Art. 151 elle-même reste "
            "signalée, sans montant.",
        )
    if not retenue_source_applicable or not montant_retenue_due:
        return ResultatMontant(CategorieMontant.calculable, 0.0,
                                "Rémunération hors régime de retenue à la source : aucune majoration Art. 194.")
    palier = "defaut" if jours_retard is None else ("moins_30j" if jours_retard <= 30 else "plus_30j")
    taux = TAUX_MAJORATION_ART194[palier]
    majoration = max(round(montant_retenue_due * taux, 2), PLANCHER_MAJORATION_ART194)
    return ResultatMontant(
        CategorieMontant.calculable_hypothese, majoration,
        f"Majoration Art. 194 CGI : {taux:.0%} x {dh(montant_retenue_due)} DH "
        f"(plancher {dh(PLANCHER_MAJORATION_ART194, 0)} DH) = {dh(majoration)} DH.",
        hypothese="Suppose que la retenue à la source était effectivement due sur cette "
                   "rémunération — hypothèse confirmée manuellement, pas déduite des données Odoo.",
    )


# ── Registre : quels articles ont une règle de calcul déterministe ─────────

#: Les fonctions ci-dessus n'ont PAS la même signature (chacune a besoin de
#: données Odoo différentes, et l'Art. 11-II travaille même sur un LOT
#: d'écritures et pas sur une seule) : il n'y a donc pas de dispatch générique
#: possible ici. Ce registre sert uniquement à répondre "cet article a-t-il
#: une règle ?" — le dispatch réel, avec l'extraction des bons arguments
#: depuis `move`/`lignes`, vit dans `ai_auditor.calculer_montant_regle()`
#: (le seul endroit qui a déjà `move` et `lignes` sous la main au moment où
#: `reference_cgi` est connu). Garder les deux synchronisés : toute référence
#: ajoutée ici doit avoir sa branche de dispatch dans ai_auditor.py, et
#: inversement.
REFERENCES_AVEC_REGLE = frozenset({
    "article 193",
    "article 11",
    "article 10",
    "article 106",
    "article 146",
    "article 151",
})

#: Sous-ensemble AUTO-DÉCLENCHABLE : les articles dont les conditions
#: d'application se lisent entièrement dans les données comptables, sans
#: jugement sémantique. Ce sont les seuls que `detection_reglee.py` a le droit
#: de détecter lui-même, sans attendre que le RAG les retienne.
#:
#: Les trois autres n'y sont PAS, et pour des raisons différentes :
#:   - Art. 146 : `non_calculable` par construction (jugement définitif requis),
#:     il ne produirait jamais de montant, donc rien à auto-détecter ;
#:   - Art. 151 : dépend d'un statut fiscal du tiers qu'aucune donnée
#:     comptable ne porte, et qui doit être confirmé par le comptable ;
#:   - Art. 193 : la condition est objective, mais le redevable est
#:     l'entreprise VENDERESSE — or l'audit ne parcourt que les achats et les
#:     OD (ai_auditor), donc l'auto-déclencher reviendrait à imputer à
#:     l'entreprise auditée l'amende d'un tiers.
REFERENCES_AUTO_DETECTABLES = frozenset({
    "article 11",
    "article 10",
    "article 106",
})


# ── ÉCARTS CORRIGÉS AILLEURS LORS DU BRANCHEMENT (07/08/2026) ───────────────
#
# 1. RECTIFIÉ LE 09/08/2026 — la note d'origine disait ceci :
#
#      « Les cas "espèces" de _demo_commerce / _demo_services étaient
#        construits sur un seuil de 5 000-8 500 DH et un commentaire
#        "cumul > 50000/mois". Le seuil réel vérifié est 20 000 DH PAR
#        TRANSACTION, sans cumul mensuel dans le texte actuel — les montants
#        de démo ont été relevés en conséquence. »
#
#    C'était une erreur, et elle vaut d'être gardée écrite parce qu'elle est
#    instructive. Les seuils de 5 000 DH et de 50 000 DH/mois ne sortaient de
#    nulle part : ce sont EXACTEMENT les deux limites de l'Art. 11-II
#    (déductibilité chez l'acheteur). Ils ont été confrontés au texte de
#    l'Art. 193 (amende chez le vendeur), jugés introuvables — ce qui est
#    vrai, ils n'y sont pas — et « corrigés » vers 20 000 DH. Une règle juste
#    a donc été remplacée par une règle fausse, en toute rigueur apparente,
#    parce que la vérification portait sur le mauvais article.
#
#    La leçon, à dire telle quelle : vérifier un CHIFFRE contre le corpus ne
#    sert à rien tant qu'on n'a pas vérifié à quel ARTICLE il appartient, ni
#    QUI en est le redevable. Les deux articles parlent de règlement en
#    espèces avec des seuils voisins ; l'un sanctionne le vendeur, l'autre
#    limite la déduction chez l'acheteur.
#
#    Les montants de démo relevés à 20 000+ DH n'ont PAS été remis à leur
#    valeur d'origine : ils dépassent largement la limite de 5 000 DH/jour de
#    l'Art. 11-II, donc ils continuent de démontrer la règle — plus
#    franchement, même.
#
# 2. Le commentaire du move IMMO-2026-001 disait "> 300 000 DH" — le plafond
#    réel vérifié est 400 000 DH. Le véhicule de démo (450 000 DH) dépasse
#    toujours ce plafond, donc l'anomalie déclenche encore, avec un montant
#    de réintégration différent (et plus petit) que ce qu'un LLM aurait
#    estimé sur la base de l'ancien seuil.