"""
Test reel de create_draft_move contre une instance Odoo.

ECRIT DANS ODOO : cree une ecriture en brouillon clairement libellee comme un
test, verifie qu'elle est bien en state='draft' et NON postee, puis la supprime.
Ne laisse aucun residu. Ne tourne que si des identifiants sont fournis.

    ODOO_DB=Nisab_demo ODOO_USER=... ODOO_PASSWORD=... python test_push_odoo.py

ou

    python test_push_odoo.py --db Nisab_demo --user ... --password ...

Ce qui est reellement verifie, et qu'aucun test hors-ligne ne peut couvrir :

  1. la societe cible est deduite des ECRITURES, pas de la session Odoo.
     Sur une base multi-societes la session pointe souvent sur la societe par
     defaut, qui n'a aucune comptabilite ; ecrire la-bas avec les comptes d'une
     autre societe fait echouer Odoo avec un message peu lisible.

  2. les codes CGNC a 4 chiffres (6142) se resolvent sur un plan a 6 chiffres
     (614210). Le CGI et le LLM raisonnent en 4 chiffres, le plan livre par
     Odoo est complete : sans resolution par prefixe, aucune correction ne
     pourrait etre poussee.

  3. un code trop court ou inexistant est REFUSE, pas devine.

  4. l'ecriture creee est un brouillon. Nisab ne valide aucune ecriture
     comptable, jamais (regle produit du projet).
"""
import argparse
import os
import sys

from app.odoo_connector import OdooConnector, OdooWriteError

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


parser = argparse.ArgumentParser(description="Test d'ecriture reelle dans Odoo (cree puis supprime un brouillon).")
parser.add_argument("--url", default=os.environ.get("ODOO_URL", "http://localhost:8069"))
parser.add_argument("--db", default=os.environ.get("ODOO_DB"))
parser.add_argument("--user", default=os.environ.get("ODOO_USER"))
parser.add_argument("--password", default=os.environ.get("ODOO_PASSWORD"))
args = parser.parse_args()

if not (args.db and args.user and args.password):
    print("Identifiants Odoo absents — test ignore.")
    print("Fournissez --db / --user / --password, ou ODOO_DB / ODOO_USER / ODOO_PASSWORD.")
    sys.exit(0)

c = OdooConnector(url=args.url, db=args.db, username=args.user, password=args.password)
c.authenticate()

print("\n-- 1. Detection de la societe cible -----------------------------")
societe = c.detect_company_id()
c.company_id = societe
noms = {s["id"]: s["name"] for s in c._execute("res.company", "search_read", [], fields=["id", "name"])}
utilisateur = c._execute("res.users", "read", [c.uid], fields=["company_id"])[0]
check("societe deduite des ecritures", societe is not None, f"id {societe} = {noms.get(societe)}")
if societe != utilisateur["company_id"][0]:
    print(f"  [i]    session Odoo = {utilisateur['company_id'][1]}, cible = {noms.get(societe)}")
    print("  [i]    Le contexte force evite d'ecrire dans la mauvaise societe.")

print("\n-- 2. Resolution des comptes ------------------------------------")
for code in ["6142", "4411"]:
    r = c.resolve_account(code)
    check(f"{code} resolu", r["code"].startswith(code), f"{code} -> {r['code']} ({r['name']}) [{r['resolution']}]")

try:
    c.resolve_account("8888")
    check("compte inexistant refuse", False, "aucune erreur levee")
except OdooWriteError as exc:
    check("compte inexistant refuse", "8888" in str(exc), str(exc)[:70])

try:
    c.resolve_account("61")
    check("code trop court refuse", False, "aucune erreur levee")
except OdooWriteError as exc:
    check("code trop court refuse", True, str(exc)[:70])

print("\n-- 3. Creation du brouillon (ECRITURE REELLE) -------------------")
res = None
try:
    res = c.create_draft_move(
        lignes=[
            {"compte": "6142", "libelle": "TEST NISAB - reintegration", "debit": 1200.00, "credit": 0},
            {"compte": "4411", "libelle": "TEST NISAB - contrepartie", "debit": 0, "credit": 1200.00},
        ],
        date_ecriture="2026-08-05",
        ref="TEST NISAB - a supprimer",
        narration="Ecriture de test creee par test_push_odoo.py.",
    )
    check("ecriture creee", res["move_id"] is not None, f"move_id={res['move_id']}")
    check("etat = draft (JAMAIS postee)", res["state"] == "draft", res["state"])
    check("societe correcte", res["company_id"] == societe)
    for cr in res["comptes_resolus"]:
        print(f"           {cr['demande']} -> {cr['code']} {cr['name']}")
except OdooWriteError as exc:
    check("creation du brouillon", False, str(exc)[:120])

print("\n-- 4. Relecture independante ------------------------------------")
if res:
    relu = c._execute("account.move", "read", [res["move_id"]],
                      fields=["state", "move_type", "line_ids"])[0]
    check("relu en state=draft", relu["state"] == "draft", relu["state"])
    check("move_type = entry", relu["move_type"] == "entry")
    check("2 lignes enregistrees", len(relu["line_ids"]) == 2)

print("\n-- 5. Nettoyage -------------------------------------------------")
if res:
    try:
        c._execute("account.move", "unlink", [res["move_id"]])
        check("ecriture de test supprimee",
              c._execute("account.move", "search_count", [["id", "=", res["move_id"]]]) == 0)
    except Exception as exc:
        check("suppression", False, f"a supprimer a la main : move_id={res['move_id']} ({exc})")

print("\n" + ("=> TOUT PASSE" if ok else "=> DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
