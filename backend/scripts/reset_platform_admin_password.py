"""
reset_platform_admin_password.py — Réinitialise le mot de passe d'un compte
admin_plateforme existant, en ligne de commande.

## Pourquoi un script séparé plutôt qu'une route

Même règle que create_platform_admin.py : admin_plateforme ne se crée (et ne
se modifie) QUE par un accès direct au serveur/à la base, jamais via une
route HTTP publique — il n'existe donc aucun flux "mot de passe oublié" en
libre-service pour ce rôle, contrairement à admin_cabinet/collaborateur
(hors scope ici, pas encore de "forgot password" côté produit non plus).
create_platform_admin.py refuse volontairement d'écraser un compte existant
("Un utilisateur existe déjà..."), d'où ce script dédié plutôt qu'un
--force sur l'autre.

Usage (depuis backend/) :
    python -m scripts.reset_platform_admin_password --email admin@iaai-academy.ma --password "nouveau-mdp"
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.models import RoleUtilisateur, Utilisateur


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    # Garde-fou minimal : un --password vide ou trivial serait accepté sans
    # broncher par argparse (une chaîne vide n'est "manquante" pour argparse
    # que si l'argument est absent, pas s'il est fourni vide) et écraserait
    # silencieusement un mot de passe valide par un mot de passe cassé.
    if len(args.password) < 8:
        print("Mot de passe trop court (minimum 8 caractères) — abandon, rien n'a été modifié.")
        return 1

    db = SessionLocal()
    try:
        user = db.execute(select(Utilisateur).where(Utilisateur.email == args.email)).scalar_one_or_none()
        if user is None:
            print(f"Aucun utilisateur avec l'email {args.email}.")
            return 1
        if user.role != RoleUtilisateur.admin_plateforme:
            # Refus volontaire : ce script ne doit pas devenir un outil
            # générique de reset pour tous les rôles (ceux-là passent par
            # PATCH /auth/me/password, authentifié, une fois connecté).
            print(f"{args.email} a le rôle '{user.role.value}', pas admin_plateforme — "
                  "ce script est réservé au bootstrap admin_plateforme.")
            return 1

        user.password_hash = hash_password(args.password)
        db.commit()
        print(f"Mot de passe réinitialisé pour {user.email} (id={user.id}).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
