"""
check_odoo18.py — Verifications prealables avant d'ecrire create_draft_move.

STRICTEMENT EN LECTURE SEULE : ce script ne cree, ne modifie et ne supprime
rien dans Odoo. Il repond a trois questions dont depend le workflow de
correction (bloc 2), et qu'il vaut mieux se poser avant d'ecrire le code que
apres :

  1. Le connecteur existant lit-il encore correctement une instance Odoo 18 ?
  2. Peut-on retrouver un compte comptable par son code ?
     Depuis Odoo 17, `account.account.code` est devenu un champ dependant de
     la societe (stocke dans `code_store`). create_draft_move en depend pour
     resoudre les comptes d'une ecriture proposee. Si la recherche directe ne
     marche pas, le repli est de charger la liste (id, code) a la connexion et
     de resoudre par id -- mais autant le savoir maintenant.
  3. Existe-t-il un journal utilisable, et l'utilisateur a-t-il le droit de
     creer une ecriture ? (droit verifie via check_access_rights, qui ne
     declenche aucune ecriture)

Usage depuis backend/ :

    python -m scripts.check_odoo18 --url http://localhost:8069 --db NOM_BASE \\
        --user admin@exemple.ma --password MOT_DE_PASSE

Les valeurs peuvent aussi venir de l'environnement (ODOO_URL, ODOO_DB,
ODOO_USER, ODOO_PASSWORD) pour eviter de taper le mot de passe dans
l'historique du shell.
"""

from __future__ import annotations

import argparse
import os
import sys
import xmlrpc.client

# Racines CGNC dont create_draft_move aura besoin pour ecrire une OD de
# correction. On teste des PREFIXES et non des codes exacts : le plan marocain
# livre par Odoo complete les codes a 5 ou 6 chiffres (6142 -> 614210), alors
# que le CGI, les manuels de compta et donc le LLM raisonnent en 4 chiffres.
# C'est le decalage que create_draft_move devra absorber.
RACINES_CGNC = [
    ("6142", "Transports (charge type)"),
    ("4411", "Fournisseurs"),
    ("3455", "TVA recuperable"),
    ("4455", "TVA facturee"),
    ("3421", "Clients"),
    ("5161", "Caisse"),
]

OK = "  [OK]   "
KO = "  [KO]   "
INFO = "  [i]    "


def cause(exc: Exception) -> str:
    """
    Derniere ligne utile d'une erreur Odoo.

    xmlrpc.client.Fault renvoie la trace Python complete du serveur (40+ lignes)
    dans le message. Illisible tel quel, alors que la derniere ligne dit
    exactement ce qui ne va pas.
    """
    texte = str(exc)
    lignes = [l.strip() for l in texte.replace("\\n", "\n").splitlines() if l.strip()]
    return lignes[-1] if lignes else texte


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifications Odoo 18 en lecture seule.")
    parser.add_argument("--url", default=os.environ.get("ODOO_URL", "http://localhost:8069"))
    parser.add_argument("--db", default=os.environ.get("ODOO_DB"))
    parser.add_argument("--user", default=os.environ.get("ODOO_USER"))
    parser.add_argument("--password", default=os.environ.get("ODOO_PASSWORD"))
    parser.add_argument("--list-db", action="store_true", help="Liste les bases de l'instance et s'arrete.")
    args = parser.parse_args()

    if args.list_db:
        try:
            db_service = xmlrpc.client.ServerProxy(f"{args.url}/xmlrpc/2/db")
            bases = db_service.list()
        except Exception as exc:
            print(f"Impossible de lister les bases : {exc}")
            print("Certaines instances desactivent cette methode (list_db = False dans odoo.conf).")
            print("Dans ce cas, le nom de la base est visible en haut de l'ecran de connexion Odoo.")
            return 1
        if not bases:
            print("Aucune base trouvee sur cette instance.")
            return 1
        print(f"Bases disponibles sur {args.url} :")
        for b in bases:
            print(f"  - {b}")
        return 0

    if not (args.db and args.user and args.password):
        print("Il manque --db, --user ou --password (ou les variables ODOO_DB / ODOO_USER / ODOO_PASSWORD).")
        print("Pour lister les bases disponibles sur l'instance :")
        print(f"  python -m scripts.check_odoo18 --url {args.url} --list-db")
        return 2

    problemes: list[str] = []

    print(f"\nInstance : {args.url}  |  base : {args.db}  |  utilisateur : {args.user}")
    print("=" * 72)

    # --- 0. Version + authentification -----------------------------------
    print("\n0. Connexion")
    try:
        common = xmlrpc.client.ServerProxy(f"{args.url}/xmlrpc/2/common")
        version = common.version()
        print(INFO + f"Odoo {version.get('server_version', '?')} (protocole {version.get('protocol_version', '?')})")
    except Exception as exc:
        print(KO + f"Instance injoignable : {cause(exc)}")
        print("\n   Verifie qu'Odoo tourne et que l'URL est la bonne (souvent http://localhost:8069).")
        return 1

    try:
        uid = common.authenticate(args.db, args.user, args.password, {})
    except Exception as exc:
        print(KO + f"Erreur d'authentification : {cause(exc)}")
        return 1
    if not uid:
        print(KO + "Authentification refusee (base, identifiant ou mot de passe incorrect).")
        return 1
    print(OK + f"Authentifie, uid = {uid}")

    models = xmlrpc.client.ServerProxy(f"{args.url}/xmlrpc/2/object")

    # Societe cible : celle qui detient reellement les ecritures. Determinee
    # plus bas ; tant qu'elle est None, les appels partent sans contexte de
    # societe, donc dans la societe courante de l'utilisateur — qui n'est pas
    # forcement la bonne.
    societe_cible: int | None = None

    def call(modele: str, methode: str, *a, **kw):
        """
        Appel XML-RPC, force dans le contexte de la societe cible.

        `allowed_company_ids` n'est pas une precaution decorative :
        account.account.code est un champ DEPENDANT DE LA SOCIETE depuis
        Odoo 17. Hors du bon contexte, chercher [('code','=','441110')] ne
        renvoie rien du tout, alors que le compte existe — et les identifiants
        different d'une societe a l'autre (441110 = id 892 dans une societe,
        id 252 dans une autre). Resoudre un compte dans le mauvais contexte
        donne donc soit rien, soit le compte d'une autre societe.
        """
        if societe_cible is not None:
            kw.setdefault("context", {})["allowed_company_ids"] = [societe_cible]
        return models.execute_kw(args.db, uid, args.password, modele, methode, list(a), kw)

    # --- 1. Le connecteur existant lit-il toujours ? ----------------------
    print("\n1. Lecture des donnees comptables (connecteur existant)")
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from app.odoo_connector import OdooConnector

        connecteur = OdooConnector(url=args.url, db=args.db, username=args.user, password=args.password)
        connecteur.authenticate()
        data = connecteur.fetch_accounting_data()
        print(OK + f"societe   : {data.get('company', {}).get('name', '?')}")
        print(OK + f"ecritures : {len(data.get('moves', []))}")
        print(OK + f"lignes    : {len(data.get('lines', []))}")
        print(OK + f"tiers     : {len(data.get('partners', []))}")
        if not data.get("moves"):
            print(INFO + "Aucune ecriture comptable validee sur les 12 derniers mois.")
            print(INFO + "L'audit n'aura rien a analyser : saisis quelques factures fournisseur")
            print(INFO + "dans Odoo, ou utilise l'import CSV / le mode demonstration.")
    except Exception as exc:
        print(KO + f"fetch_accounting_data a echoue : {cause(exc)}")
        problemes.append("le connecteur ne lit pas cette instance")

    # --- 1 bis. Quelle societe detient reellement la comptabilite ? ------
    print("\n1 bis. Societe cible")
    try:
        societes = call("res.company", "search_read", [], fields=["id", "name", "country_id", "currency_id"])
        utilisateur = call("res.users", "read", [uid], fields=["company_id"])[0]
        echantillon_moves = call("account.move", "search_read", [["state", "=", "posted"]],
                                 fields=["company_id"], limit=200)
        compte_par_soc: dict[int, int] = {}
        for m in echantillon_moves:
            if m.get("company_id"):
                compte_par_soc[m["company_id"][0]] = compte_par_soc.get(m["company_id"][0], 0) + 1

        for s in societes:
            n = compte_par_soc.get(s["id"], 0)
            marque = " <- societe courante de l'utilisateur" if s["id"] == utilisateur["company_id"][0] else ""
            pays = s["country_id"][1] if s.get("country_id") else "?"
            print(f"{INFO}id {s['id']:<3} {s['name']:<30} {pays:<16} {n:>3} ecriture(s){marque}")

        if compte_par_soc:
            societe_cible = max(compte_par_soc, key=compte_par_soc.get)
            nom_cible = next((s["name"] for s in societes if s["id"] == societe_cible), "?")
            print(OK + f"Societe cible retenue : id {societe_cible} ({nom_cible}) — celle qui detient les ecritures.")
            if societe_cible != utilisateur["company_id"][0]:
                print(KO + "Ce n'est PAS la societe courante de l'utilisateur.")
                print(INFO + "Sans contexte explicite, une ecriture creee atterrirait dans la mauvaise")
                print(INFO + "societe, avec des comptes que Odoo refuserait. create_draft_move devra")
                print(INFO + "forcer allowed_company_ids sur la societe cible.")
                problemes.append("societe courante differente de la societe comptable")
        else:
            print(INFO + "Aucune ecriture validee : impossible de deduire la societe cible.")
    except Exception as exc:
        print(INFO + f"Lecture des societes impossible ({cause(exc)}).")

    # --- 2. Resolution d'un compte par son code --------------------------
    print("\n2. Resolution des comptes par code, dans le contexte de la societe cible")
    champ_code_cherchable = False
    try:
        champs = call("account.account", "fields_get", [], attributes=["type", "store", "searchable"])
        infos = champs.get("code", {})
        print(INFO + f"champ 'code' : store={infos.get('store')} searchable={infos.get('searchable')}")
        if "code_store" in champs:
            print(INFO + "'code_store' present -> Odoo 17+, 'code' est dependant de la societe.")
    except Exception as exc:
        print(KO + f"fields_get impossible : {cause(exc)}")

    # Test auto-calibre : on prend un compte reel de CETTE base et on verifie
    # qu'on sait le retrouver par son code. Tester des codes devines mene a
    # conclure "la recherche est cassee" alors que c'est le jeu de test qui
    # ne correspond pas au plan comptable installe.
    try:
        temoin = call("account.account", "search_read", [], fields=["id", "code", "name"], limit=1)
    except Exception as exc:
        print(KO + f"lecture du plan comptable impossible : {cause(exc)}")
        problemes.append("plan comptable illisible")
        temoin = []

    if not temoin:
        print(KO + "Plan comptable vide.")
        print(INFO + "Installe le module 'Facturation' et applique la localisation fiscale Maroc")
        print(INFO + "(voir scripts/setup_odoo_compta.py), puis relance.")
        problemes.append("plan comptable vide")
    else:
        code_reel = str(temoin[0]["code"])
        retrouve = call("account.account", "search_read", [["code", "=", code_reel]], fields=["id", "code"], limit=1)
        if retrouve:
            champ_code_cherchable = True
            print(OK + f"Recherche exacte par code fonctionnelle (temoin {code_reel}).")
        else:
            print(KO + f"Le compte {code_reel} existe mais n'est pas retrouve par [('code','=',...)].")
            print(INFO + "Repli necessaire : resolution par id via un cache charge a la connexion.")
            problemes.append("recherche par code non fonctionnelle")

        total = call("account.account", "search_count", [])
        longueurs = sorted({len(str(c["code"])) for c in call("account.account", "search_read", [], fields=["code"], limit=500)})
        print(INFO + f"{total} comptes | longueur des codes : {longueurs}")
        if 4 not in longueurs:
            print(INFO + "Aucun code a 4 chiffres : le plan est complete (6142 -> 614210).")
            print(INFO + "create_draft_move devra donc resoudre par PREFIXE, pas par egalite,")
            print(INFO + "car le LLM raisonne en codes CGNC a 4 chiffres.")

        print("\n   Racines CGNC utiles a une OD de correction :")
        for racine, libelle in RACINES_CGNC:
            try:
                res = call("account.account", "search_read", [["code", "=like", racine + "%"]],
                           fields=["code", "name"], limit=2, order="code")
            except Exception as exc:
                print(KO + f"recherche par prefixe refusee : {cause(exc)}")
                problemes.append("recherche par prefixe non fonctionnelle")
                break
            if res:
                exemples = ", ".join(f"{r['code']}" for r in res)
                print(f"     {OK.strip():<8} {racine:<6} {libelle:<26} -> {exemples}")
            else:
                print(f"     {KO.strip():<8} {racine:<6} {libelle:<26} -> aucun compte")
                problemes.append(f"aucun compte sous la racine {racine}")

    # --- 3. Journal + droit de creation ----------------------------------
    print("\n3. Journal cible et droit de creation d'ecriture")
    try:
        journaux = call("account.journal", "search_read", [["type", "=", "general"]], fields=["id", "code", "name"], limit=5)
        if journaux:
            print(OK + "Journal(aux) de type 'general' disponible(s) :")
            for j in journaux:
                print(f"           {j.get('code', '?'):<8} id {j['id']:<5} {j.get('name', '')}")
        else:
            tous = call("account.journal", "search_read", [], fields=["id", "code", "name", "type"], limit=8)
            print(KO + "Aucun journal de type 'general'. Journaux presents :")
            for j in tous:
                print(f"           {j.get('code', '?'):<8} type={j.get('type')} {j.get('name', '')}")
            problemes.append("pas de journal 'general'")
    except Exception as exc:
        print(KO + f"lecture des journaux impossible : {cause(exc)}")
        problemes.append("journaux illisibles")

    try:
        # check_access_rights ne cree rien : il repond juste "as-tu le droit".
        peut_creer = call("account.move", "check_access_rights", "create", raise_exception=False)
        if peut_creer:
            print(OK + "L'utilisateur a le droit de creer une ecriture (account.move).")
        else:
            print(KO + "L'utilisateur n'a PAS le droit de creer une ecriture.")
            print(INFO + "Donne-lui le groupe 'Comptabilite / Comptable' dans Odoo.")
            problemes.append("droit de creation d'ecriture manquant")
    except Exception as exc:
        print(INFO + f"check_access_rights indisponible ({cause(exc)}) - a verifier manuellement.")

    # --- Synthese --------------------------------------------------------
    print("\n" + "=" * 72)
    if not problemes:
        print("RESULTAT : tout est vert.")
        if champ_code_cherchable:
            print("create_draft_move pourra resoudre les comptes par code, comme prevu.")
        return 0

    print("RESULTAT : points a traiter avant d'ecrire le push Odoo :")
    for p in problemes:
        print(f"  - {p}")
    print("\nAucun n'est bloquant pour le reste du projet : le workflow de correction")
    print("fonctionne sans Odoo (les propositions restent validables et exportables),")
    print("seul le bouton 'Creer le brouillon dans Odoo' en depend.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
