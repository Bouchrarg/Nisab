"""
roi.py — Chiffrage de la valeur générée par Nisab pour un cabinet.

Module de calcul pur, sans FastAPI ni accès base — même séparation que
tax_calendar.py / regles_montant.py. Les routes (`GET /dossiers/{id}/roi`,
`GET /roi/portefeuille`) vivent dans routes_roi.py.

## Ce qui est MESURÉ et ce qui est ESTIMÉ, jamais confondu ni additionné

- **Exposition détectée avant contrôle (DH)** — MESURÉ. Somme de
  `amount_risk` sur les alertes réellement chiffrables (`categorie_montant
  != "non_calculable"`) : c'est le même total que celui déjà affiché par
  `GET /dashboard/summary` sous "exposition fiscale chiffrable", donc soumis
  à la même prudence — cf. regles_montant.py : "non_calculable" veut dire
  qu'une règle a tourné et n'a explicitement rien pu chiffrer, pas "0 DH
  vérifié". Le compter comme 0 sous-estimerait silencieusement l'exposition.
- **Exposition régularisée (DH)** — MESURÉ. Même somme, restreinte aux
  alertes dont `statut == "traitee"` (décision humaine du collaborateur,
  jamais écrasée par un ré-audit — voir _appliquer_finding).
- **Temps d'analyse épargné (h)** — ESTIMÉ, jamais affiché sans son
  hypothèse. Un ROI qui cache l'hypothèse derrière un chiffre est exactement
  le genre d'affirmation non sourcée que le reste du produit s'interdit (cf.
  règle d'architecture "zéro affirmation sans source" du projet).
- **Exposition échéances suivies (DH)** — MESURÉ, mais partiel PAR NATURE.
  Vient de `tax_calendar._montant_tva_periode` : seule la TVA a une base
  chiffrable depuis le pivot comptable (TVA facturée - TVA déductible), les
  autres échéances (IS, IR, CNSS, Taxe Professionnelle) resteraient du
  COMPTAGE pur sans ce chiffre — leur base (résultat théorique de l'exercice
  précédent, masse salariale, valeur locative) n'est pas dans les données
  dont Nisab dispose. Jamais additionné à `exposition_detectee_dh` : l'un
  vient d'anomalies déjà commises, l'autre d'échéances encore À VENIR — les
  confondre ferait passer un risque futur pour un risque déjà réalisé.

## Pourquoi pas de courbe dans le temps

Aucun snapshot des audits passés n'existe : un ré-audit MET À JOUR les
alertes existantes (réconciliation par clé métier), il n'en garde pas
d'historique versionné. Ce module chiffre donc un ÉTAT COURANT, pas une
évolution. Une table d'historique serait un chantier séparé.
"""

from __future__ import annotations

from app.tax_calendar import TAUX_MAJORATION_TVA_PLANCHER

#: Minutes de revue manuelle qu'un collaborateur consacrerait à UNE pièce en
#: l'absence de Nisab (identifier la règle applicable, vérifier le seuil,
#: rédiger la note) — hypothèse déclarée, pas mesurée sur ce produit (aucune
#: instrumentation du temps de revue n'existe). Choisie délibérément basse :
#: une hypothèse optimiste serait la première chose contestée à l'oral, une
#: hypothèse prudente résiste mieux à la question "et si c'est surestimé ?".
MINUTES_REVUE_PAR_PIECE = 4


def exposition_findings(findings: list[dict]) -> dict:
    """
    Sépare les findings chiffrables des non-chiffrables et somme les premiers.

    Isolé pour être partagé avec `routes_dossiers.dashboard_summary`, qui
    calcule exactement ceci pour son propre total affiché — dupliquer cette
    logique aurait fini par diverger silencieusement des deux côtés.
    """
    chiffrables = [f for f in findings if f.get("categorie_montant") != "non_calculable"]
    return {
        "chiffrables": chiffrables,
        "nb_non_chiffrables": len(findings) - len(chiffrables),
        "total_dh": sum(f.get("amount_risk", 0) or 0 for f in chiffrables),
    }


def exposition_echeances(events: list[dict]) -> dict:
    """
    Sépare les échéances du calendrier (`tax_calendar.get_calendar_events`)
    dont le montant est chiffrable de celles qui restent du comptage pur.

    Un événement sans `categorie_montant` (tous les types hors TVA
    aujourd'hui — IS, IR, CNSS, Taxes Locales, cf. tax_calendar.py) est traité
    comme "non_calculable" : `.get()` plutôt qu'un accès direct, pour ne pas
    supposer que le champ existe sur des événements qui ne le posent pas.
    """
    chiffrables = [
        e for e in events if e.get("categorie_montant") in ("calculable", "calculable_hypothese")
    ]
    return {
        "nb_echeances_suivies": len(events),
        "nb_avec_base_connue": len(chiffrables),
        "total_dh": sum(e.get("montant_base", 0) or 0 for e in chiffrables),
    }


def calculer_roi_dossier(findings: list[dict], nb_pieces: int, events: list[dict] | None = None) -> dict:
    """
    ROI d'UN dossier à partir de ses findings actifs (`_lire_audit_persiste`),
    du nombre de pièces comptables du dossier (`nb_moves`) et, optionnellement,
    de ses échéances à venir (`tax_calendar.get_calendar_events`) pour la
    partie exposition_echeances_dh — absente (0, hypothèse silencieuse) si
    `events` n'est pas fourni, plutôt que de forcer chaque appelant à calculer
    un calendrier qu'il n'a pas forcément sous la main.
    """
    expo = exposition_findings(findings)
    regularisees_dh = sum(
        f.get("amount_risk", 0) or 0 for f in expo["chiffrables"] if f.get("statut") == "traitee"
    )
    temps_h = round(nb_pieces * MINUTES_REVUE_PAR_PIECE / 60, 1)
    expo_ech = exposition_echeances(events or [])

    return {
        "exposition_detectee_dh": round(expo["total_dh"], 2),
        "exposition_regularisee_dh": round(regularisees_dh, 2),
        "nb_anomalies_chiffrables": len(expo["chiffrables"]),
        "nb_non_chiffrables": expo["nb_non_chiffrables"],
        "temps_estime_h": temps_h,
        "exposition_echeances_dh": round(expo_ech["total_dh"], 2),
        "nb_echeances_suivies": expo_ech["nb_echeances_suivies"],
        "nb_echeances_base_connue": expo_ech["nb_avec_base_connue"],
        "hypotheses": [
            {
                "libelle": "Temps de revue manuelle par pièce (sans Nisab)",
                "valeur": MINUTES_REVUE_PAR_PIECE,
                "unite": "min",
            },
            {
                "libelle": "Exposition échéances TVA : plancher de majoration (Art. 208 CGI), hors 5%/mois de retard",
                "valeur": int(TAUX_MAJORATION_TVA_PLANCHER * 100),
                "unite": "%",
            },
        ],
    }


def agreger_roi_portefeuille(rois: list[dict]) -> dict:
    """
    Somme des ROI par dossier (`calculer_roi_dossier`) pour la vue cabinet.
    Les hypothèses ne se somment pas — une seule ligne, valable pour tous les
    dossiers agrégés (c'est la même constante partout, pas une par dossier).
    """
    if not rois:
        return {
            "exposition_detectee_dh": 0, "exposition_regularisee_dh": 0,
            "nb_anomalies_chiffrables": 0, "nb_non_chiffrables": 0,
            "temps_estime_h": 0, "nb_dossiers": 0,
            "exposition_echeances_dh": 0, "nb_echeances_suivies": 0, "nb_echeances_base_connue": 0,
            "hypotheses": [
                {"libelle": "Temps de revue manuelle par pièce (sans Nisab)",
                 "valeur": MINUTES_REVUE_PAR_PIECE, "unite": "min"},
                {"libelle": "Exposition échéances TVA : plancher de majoration (Art. 208 CGI), hors 5%/mois de retard",
                 "valeur": int(TAUX_MAJORATION_TVA_PLANCHER * 100), "unite": "%"},
            ],
        }
    return {
        "exposition_detectee_dh": round(sum(r["exposition_detectee_dh"] for r in rois), 2),
        "exposition_regularisee_dh": round(sum(r["exposition_regularisee_dh"] for r in rois), 2),
        "nb_anomalies_chiffrables": sum(r["nb_anomalies_chiffrables"] for r in rois),
        "nb_non_chiffrables": sum(r["nb_non_chiffrables"] for r in rois),
        "temps_estime_h": round(sum(r["temps_estime_h"] for r in rois), 1),
        "exposition_echeances_dh": round(sum(r["exposition_echeances_dh"] for r in rois), 2),
        "nb_echeances_suivies": sum(r["nb_echeances_suivies"] for r in rois),
        "nb_echeances_base_connue": sum(r["nb_echeances_base_connue"] for r in rois),
        "nb_dossiers": len(rois),
        "hypotheses": rois[0]["hypotheses"],
    }
