"""
setup_odoo_compta.py — Installe dans Odoo les modules dont Nisab a besoin.

## Pourquoi ce script existe

L'app qui s'appelle « Comptabilite » dans le catalogue Odoo (`account_accountant`)
est reservee a l'edition Enterprise : en Community, cliquer dessus affiche une
page de mise a niveau payante, jamais une installation. C'est la cause du
« je n'arrive pas a telecharger l'app comptabilite ».

Nisab n'en a pas besoin. Les quatre modeles qu'il lit et ecrit
(account.move, account.move.line, account.account, account.journal) viennent
tous du module `account`, appele « Facturation » en Community et parfaitement
installable. `account_accountant` n'ajoute que le lettrage bancaire, les
tableaux de bord comptables et les etats fiscaux — que Nisab ne touche jamais.

Le second module, `l10n_ma`, est le vrai enjeu : c'est lui qui charge le plan
comptable marocain (CGNC). Sans lui, les comptes 6142 / 4411 / 34551 que
manipule l'audit n'existent tout simplement pas dans la base.

## ATTENTION — ce script ECRIT dans Odoo

Installer un module Odoo est difficile a annuler proprement : la desinstallation
laisse des residus et peut supprimer des donnees liees. Le script est donc en
mode simulation par defaut, comme scripts/cleanup_test_orgs.py. Il faut passer
--confirm pour installer reellement.

Le plan comptable ne s'applique qu'a une societe qui n'en a pas encore. Si la
base a deja un plan charge, l10n_ma s'installera sans le remplacer — c'est le
comportement voulu, on ne rebat pas les cartes d'une comptabilite existante.

## Usage depuis backend/

    # 1. Voir ce qui serait fait, sans rien modifier
    python -m scripts.setup_odoo_compta --db Nisab_demo --user LOGIN --password MDP

    # 2. Installer pour de vrai
    python -m scripts.setup_odoo_compta --db Nisab_demo --user LOGIN --password MDP --confirm

Les identifiants peuvent venir de ODOO_DB / ODOO_USER / ODOO_PASSWORD.
"""

from __future__ import annotations

import argparse
import os
import sys
import xmlrpc.client

#: Modules requis, dans l'ordre d'installation. `account` d'abord : `l10n_ma`
#: en depend et son plan comptable n'a nulle part ou s'appliquer sans lui.
MODULES_REQUIS = [
    ("account", "Facturation (account.move / account.account / account.journal)"),
    ("l10n_ma", "Maroc — plan comptable CGNC"),
]

OK = "  [OK]   "
KO = "  [KO]   "
INFO = "  [i]    "


def cause(exc: Exception) -> str:
    """Derniere ligne utile d'une erreur Odoo (les Fault portent toute la trace serveur)."""
    lignes = [l.strip() for l in str(exc).replace("\\n", "\n").splitlines() if l.strip()]
    return lignes[-1] if lignes else str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Installe les modules comptables Odoo requis par Nisab.")
    parser.add_argument("--url", default=os.environ.get("ODOO_URL", "http://localhost:8069"))
    parser.add_argument("--db", default=os.environ.get("ODOO_DB"))
    parser.add_argument("--user", default=os.environ.get("ODOO_USER"))
    parser.add_argument("--password", default=os.environ.get("ODOO_PASSWORD"))
    parser.add_argument("--confirm", action="store_true", help="Installe reellement (sinon simulation).")
    args = parser.parse_args()

    if not (args.db and args.user and args.password):
        print("Il manque --db, --user ou --password (ou ODOO_DB / ODOO_USER / ODOO_PASSWORD).")
        return 2

    print(f"\nInstance : {args.url}  |  base : {args.db}")
    print("Mode     : " + ("INSTALLATION REELLE" if args.confirm else "SIMULATION (aucune modification)"))
    print("=" * 72)

    # --- connexion --------------------------------------------------------
    try:
        common = xmlrpc.client.ServerProxy(f"{args.url}/xmlrpc/2/common")
        version = common.version()
        uid = common.authenticate(args.db, args.user, args.password, {})
    except Exception as exc:
        print(KO + f"Connexion impossible : {cause(exc)}")
        return 1
    if not uid:
        print(KO + "Authentification refusee (base, identifiant ou mot de passe incorrect).")
        return 1

    edition = "Enterprise" if version.get("server_version_info", [None] * 6)[5] == "e" else "Community"
    print(INFO + f"Odoo {version.get('server_version')} — edition {edition}")
    if edition == "Community":
        print(INFO + "L'app 'Comptabilite' (account_accountant) est Enterprise et ne s'installera pas.")
        print(INFO + "C'est normal, et sans consequence : Nisab n'utilise que le module 'account'.")

    models = xmlrpc.client.ServerProxy(f"{args.url}/xmlrpc/2/object")

    def call(modele: str, methode: str, *a, **kw):
        return models.execute_kw(args.db, uid, args.password, modele, methode, list(a), kw)

    # --- droits ----------------------------------------------------------
    try:
        if not call("ir.module.module", "check_access_rights", "write", raise_exception=False):
            print(KO + "Cet utilisateur n'a pas le droit d'installer des modules.")
            print(INFO + "Utilise le compte administrateur de la base.")
            return 1
    except Exception:
        pass  # methode absente selon la version : on laissera l'install echouer proprement

    # --- etat actuel ------------------------------------------------------
    print("\n1. Etat des modules requis")
    a_installer: list[tuple[int, str, str]] = []
    for technique, libelle in MODULES_REQUIS:
        try:
            res = call("ir.module.module", "search_read",
                       [["name", "=", technique]], fields=["id", "name", "state", "shortdesc"], limit=1)
        except Exception as exc:
            print(KO + f"Lecture du catalogue impossible : {cause(exc)}")
            return 1

        if not res:
            print(KO + f"{technique:<12} introuvable dans le catalogue.")
            print(INFO + "Va dans Applications > Mettre a jour la liste des applications, puis relance.")
            continue

        module = res[0]
        etat = module["state"]
        marque = OK if etat == "installed" else INFO
        print(f"{marque}{technique:<12} {etat:<14} {libelle}")
        if etat != "installed":
            a_installer.append((module["id"], technique, libelle))

    if not a_installer:
        print("\n" + OK + "Les deux modules sont deja installes, rien a faire.")
    else:
        print(f"\n2. {len(a_installer)} module(s) a installer")
        for _, technique, libelle in a_installer:
            print(f"         - {technique} ({libelle})")

        if not args.confirm:
            print("\n" + INFO + "Simulation : rien n'a ete modifie.")
            print(INFO + "Relance la meme commande avec --confirm pour installer.")
            print(INFO + "Fais-le sur Nisab_demo, pas sur ta base de sauvegarde.")
            return 0

        for module_id, technique, _ in a_installer:
            print(f"\n         Installation de {technique}...")
            try:
                # button_immediate_install recharge le registre Odoo : l'appel
                # peut prendre plusieurs dizaines de secondes et la reponse
                # arriver apres un long silence. C'est normal.
                call("ir.module.module", "button_immediate_install", [module_id])
                print(OK + f"{technique} installe.")
            except Exception as exc:
                print(KO + f"Echec sur {technique} : {cause(exc)}")
                print(INFO + "Installe-le a la main depuis Applications dans l'interface Odoo.")
                return 1

    # --- verification du plan comptable ----------------------------------
    print("\n3. Plan comptable")
    try:
        nb = call("account.account", "search_count", [])
        print(INFO + f"{nb} compte(s) dans le plan comptable.")
        if nb == 0:
            print(KO + "Plan comptable vide.")
            print(INFO + "Dans Odoo : Facturation > Configuration > Parametres > Comptabilite,")
            print(INFO + "verifie que la localisation fiscale 'Maroc' est bien selectionnee.")
        else:
            echantillon = call("account.account", "search_read",
                               [["code", "in", ["6142", "4411", "34551", "3421"]]],
                               fields=["code", "name"], limit=6)
            if echantillon:
                print(OK + "Comptes CGNC attendus par l'audit, presents :")
                for c in echantillon:
                    print(f"           {str(c.get('code')):<10} {c.get('name', '')}")
            else:
                apercu = call("account.account", "search_read", [], fields=["code", "name"], limit=6)
                print(INFO + "Aucun code CGNC exact trouve. Codes reellement presents :")
                for c in apercu:
                    print(f"           {str(c.get('code')):<10} {c.get('name', '')}")
                print(INFO + "Le plan est probablement generique : la localisation marocaine")
                print(INFO + "n'a pas ete appliquee a la societe.")
    except Exception as exc:
        print(INFO + f"Plan comptable illisible pour l'instant ({cause(exc)}).")
        print(INFO + "Redemarre Odoo puis relance : le registre vient d'etre recharge.")

    print("\n" + "=" * 72)
    print("Etape suivante : python -m scripts.check_odoo18 --db " + args.db + " --user ... --password ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
