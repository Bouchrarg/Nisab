"""
Vérifie que l'import CSV produit exactement le schéma pivot attendu par le
moteur d'audit — sans appeler le LLM.

Le vrai enjeu de la Phase 5 n'est pas « on sait lire un CSV », c'est « le moteur
d'audit ne sait pas qu'il ne parle plus à Odoo ». On le prouve en passant les
données importées dans les fonctions internes d'ai_auditor.py, non modifiées.

Lancer depuis backend/ :  python test_import_fichier.py
"""
import sys

from app.ai_auditor import _build_search_query, _build_transaction_summary, _resolve_partner
from app.connectors.fichier_connecteur import MODELE_CSV, FichierAccountingConnector
from app.routes_dossiers import _fusionner_donnees_comptables
from app.tax_calendar import get_calendar_events

ok = True


def check(label, condition, detail=""):
    global ok
    print(("  OK   " if condition else "  ECHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        ok = False


CSV_MULTI = """date;piece;journal;compte;libelle;debit;credit;tiers_nom;tiers_ice;mode_reglement
14/03/2026;FACT-2026-002;ACH;6142;Frais de mission;1 200,00;0;Transport Atlas SARL;;especes
14/03/2026;FACT-2026-002;ACH;34551;TVA recuperable;240,00;0;Transport Atlas SARL;;especes
14/03/2026;FACT-2026-002;ACH;4411;Fournisseur;0;1 440,00;Transport Atlas SARL;;especes
02/04/2026;VTE-2026-010;VTE;3421;Client;6 000,00;0;Client Beta SA;001234567000045;virement
02/04/2026;VTE-2026-010;VTE;7111;Ventes;0;5 000,00;Client Beta SA;001234567000045;virement
02/04/2026;VTE-2026-010;VTE;4455;TVA facturee;0;1 000,00;Client Beta SA;001234567000045;virement
ligne de total sans date;;;;;;;;;
"""

print("\n-- 1. Modèle CSV fourni à l'utilisateur -------------------------")
data = FichierAccountingConnector(MODELE_CSV.encode(), "modele.csv").fetch_accounting_data()
check("modèle lisible", len(data["moves"]) == 1, f"{len(data['moves'])} écriture(s)")
check("3 lignes regroupées en 1 pièce", len(data["lines"]) == 3)
check("montant_ttc repris de la colonne", data["moves"][0]["amount_total"] == 1440.0, str(data["moves"][0]["amount_total"]))

print("\n-- 2. Fichier réaliste (sép. ';', virgule décimale, ligne parasite) --")
conn = FichierAccountingConnector(CSV_MULTI.encode(), "export_sage.csv")
data = conn.fetch_accounting_data()
moves = {m["name"]: m for m in data["moves"]}

check("2 écritures reconstituées", len(moves) == 2, ", ".join(moves))
check("ligne parasite ignorée, pas d'échec", conn.nb_lignes_ignorees == 1, f"{conn.nb_lignes_ignorees} ignorée(s)")
check("un warning explicite est remonté", any("Ligne" in w for w in conn.warnings), conn.warnings[0] if conn.warnings else "aucun")
check("date FR convertie en ISO", moves["FACT-2026-002"]["date"] == "2026-03-14", moves["FACT-2026-002"]["date"])
check("montant '1 200,00' lu correctement", data["lines"][0]["debit"] == 1200.0, str(data["lines"][0]["debit"]))
check("achat détecté via compte 4411", moves["FACT-2026-002"]["move_type"] == "in_invoice", moves["FACT-2026-002"]["move_type"])
check("vente détectée via compte 3421", moves["VTE-2026-010"]["move_type"] == "out_invoice", moves["VTE-2026-010"]["move_type"])
check("total déduit de la partie double", moves["FACT-2026-002"]["amount_total"] == 1440.0, str(moves["FACT-2026-002"]["amount_total"]))
check("aucun déséquilibre signalé", not any("déséquilibrée" in w for w in conn.warnings))

ice = {p["name"]: p["vat"] for p in data["partners"]}
check("ICE manquant = False (pas '')", ice["Transport Atlas SARL"] is False, repr(ice["Transport Atlas SARL"]))
check("ICE présent conservé", ice["Client Beta SA"] == "001234567000045")

print("\n-- 3. Déterminisme des identifiants (ré-import) -----------------")
data2 = FichierAccountingConnector(CSV_MULTI.encode(), "export_sage.csv").fetch_accounting_data()
ids1 = sorted(m["id"] for m in data["moves"])
ids2 = sorted(m["id"] for m in data2["moves"])
check("move ids identiques après ré-import", ids1 == ids2, f"{ids1} vs {ids2}")
melange = "\n".join([CSV_MULTI.splitlines()[0]] + list(reversed(CSV_MULTI.splitlines()[1:])))
data3 = FichierAccountingConnector(melange.encode(), "export_sage.csv").fetch_accounting_data()
check("ids indépendants de l'ordre des lignes", sorted(m["id"] for m in data3["moves"]) == ids1)
check("ids dans les bornes d'un INTEGER Postgres", all(0 < m["id"] < 2**31 for m in data["moves"]))

print("\n-- 4. Le moteur d'audit consomme les données sans modification --")
partner_map = {p["id"]: p for p in data["partners"]}
move = moves["FACT-2026-002"]
partner = _resolve_partner(move, partner_map)
check("tiers résolu par ai_auditor", partner is not None and partner["name"] == "Transport Atlas SARL")

resume = _build_transaction_summary(move, data["lines"], partner)
check("n° de pièce dans le résumé", "FACT-2026-002" in resume)
check("3 lignes détaillées dans le résumé", resume.count("- Ligne:") == 3, str(resume.count("- Ligne:")))
check("ICE manquant signalé au LLM", "NON RENSEIGNÉ / MANQUANT" in resume)
check("mode de règlement transmis", "Mode: especes" in resume)
check("montant TTC formaté", "1,440.00 DH" in resume, [l for l in resume.splitlines() if "TTC" in l])
check("requête RAG non vide", len(_build_search_query(move, resume, partner)) > 40)

print("\n-- 5. Le calendrier fiscal accepte la même structure ------------")
events = get_calendar_events(odoo_data=data, nb_months_back=6)
check("calendrier calculé sur données importées", len(events) > 0, f"{len(events)} échéances")

print("\n-- 6. Fusion plutôt qu'écrasement (routes_dossiers) -------------")
CSV_JANVIER = """date;piece;journal;compte;libelle;debit;credit;tiers_nom;tiers_ice;mode_reglement
14/01/2026;FACT-2026-002;ACH;6142;Frais de mission;1 200,00;0;Transport Atlas SARL;;especes
14/01/2026;FACT-2026-002;ACH;34551;TVA recuperable;240,00;0;Transport Atlas SARL;;especes
14/01/2026;FACT-2026-002;ACH;4411;Fournisseur;0;1 440,00;Transport Atlas SARL;;especes
"""
CSV_FEVRIER = """date;piece;journal;compte;libelle;debit;credit;tiers_nom;tiers_ice;mode_reglement
02/02/2026;VTE-2026-010;VTE;3421;Client;6 000,00;0;Client Beta SA;001234567000045;virement
02/02/2026;VTE-2026-010;VTE;7111;Ventes;0;5 000,00;Client Beta SA;001234567000045;virement
02/02/2026;VTE-2026-010;VTE;4455;TVA facturee;0;1 000,00;Client Beta SA;001234567000045;virement
"""
# Même n° de pièce que janvier, montant corrigé -- doit REMPLACER, pas s'ajouter.
CSV_CORRECTION = """date;piece;journal;compte;libelle;debit;credit;tiers_nom;tiers_ice;mode_reglement
14/01/2026;FACT-2026-002;ACH;6142;Frais de mission;2 000,00;0;Transport Atlas SARL;;especes
14/01/2026;FACT-2026-002;ACH;34551;TVA recuperable;400,00;0;Transport Atlas SARL;;especes
14/01/2026;FACT-2026-002;ACH;4411;Fournisseur;0;2 400,00;Transport Atlas SARL;;especes
"""

janvier = FichierAccountingConnector(CSV_JANVIER.encode(), "janvier.csv").fetch_accounting_data()
fevrier = FichierAccountingConnector(CSV_FEVRIER.encode(), "fevrier.csv").fetch_accounting_data()
correction = FichierAccountingConnector(CSV_CORRECTION.encode(), "correction.csv").fetch_accounting_data()

apres_fevrier = _fusionner_donnees_comptables(janvier, fevrier)
check("janvier + février = 2 écritures distinctes", len(apres_fevrier["moves"]) == 2,
      [m["name"] for m in apres_fevrier["moves"]])
check("janvier + février = 6 lignes (3+3, aucune perdue)", len(apres_fevrier["lines"]) == 6,
      str(len(apres_fevrier["lines"])))
check("les deux tiers sont présents", {p["name"] for p in apres_fevrier["partners"]}
      == {"Transport Atlas SARL", "Client Beta SA"})

apres_correction = _fusionner_donnees_comptables(apres_fevrier, correction)
check("réimporter FACT-2026-002 ne duplique pas l'écriture", len(apres_correction["moves"]) == 2,
      [m["name"] for m in apres_correction["moves"]])
move_corrige = next(m for m in apres_correction["moves"] if m["name"] == "FACT-2026-002")
check("le montant corrigé remplace l'ancien", move_corrige["amount_total"] == 2400.0,
      str(move_corrige["amount_total"]))
lignes_fact = [l for l in apres_correction["lines"] if l["move_id"][1] == "FACT-2026-002"]
check("3 lignes pour la pièce corrigée, pas 6 (pas d'accumulation)", len(lignes_fact) == 3,
      str(len(lignes_fact)))
check("VTE-2026-010 intacte après la correction de janvier",
      any(m["name"] == "VTE-2026-010" for m in apres_correction["moves"]))
check("snapshot vide + nouveau fichier = pas de plantage", _fusionner_donnees_comptables(None, janvier) == janvier)

print("\n" + ("=> TOUT PASSE" if ok else "=> DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
