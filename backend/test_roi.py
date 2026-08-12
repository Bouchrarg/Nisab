"""
test_roi.py — Chiffrage de la valeur générée (ROI cabinet).

Script manuel (pas pytest), même convention que test_cle_metier.py.
Lancer depuis backend/ :  python test_roi.py

## Ce qu'on vérifie

1. `exposition_findings` isole correctement chiffrables / non-chiffrables et
   ne compte JAMAIS un "non_calculable" comme 0 DH vérifié dans le total —
   même exigence que dashboard_summary et AuditPage.jsx.
2. `calculer_roi_dossier` sépare exposition détectée (toutes les alertes
   chiffrables) et exposition régularisée (seulement statut "traitee") — les
   deux ne doivent jamais être confondues, la régularisée est un
   SOUS-ENSEMBLE de la détectée.
3. Le temps estimé est TOUJOURS accompagné de son hypothèse — jamais un
   chiffre nu, cf. la règle "zéro affirmation sans source" du produit.
4. `agreger_roi_portefeuille` somme correctement plusieurs dossiers et gère
   le portefeuille vide sans lever.
"""
import sys

from app.odoo_connector import get_demo_data
from app.roi import (
    MINUTES_REVUE_PAR_PIECE,
    agreger_roi_portefeuille,
    calculer_roi_dossier,
    exposition_echeances,
    exposition_findings,
)
from app.tax_calendar import TAUX_MAJORATION_TVA_PLANCHER, get_calendar_events

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


def finding(amount, categorie="calculable", statut="ouverte"):
    return {"amount_risk": amount, "categorie_montant": categorie, "statut": statut}


print("\n-- 1. exposition_findings — non_calculable jamais compté comme 0 --")
findings = [
    finding(1500.0, "calculable"),
    finding(3000.0, "calculable_hypothese"),
    finding(None, "non_calculable"),  # amount_risk=0 côté API, mais À EXCLURE du total
]
expo = exposition_findings(findings)
check("2 findings chiffrables retenus", len(expo["chiffrables"]) == 2, str(len(expo["chiffrables"])))
check("1 finding non chiffrable exclu", expo["nb_non_chiffrables"] == 1)
check("total = 4500 (pas 4500+0, la distinction ne change rien ici mais la logique doit exclure, pas ajouter 0)",
      expo["total_dh"] == 4500.0, str(expo["total_dh"]))

print("\n-- 2. calculer_roi_dossier — détectée vs régularisée, jamais confondues --")
findings = [
    finding(1500.0, "calculable", statut="traitee"),   # régularisée
    finding(3000.0, "calculable", statut="ouverte"),    # détectée seulement
    finding(2000.0, "non_calculable", statut="ouverte"),  # hors tout total
]
r = calculer_roi_dossier(findings, nb_pieces=30)
check("exposition détectée = 4500 (1500+3000, exclut non_calculable)", r["exposition_detectee_dh"] == 4500.0, str(r["exposition_detectee_dh"]))
check("exposition régularisée = 1500 (seulement 'traitee')", r["exposition_regularisee_dh"] == 1500.0, str(r["exposition_regularisee_dh"]))
check("régularisée <= détectée (sous-ensemble, jamais l'inverse)", r["exposition_regularisee_dh"] <= r["exposition_detectee_dh"])
check("nb_non_chiffrables = 1", r["nb_non_chiffrables"] == 1)
check("temps estimé = 30 pièces * constante / 60", r["temps_estime_h"] == round(30 * MINUTES_REVUE_PAR_PIECE / 60, 1), str(r["temps_estime_h"]))
check("hypothèses toujours présentes (temps + échéances)", len(r["hypotheses"]) == 2 and r["hypotheses"][0]["valeur"] == MINUTES_REVUE_PAR_PIECE)

print("\n-- 3. agreger_roi_portefeuille --")
r1 = calculer_roi_dossier([finding(1000.0, statut="traitee")], nb_pieces=10)
r2 = calculer_roi_dossier([finding(2000.0)], nb_pieces=20)
agg = agreger_roi_portefeuille([r1, r2])
check("exposition détectée agrégée = 3000", agg["exposition_detectee_dh"] == 3000.0, str(agg["exposition_detectee_dh"]))
check("exposition régularisée agrégée = 1000", agg["exposition_regularisee_dh"] == 1000.0, str(agg["exposition_regularisee_dh"]))
check("nb_dossiers = 2", agg["nb_dossiers"] == 2)
check("temps agrégé = somme des deux", agg["temps_estime_h"] == round(r1["temps_estime_h"] + r2["temps_estime_h"], 1))

agg_vide = agreger_roi_portefeuille([])
check("portefeuille vide ne lève pas", agg_vide["nb_dossiers"] == 0)
check("portefeuille vide garde les 2 hypothèses (temps + échéances)", len(agg_vide["hypotheses"]) == 2)

print("\n-- 4. exposition_echeances — TVA seule chiffrable, le reste compté --")
events = [
    {"category": "TVA", "categorie_montant": "calculable_hypothese", "montant_base": 3000.0},
    {"category": "TVA", "categorie_montant": "non_calculable", "montant_base": None},
    {"category": "TVA", "categorie_montant": "calculable", "montant_base": 0.0},  # crédit de TVA
    {"category": "IS", "montant_base": None},  # pas de categorie_montant du tout (IS/IR/CNSS/TP)
]
expo = exposition_echeances(events)
check("4 échéances suivies au total", expo["nb_echeances_suivies"] == 4)
check("2 avec une base connue (calculable + calculable_hypothese)", expo["nb_avec_base_connue"] == 2, str(expo["nb_avec_base_connue"]))
check("total = 3000 (le crédit de TVA à 0 n'ajoute rien, IS ignoré)", expo["total_dh"] == 3000.0, str(expo["total_dh"]))

expo_vide = exposition_echeances([])
check("liste vide ne lève pas", expo_vide["total_dh"] == 0)

print("\n-- 5. calculer_roi_dossier avec events — jamais additionné à l'exposition détectée --")
r = calculer_roi_dossier([finding(1500.0, "calculable")], nb_pieces=10, events=events)
check("exposition_detectee_dh reste 1500 (findings seuls)", r["exposition_detectee_dh"] == 1500.0)
check("exposition_echeances_dh = 3000 (events seuls, jamais mélangé)", r["exposition_echeances_dh"] == 3000.0, str(r["exposition_echeances_dh"]))
check("nb_echeances_suivies = 4", r["nb_echeances_suivies"] == 4)
check("2 hypothèses (temps + échéances)", len(r["hypotheses"]) == 2)

r_sans_events = calculer_roi_dossier([finding(1500.0, "calculable")], nb_pieces=10)
check("sans events fourni, exposition_echeances_dh = 0 (pas de crash)", r_sans_events["exposition_echeances_dh"] == 0)

print("\n-- 6. Bout en bout sur les 3 scénarios de démo — montants TVA réels --")
NOM_MOIS = {2: "février", 3: "mars"}
ATTENDU = {
    # scénario: (mois couvert, categorie_montant attendue, montant_base attendu)
    "commerce": (2, "calculable_hypothese", round(20000.0 * TAUX_MAJORATION_TVA_PLANCHER, 2)),
    "conforme": (2, "calculable_hypothese", round((14166.67 + 9000.0) * TAUX_MAJORATION_TVA_PLANCHER, 2)),
    "services": (3, "calculable_hypothese", round((16000.0 - 3700.0) * TAUX_MAJORATION_TVA_PLANCHER, 2)),
}
for scenario, (mois, cat_attendue, montant_attendu) in ATTENDU.items():
    data = get_demo_data(scenario)
    events = get_calendar_events(odoo_data=data, nb_months_back=6)
    titre_attendu = f"TVA mensuelle — Déclaration {NOM_MOIS[mois]} 2026"
    evt = next((e for e in events if e["title"] == titre_attendu), None)
    check(f"{scenario} : échéance '{titre_attendu}' trouvée", evt is not None)
    if evt:
        check(f"{scenario} : categorie_montant == {cat_attendue}", evt["categorie_montant"] == cat_attendue, evt["categorie_montant"])
        check(f"{scenario} : montant_base == {montant_attendu}", evt["montant_base"] == montant_attendu, str(evt["montant_base"]))

print("\n" + ("TOUT EST VERT" if ok else "DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
