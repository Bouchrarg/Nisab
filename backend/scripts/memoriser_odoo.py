"""
memoriser_odoo.py — Enregistre les identifiants Odoo d'un dossier SANS
resynchroniser les données comptables.

## Pourquoi ce script existe

`POST /dossiers/{id}/odoo/connect` fait deux choses à la fois : il recharge le
snapshot comptable ET (si la case est cochée) mémorise les identifiants
chiffrés. Or `odoo/connect` REMPLACE tout le snapshot — c'est voulu, Odoo est
une source de vérité live.

Conséquence : sur un dossier dont le snapshot est une FUSION (connexion Odoo
puis import de fichier, cf. `_fusionner_donnees_comptables`), repasser par la
route pour la seule raison d'enregistrer un mot de passe détruit la partie
fichier de la fusion et oblige à relancer tout l'audit. Ce script fait
uniquement la moitié qui manque.

Il ne remplace pas la route : c'est un outil de reprise, pour le cas où la
mémorisation a échoué alors que les données, elles, sont bonnes.

## Garde-fous

- Les identifiants sont VÉRIFIÉS contre Odoo (authenticate seul, aucune
  écriture, aucune lecture de données) avant d'être stockés. Enregistrer un
  mot de passe faux ne ferait que déplacer l'échec au moment du push.
- La ligne `connexion_comptable` doit déjà exister : ce script ne crée pas une
  connexion, il complète celle qu'une synchronisation a laissée. Si elle
  n'existe pas, c'est qu'aucune donnée n'a jamais été chargée — il faut alors
  passer par la route, il n'y a rien à préserver.
- `derniere_sync` n'est PAS touché : aucune synchronisation n'a eu lieu, le
  prétendre serait mentir sur la fraîcheur des données.

Usage (depuis backend/) :
    python -m scripts.memoriser_odoo --dossier "Nisab_demo" \
        --url http://localhost:8069 --db Nisab_demo \
        --user admin --password monmotdepasse
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from app.db_admin import AdminSessionLocal
from app.models import ConnexionComptable, Dossier, TypeConnexion
from app.odoo_connector import OdooConnector
from app.secrets_store import chiffrer, cle_disponible


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enregistre les identifiants Odoo d'un dossier sans resynchroniser."
    )
    parser.add_argument("--dossier", required=True,
                        help="Raison sociale exacte du dossier, ou son UUID.")
    parser.add_argument("--url", required=True, help="URL Odoo, ex. http://localhost:8069")
    parser.add_argument("--db", required=True, help="Nom de la base Odoo, ex. Nisab_demo")
    parser.add_argument("--user", required=True, help="Login Odoo")
    parser.add_argument("--password", required=True, help="Mot de passe Odoo")
    args = parser.parse_args()

    if not cle_disponible():
        print("NISAB_SECRET_KEY absente de l'environnement : impossible de chiffrer.", file=sys.stderr)
        return 1

    db = AdminSessionLocal()
    try:
        dossier = db.execute(
            select(Dossier).where(Dossier.raison_sociale == args.dossier)
        ).scalars().first()
        if dossier is None:
            try:
                dossier = db.get(Dossier, args.dossier)
            except Exception:
                # Un argument qui n'est pas un UUID fait échouer le cast côté
                # Postgres et AVORTE la transaction : sans rollback, le listing
                # d'aide ci-dessous échouerait à son tour et l'utilisateur
                # n'aurait qu'une stacktrace au lieu du nom de son dossier.
                db.rollback()
                dossier = None
        if dossier is None:
            print(f"Dossier introuvable : {args.dossier!r}", file=sys.stderr)
            print("Dossiers existants :", file=sys.stderr)
            for d in db.execute(select(Dossier).order_by(Dossier.raison_sociale)).scalars().all():
                print(f"  - {d.raison_sociale}  ({d.id})", file=sys.stderr)
            return 1

        connexion = db.execute(
            select(ConnexionComptable).where(
                ConnexionComptable.dossier_id == dossier.id,
                ConnexionComptable.type == TypeConnexion.odoo,
            )
        ).scalars().first()
        if connexion is None:
            print(
                f"Aucune connexion Odoo enregistrée pour « {dossier.raison_sociale} ». "
                "Passez par l'interface (onglet Odoo) : il n'y a aucune donnée à préserver.",
                file=sys.stderr,
            )
            return 1

        # Vérification AVANT stockage : un mot de passe faux échouerait sinon
        # au moment du push, c'est-à-dire au pire moment possible.
        print(f"Vérification des identifiants sur {args.url} (base {args.db})...")
        try:
            connecteur = OdooConnector(args.url, args.db, args.user, args.password)
            uid = connecteur.authenticate()
        except Exception as exc:
            print(f"Authentification Odoo refusée : {exc}", file=sys.stderr)
            print("Rien n'a été enregistré.", file=sys.stderr)
            return 1
        print(f"Authentification OK (uid={uid}).")

        deja = bool(connexion.identifiants_chiffres)
        connexion.identifiants_chiffres = chiffrer({
            "url": args.url, "db": args.db,
            "username": args.user, "password": args.password,
        })
        # derniere_sync volontairement inchangé : aucune donnée n'a été relue.
        db.commit()

        print(
            f"Identifiants {'remplacés' if deja else 'enregistrés'} (chiffrés) pour "
            f"« {dossier.raison_sociale} ». Le push de brouillon Odoo est maintenant disponible."
        )
        print("Aucune donnée comptable n'a été touchée : snapshot et alertes intacts.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
