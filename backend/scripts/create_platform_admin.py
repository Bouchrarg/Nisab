"""
Ce rôle (gestion du corpus fiscal partagé, de la veille, du pipeline
d'ingestion — voir app/admin.py) n'est volontairement PAS accessible via
/auth/register (qui ne crée que des admin_cabinet). Il se crée uniquement
via ce script, exécuté manuellement en ligne de commande par quelqu'un qui
a déjà accès au serveur/à la base — jamais via une route HTTP publique.

Usage :
    cd backend
    python -m scripts.create_platform_admin --email admin@iaai-academy.ma --password "..."

Le script rattache l'utilisateur à une organisation réservée
"IAAI Academy - Interne" (créée si elle n'existe pas encore) : même un
admin_plateforme reste techniquement rattaché à une organisation dans le
schéma actuel (contrainte FK), mais cette organisation n'est jamais un
tenant client et n'a pas vocation à posséder de dossiers.
"""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.models import Organisation, RoleUtilisateur, TypeOrganisation, Utilisateur

INTERNAL_ORG_NAME = "IAAI Academy - Bouchra Rguibi"


def main():
    parser = argparse.ArgumentParser(description="Créer un compte admin_plateforme (accès corpus/veille/pipeline).")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--nom-complet", default="")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = db.execute(select(Utilisateur).where(Utilisateur.email == args.email)).scalar_one_or_none()
        if existing:
            print(f"Un utilisateur existe déjà avec l'email {args.email} (id={existing.id}).")
            return

        org = db.execute(select(Organisation).where(Organisation.nom == INTERNAL_ORG_NAME)).scalar_one_or_none()
        if org is None:
            org = Organisation(id=uuid.uuid4(), nom=INTERNAL_ORG_NAME, type_organisation=TypeOrganisation.cabinet)
            db.add(org)
            db.flush()
            print(f"Organisation interne créée : {org.id}")

        user = Utilisateur(
            id=uuid.uuid4(),
            organisation_id=org.id,
            email=args.email,
            password_hash=hash_password(args.password),
            nom_complet=args.nom_complet,
            role=RoleUtilisateur.admin_plateforme,
        )
        db.add(user)
        db.commit()
        print(f"Compte admin_plateforme créé : {user.email} (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
