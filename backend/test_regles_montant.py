"""
Vérifie les 5 règles de `app.regles_montant` sur des cas connus.

Script manuel (pas pytest, même convention que test_cle_metier.py) : aucune
DB requise, ce sont des fonctions pures. Cas tirés soit des scénarios de démo
d'`odoo_connector.py` (avec les seuils corrigés — voir la note en bas de
regles_montant.py), soit construits pour couvrir chaque catégorie.
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from app.regles_montant import (
    CategorieMontant,
    ChargeEspeces,
    amortissement_vehicule_tourisme_art10,
    repartir_deductible_especes_art11,
    categorie_art106,
    extraire_prix_vehicule,
    facture_mentions_obligatoires_art146,
    paiement_especes_art193,
    remuneration_tiers_non_declaree_art151,
    tva_non_deductible_art106,
)

ok = True


def check(label, condition, detail=""):
    global ok
    print(("  OK   " if condition else "  ECHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        ok = False


# ── Règle 1 : Art. 193, paiement en espèces ─────────────────────────────────
print("\n== Règle 1 — Art. 193 (paiement espèces) ==")

# QUI est redevable : le texte met l'amende "à l'encontre de l'entreprise
# venderesse ou prestataire de services". Sur une VENTE encaissée en espèces,
# l'entreprise auditée est la venderesse -> amende due.
move_vente = {"id": 106, "amount_total": 47000.0, "move_type": "out_invoice"}
lignes_vente = [{"move_id": [106, "VENTE-X"], "payment_mode": "cash"}]
r = paiement_especes_art193(move_vente, lignes_vente)
check("vente 47 000 DH encaissée en espèces -> calculable", r.categorie == CategorieMontant.calculable)
check("vente 47 000 DH espèces -> amende = 6% x 47000 = 2820 DH", r.montant == 2820.0, r.montant)

# Le même montant sur un ACHAT ne doit produire AUCUNE amende : l'entreprise
# auditée est alors l'acheteuse, et l'Art. 193 ne la vise pas. C'est le cas
# réel de FACT-2026-004 (_demo_commerce), qui est un `in_invoice` — la règle
# applicable à l'acheteur est l'Art. 11-II, testée plus bas.
move_achat = {"id": 106, "amount_total": 47000.0, "move_type": "in_invoice"}
lignes_achat = [{"move_id": [106, "FACT-2026-004"], "payment_mode": "cash"}]
r = paiement_especes_art193(move_achat, lignes_achat)
check("achat 47 000 DH espèces -> aucune amende Art. 193 (redevable = le vendeur)",
      r.categorie == CategorieMontant.calculable and r.montant == 0.0, r.montant)
check("achat espèces -> le detail explique que le redevable est l'entreprise venderesse",
      "venderesse" in r.detail)

# Règlement par virement : jamais d'amende, quel que soit le montant.
move_virement = {"id": 999, "amount_total": 90000.0, "move_type": "out_invoice"}
lignes_virement = [{"move_id": [999, "X"], "payment_mode": "virement"}]
r = paiement_especes_art193(move_virement, lignes_virement)
check("90 000 DH par virement -> aucune amende", r.montant == 0.0, r.montant)

# Sous le seuil : la loi dit "égal ou supérieur à 20 000 DH".
move_8500 = {"id": 102, "amount_total": 8500.0, "move_type": "out_invoice"}
lignes_8500 = [{"move_id": [102, "X"], "payment_mode": "cash"}]
r = paiement_especes_art193(move_8500, lignes_8500)
check("8 500 DH espèces -> calculable, montant nul (sous le seuil de 20 000 DH)",
      r.categorie == CategorieMontant.calculable and r.montant == 0.0, r.montant)

# Exactement au seuil : la loi dit "égal ou supérieur" -> amende due.
move_pile = {"id": 1, "amount_total": 20000.0, "move_type": "out_invoice"}
lignes_pile = [{"move_id": [1, "X"], "payment_mode": "espèces"}]
r = paiement_especes_art193(move_pile, lignes_pile)
check("20 000 DH pile espèces -> amende due (seuil inclusif)", r.montant == 1200.0, r.montant)


# ── Règle 1 bis : Art. 11-II, règlement espèces côté ACHETEUR ───────────────
print("\n== Règle 1 bis — Art. 11-II (déductibilité, côté acheteur) ==")

# Cas démo FACT-2026-002 : 20 000 DH HT réglés en espèces un seul jour.
r = repartir_deductible_especes_art11([
    ChargeEspeces(piece="FACT-2026-002", date_piece="2026-01-20", montant_ht=20000.0),
])
check("20 000 DH espèces en un jour -> réintégration = 20 000 - 5 000 = 15 000 DH",
      r["FACT-2026-002"].montant == 15000.0, r["FACT-2026-002"].montant)
check("Art. 11-II -> calculable_hypothese (mode de règlement + nature de charge déduits)",
      r["FACT-2026-002"].categorie == CategorieMontant.calculable_hypothese)

# Sous la limite journalière : intégralement déductible, donc un vrai 0 DH.
r = repartir_deductible_especes_art11([
    ChargeEspeces(piece="P1", date_piece="2026-02-03", montant_ht=3000.0),
])
check("3 000 DH espèces -> sous la limite, aucune réintégration",
      r["P1"].categorie == CategorieMontant.calculable and r["P1"].montant == 0.0)

# Deux pièces le MÊME jour chez le MÊME fournisseur : une seule enveloppe de
# 5 000 DH à partager, au prorata. Le total est ce qui compte.
r = repartir_deductible_especes_art11([
    ChargeEspeces(piece="A", date_piece="2026-03-10", montant_ht=6000.0),
    ChargeEspeces(piece="B", date_piece="2026-03-10", montant_ht=2000.0),
])
total_jour = round(r["A"].montant + r["B"].montant, 2)
check("2 pièces le même jour (6 000 + 2 000) -> réintégration totale = 8 000 - 5 000 = 3 000 DH",
      total_jour == 3000.0, total_jour)
check("prorata : la pièce de 6 000 DH absorbe les 3/4 de l'enveloppe",
      r["A"].montant == 2250.0 and r["B"].montant == 750.0, (r["A"].montant, r["B"].montant))

# Deux fournisseurs le même jour = deux enveloppes distinctes. La fonction ne
# reçoit qu'UN fournisseur à la fois : c'est le regroupement en amont
# (detection_reglee) qui garantit ça, testé ici par construction.
r_f1 = repartir_deductible_especes_art11([ChargeEspeces("F1", "2026-03-10", 6000.0)])
r_f2 = repartir_deductible_especes_art11([ChargeEspeces("F2", "2026-03-10", 6000.0)])
check("chaque fournisseur a sa propre enveloppe journalière de 5 000 DH",
      r_f1["F1"].montant == 1000.0 and r_f2["F2"].montant == 1000.0)

# PLAFOND MENSUEL — le cas que les scénarios de démo n'atteignent jamais.
# 12 journées à 8 000 DH chez le même fournisseur : la limite journalière
# accorderait 12 x 5 000 = 60 000 DH, mais le plafond mensuel la ramène à
# 50 000 DH. Total réglé 96 000 -> réintégration 46 000 DH.
charges_mois = [
    ChargeEspeces(piece=f"M{j}", date_piece=f"2026-04-{j:02d}", montant_ht=8000.0)
    for j in range(1, 13)
]
r = repartir_deductible_especes_art11(charges_mois)
total_reintegre = round(sum(x.montant for x in r.values()), 2)
check("12 jours x 8 000 DH -> plafond mensuel 50 000 DH -> réintégration = 96 000 - 50 000 = 46 000 DH",
      total_reintegre == 46000.0, total_reintegre)
check("plafond mensuel atteint -> le detail le dit explicitement",
      any("plafond mensuel" in x.detail for x in r.values()))
# Les deux derniers jours du mois ne reçoivent plus rien : l'enveloppe
# mensuelle est épuisée, ils sont réintégrés en totalité.
check("une fois le plafond mensuel épuisé, la journée est réintégrée en entier",
      r["M12"].montant == 8000.0, r["M12"].montant)

# Deux mois distincts = deux plafonds mensuels distincts.
r = repartir_deductible_especes_art11([
    ChargeEspeces("X1", "2026-05-31", 8000.0),
    ChargeEspeces("X2", "2026-06-01", 8000.0),
])
check("le plafond mensuel se remet à zéro au changement de mois",
      r["X1"].montant == 3000.0 and r["X2"].montant == 3000.0)


# ── Règle 2 : Art. 10, amortissement véhicule de tourisme ──────────────────
print("\n== Règle 2 — Art. 10-I-F (véhicule de tourisme) ==")

# Cas démo IMMO-2026-001 : véhicule 450 000 DH, dotation annuelle 90 000 DH
# (taux 20%). Plafond réel 400 000 DH (pas 300 000 DH comme dans le commentaire
# du code démo).
r = amortissement_vehicule_tourisme_art10(prix_acquisition_ttc=450000.0, dotation_annuelle=90000.0)
attendu = round(90000.0 * (450000.0 - 400000.0) / 450000.0, 2)  # = 10 000.0
check("véhicule 450 000 DH -> calculable_hypothese", r.categorie == CategorieMontant.calculable_hypothese)
check(f"véhicule 450 000 DH -> réintégration = {attendu} DH", r.montant == attendu, r.montant)
check("véhicule 450 000 DH -> hypothèse documentée", bool(r.hypothese))

# Véhicule sous le plafond : aucune réintégration.
r = amortissement_vehicule_tourisme_art10(prix_acquisition_ttc=250000.0, dotation_annuelle=50000.0)
check("véhicule 250 000 DH -> calculable, montant nul", r.categorie == CategorieMontant.calculable and r.montant == 0.0)

# Donnée manquante (prix non extrait du libellé) : non calculable, pas 0 ni erreur.
r = amortissement_vehicule_tourisme_art10(prix_acquisition_ttc=None, dotation_annuelle=90000.0)
check("prix véhicule inconnu -> non_calculable", r.categorie == CategorieMontant.non_calculable and r.montant is None)


# ── Règle 3 : Art. 106, TVA non déductible ──────────────────────────────────
print("\n== Règle 3 — Art. 106-I (TVA non déductible) ==")

r = tva_non_deductible_art106(montant_tva_ligne=1000.0, categorie="vehicule_tourisme")
check("TVA sur catégorie exclue -> réintégration = montant intégral", r.montant == 1000.0, r.montant)
check("TVA sur catégorie exclue -> calculable (zéro hypothèse)", r.categorie == CategorieMontant.calculable)

r = tva_non_deductible_art106(montant_tva_ligne=533.33, categorie=None)
check("catégorie non détectée -> non_calculable, PAS un 0 silencieux",
      r.categorie == CategorieMontant.non_calculable and r.montant is None, r.montant)

r = tva_non_deductible_art106(montant_tva_ligne=200.0, categorie="autre_chose_non_reconnue")
check("catégorie explicitement hors liste -> calculable, aucune réintégration",
      r.categorie == CategorieMontant.calculable and r.montant == 0.0)

# Détecteur de catégorie par mots-clés (déterministe, pas de LLM)
check("libellé 'Repas d'affaires clients' -> catégorie non reconnue (Art. 106 ne liste pas la restauration)",
      categorie_art106("Repas d'affaires clients mars 2026") is None)
check("libellé 'Amort. véhicule tourisme 450000DH' -> catégorie vehicule_tourisme",
      categorie_art106("Amort. véhicule tourisme 450000DH (taux 20%)") == "vehicule_tourisme")
check("libellé 'Achat gasoil poids lourd' -> catégorie produit_petrolier_exclu",
      categorie_art106("Achat gasoil poids lourd") == "produit_petrolier_exclu")
check("libellé vide -> None", categorie_art106("") is None)

# Extraction du prix véhicule depuis un libellé texte (heuristique, cf. calculable_hypothese)
check("extraction prix depuis libellé démo -> 450000.0",
      extraire_prix_vehicule("Amort. véhicule tourisme 450000DH (taux 20%)") == 450000.0)
check("libellé sans nombre plausible -> None", extraire_prix_vehicule("Amortissement véhicule") is None)
check("libellé vide -> None", extraire_prix_vehicule("") is None)


# ── Règle 4 : Art. 146, mentions obligatoires ───────────────────────────────
print("\n== Règle 4 — Art. 146 (mentions obligatoires facture) ==")

r = facture_mentions_obligatoires_art146()
check("Art. 146 -> toujours non_calculable, quel que soit le contexte",
      r.categorie == CategorieMontant.non_calculable and r.montant is None)
check("Art. 146 -> le detail explique POURQUOI (jugement définitif requis)",
      "jugement" in r.detail.lower())


# ── Règle 5 : Art. 151/194, rémunérations à des tiers ───────────────────────
print("\n== Règle 5 — Art. 151 / 194 (rémunérations non déclarées) ==")

# Cas démo FACT-2026-201 (consultant) : statut de retenue à la source inconnu
# du pivot Odoo -> non calculable par défaut, PAS une estimation optimiste.
r = remuneration_tiers_non_declaree_art151(retenue_source_applicable=None, montant_retenue_due=None, jours_retard=None)
check("statut retenue à la source inconnu -> non_calculable", r.categorie == CategorieMontant.non_calculable and r.montant is None)

# Hypothèse confirmée manuellement : retard <= 30j -> majoration 5%, plancher 500 DH.
r = remuneration_tiers_non_declaree_art151(retenue_source_applicable=True, montant_retenue_due=1900.0, jours_retard=10)
check("retenue due 1900 DH, retard 10j -> majoration 5% = 95 DH -> plancher 500 DH appliqué",
      r.montant == 500.0, r.montant)
check("retenue due -> calculable_hypothese (jamais calculable pur)",
      r.categorie == CategorieMontant.calculable_hypothese)

# Retard > 30j sur un montant plus élevé : le plancher ne joue plus.
r = remuneration_tiers_non_declaree_art151(retenue_source_applicable=True, montant_retenue_due=20000.0, jours_retard=45)
check("retenue due 20 000 DH, retard 45j -> majoration 15% = 3000 DH", r.montant == 3000.0, r.montant)

# Confirmé hors régime de retenue à la source : pas de majoration.
r = remuneration_tiers_non_declaree_art151(retenue_source_applicable=False, montant_retenue_due=None, jours_retard=None)
check("hors régime retenue à la source -> aucune majoration",
      r.categorie == CategorieMontant.calculable and r.montant == 0.0)


print("\n" + ("TOUS LES TESTS PASSENT" if ok else "DES TESTS ONT ÉCHOUÉ"))
sys.exit(0 if ok else 1)