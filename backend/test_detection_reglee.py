"""
Vérifie la détection déterministe (`app.detection_reglee`) sur les trois
scénarios de démonstration d'`odoo_connector.py`.

Script manuel (pas pytest, même convention que test_regles_montant.py). Aucune
base requise : le corpus est simulé par un vérificateur de références injecté,
ce qui permet de tester la logique de détection sans Postgres — mais aussi de
vérifier le comportement quand un article est ABSENT du corpus, cas qu'on ne
pourrait pas provoquer contre la vraie base.

Deux scénarios comptent autant l'un que l'autre :
  - `commerce` doit produire les montants attendus ;
  - `conforme` doit produire ZÉRO alerte. C'est le seul moyen de vérifier
    qu'on n'a pas gagné des montants en fabriquant des faux positifs.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath("."))

from app.detection_reglee import detecter, est_regle_en_especes, _lignes_du_move
from app.odoo_connector import _demo_commerce, _demo_conforme, _demo_services
from app.regles_montant import dh

ok = True


def check(label, condition, detail=""):
    global ok
    print(("  OK   " if condition else "  ECHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        ok = False


def corpus_complet(references):
    """Simule un corpus qui contient tous les articles demandés."""
    return set(references)


def corpus_vide(references):
    """Simule un corpus où aucun article n'est retrouvable."""
    return set()


def par_piece(findings):
    return {f["invoice"]: f for f in findings}


# ── Scénario commerce ───────────────────────────────────────────────────────
print("\n== Scénario `commerce` ==")

findings = detecter(_demo_commerce(), verifier_references=corpus_complet)
trouves = par_piece(findings)

check(f"3 anomalies chiffrées détectées (obtenu : {len(findings)})", len(findings) == 3,
      ", ".join(f"{f['invoice']}/{f['reference_cgi']}" for f in findings))

# Art. 11-II — Al Baraka, deux règlements espèces en janvier, jours distincts.
# 20/01 : 20 000 HT -> 5 000 déductibles -> 15 000 réintégrés.
# 28/01 : 39 166,67 HT -> 5 000 déductibles -> 34 166,67 réintégrés.
f2 = trouves.get("FACT-2026-002")
check("FACT-2026-002 rattachée à l'Article 11", f2 is not None and f2["reference_cgi"] == "Article 11")
check("FACT-2026-002 -> réintégration = 20 000 - 5 000 = 15 000 DH",
      f2 is not None and f2["amount_risk"] == 15000.0, f2 and f2["amount_risk"])

f4 = trouves.get("FACT-2026-004")
check("FACT-2026-004 rattachée à l'Article 11", f4 is not None and f4["reference_cgi"] == "Article 11")
check("FACT-2026-004 -> réintégration = 39 166,67 - 5 000 = 34 166,67 DH",
      f4 is not None and f4["amount_risk"] == 34166.67, f4 and f4["amount_risk"])

check("Art. 11 -> calculable_hypothese (mode de règlement déduit, charges présumées art. 10 I-A/B/E)",
      f2 is not None and f2["categorie_montant"] == "calculable_hypothese")
check("Art. 11 -> l'hypothèse nomme le signal utilisé",
      f2 is not None and "mode de règlement" in (f2["montant_hypothese"] or ""))
check("Art. 11 -> le detail contient le calcul en toutes lettres",
      f2 is not None and dh(5000, 0) in f2["montant_detail"] and f"{dh(15000)} DH" in f2["montant_detail"],
      f2 and f2["montant_detail"])
# Régression : le format anglo-saxon ("15,000.00") a été affiché pendant un
# temps dans ce champ, qui est précisément celui qu'un comptable doit pouvoir
# relire. Une virgule de séparateur de milliers ne doit jamais y réapparaître.
check("Art. 11 -> montant formaté à la française, pas « 15,000.00 »",
      f2 is not None and "15,000" not in f2["montant_detail"] and " " in f2["montant_detail"])

# Art. 10 — véhicule 450 000 DH, dotation 90 000 DH, plafond 400 000 DH.
fi = trouves.get("IMMO-2026-001")
check("IMMO-2026-001 rattachée à l'Article 10", fi is not None and fi["reference_cgi"] == "Article 10")
check("IMMO-2026-001 -> réintégration = 90 000 x (450 000 - 400 000) / 450 000 = 10 000 DH",
      fi is not None and fi["amount_risk"] == 10000.0, fi and fi["amount_risk"])

total = round(sum(f["amount_risk"] for f in findings), 2)
check("Exposition chiffrable totale = 59 166,67 DH", total == 59166.67, total)

# Le repas d'affaires ne doit PAS produire d'alerte Art. 106 : la restauration
# ne figure pas dans les 4 catégories exclues du droit à déduction, et le nom
# du fournisseur ("Carburants Sud") ne doit jamais servir à catégoriser.
check("FACT-2026-005 (repas d'affaires chez « Carburants Sud ») -> aucune alerte Art. 106",
      "FACT-2026-005" not in trouves)

# Facture d'achat normale, réglée par un moyen traçable.
check("FACT-2026-001 (achat classique) -> aucune alerte", "FACT-2026-001" not in trouves)

# Toutes les alertes doivent citer un article, sinon _reecrire_citations
# ne créerait aucune CitationRisque.
check("toutes les alertes portent une citation dans rag_sources",
      all(f["rag_sources"] and f["reference_cgi"] in f["rag_sources"] for f in findings))


# ── Corpus indisponible ─────────────────────────────────────────────────────
print("\n== Garde-fou : article absent du corpus ==")

check("aucun article citable -> AUCUNE alerte émise (pas d'affirmation sans source)",
      detecter(_demo_commerce(), verifier_references=corpus_vide) == [])


# ── Scénario conforme ───────────────────────────────────────────────────────
print("\n== Scénario `conforme` (aucun faux positif attendu) ==")

findings_conformes = detecter(_demo_conforme(), verifier_references=corpus_complet)
check("0 anomalie sur un dossier conforme", len(findings_conformes) == 0,
      ", ".join(f"{f['invoice']}/{f['reference_cgi']}" for f in findings_conformes))


# ── Scénario services ───────────────────────────────────────────────────────
print("\n== Scénario `services` ==")

findings_services = detecter(_demo_services(), verifier_references=corpus_complet)
trouves_s = par_piece(findings_services)

# FACT-2026-204 : prestation nettoyage 18 500 HT réglée en espèces le 15/03.
fs = trouves_s.get("FACT-2026-204")
check("FACT-2026-204 (espèces 18 500 HT) -> Article 11",
      fs is not None and fs["reference_cgi"] == "Article 11")
check("FACT-2026-204 -> réintégration = 18 500 - 5 000 = 13 500 DH",
      fs is not None and fs["amount_risk"] == 13500.0, fs and fs["amount_risk"])
check("les honoraires réglés par virement ne déclenchent rien",
      "FACT-2026-201" not in trouves_s and "FACT-2026-203" not in trouves_s)


# ── Signal « réglé en espèces » ─────────────────────────────────────────────
print("\n== Signal de règlement en espèces ==")

data = _demo_commerce()
moves = {m["name"]: m for m in data["moves"]}

m2 = moves["FACT-2026-002"]
especes, origine = est_regle_en_especes(m2, _lignes_du_move(m2, data["lines"]))
check("payment_mode='cash' -> détecté", especes is True)
check("l'origine du signal est explicitée", "mode de règlement" in origine, origine)

m1 = moves["FACT-2026-001"]
especes, _ = est_regle_en_especes(m1, _lignes_du_move(m1, data["lines"]))
check("facture sans mode de règlement espèces -> non détecté", especes is False)

# Signal Odoo réel : le journal de caisse, puisque payment_mode n'existe pas
# dans account.move.line.
faux_move = {"id": 999, "journal_id": [7, "Caisse MAD"], "journal_type": "cash"}
especes, origine = est_regle_en_especes(faux_move, [])
check("journal_type='cash' (Odoo réel) -> détecté", especes is True)
check("l'origine cite le journal", "journal" in origine, origine)

# Signal de repli : contrepartie sur un compte de caisse du plan CGNC.
faux_move2 = {"id": 998, "journal_id": [1, "Achats"]}
lignes_caisse = [{"move_id": [998, "X"], "account_id": [42, "516100 Caisse centrale"], "credit": 30000.0}]
especes, origine = est_regle_en_especes(faux_move2, lignes_caisse)
check("contrepartie sur compte 516x (CGNC) -> détecté", especes is True)
check("l'origine cite le compte", "compte de caisse" in origine, origine)

# Un compte qui n'est pas de la caisse ne doit jamais déclencher.
lignes_banque = [{"move_id": [997, "X"], "account_id": [43, "514100 Banques"], "credit": 30000.0}]
especes, _ = est_regle_en_especes({"id": 997, "journal_id": [1, "Achats"]}, lignes_banque)
check("contrepartie bancaire (514x) -> non détecté", especes is False)


print("\n" + ("TOUS LES TESTS PASSENT" if ok else "DES TESTS ONT ÉCHOUÉ"))
sys.exit(0 if ok else 1)
