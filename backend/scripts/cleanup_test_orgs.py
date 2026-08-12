"""
cleanup_test_orgs.py — Supprime les organisations de test créées via /docs
(Swagger UI), reconnaissables au nom littéral "string" laissé par le
placeholder par défaut de FastAPI sur un champ str non modifié.

Ce n'est PAS un bug applicatif : c'est un artefact de test (appels à
POST /auth/register depuis /docs sans remplacer les valeurs d'exemple).
Ce script nettoie une base de dev/démo, rien d'autre.

Supprime, dans l'ordre des dépendances FK, tout ce qui est rattaché à ces
organisations : citations -> alertes/simulations/notifications -> dossiers
-> accès -> utilisateurs -> organisation.

Usage :
    cd backend
    python -m scripts.cleanup_test_orgs            # dry-run (affiche ce qui serait supprimé)
    python -m scripts.cleanup_test_orgs --confirm   # supprime réellement
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Acces,
    AlerteRisque,
    Citation,
    CitationRisque,
    CitationSimulation,
    ConnexionComptable,
    Declaration,
    Dossier,
    Echeance,
    Invitation,
    NotificationVeille,
    Organisation,
    PieceComptable,
    SimulationControle,
    Utilisateur,
)

TEST_ORG_NAME = "string"


def main():
    parser = argparse.ArgumentParser(description="Purge les organisations de test nommées 'string'.")
    parser.add_argument("--confirm", action="store_true", help="Supprime réellement (sinon dry-run).")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        orgs = db.execute(select(Organisation).where(Organisation.nom == TEST_ORG_NAME)).scalars().all()
        if not orgs:
            print(f"Aucune organisation nommée '{TEST_ORG_NAME}' trouvée.")
            return

        for org in orgs:
            dossiers = db.execute(select(Dossier).where(Dossier.organisation_id == org.id)).scalars().all()
            users = db.execute(select(Utilisateur).where(Utilisateur.organisation_id == org.id)).scalars().all()
            print(f"Organisation {org.id} ('{org.nom}', créée le {org.created_at}) : "
                  f"{len(users)} utilisateur(s), {len(dossiers)} dossier(s)")

            if not args.confirm:
                continue

            for d in dossiers:
                alerte_ids = [a.id for a in db.execute(select(AlerteRisque).where(AlerteRisque.dossier_id == d.id)).scalars()]
                sim_ids = [s.id for s in db.execute(select(SimulationControle).where(SimulationControle.dossier_id == d.id)).scalars()]
                if alerte_ids:
                    db.query(CitationRisque).filter(CitationRisque.alerte_id.in_(alerte_ids)).delete(synchronize_session=False)
                if sim_ids:
                    db.query(CitationSimulation).filter(CitationSimulation.simulation_id.in_(sim_ids)).delete(synchronize_session=False)
                db.query(Citation).filter(Citation.dossier_id == d.id).delete(synchronize_session=False)
                db.query(AlerteRisque).filter(AlerteRisque.dossier_id == d.id).delete(synchronize_session=False)
                db.query(SimulationControle).filter(SimulationControle.dossier_id == d.id).delete(synchronize_session=False)
                db.query(NotificationVeille).filter(NotificationVeille.dossier_id == d.id).delete(synchronize_session=False)
                db.query(Echeance).filter(Echeance.dossier_id == d.id).delete(synchronize_session=False)
                db.query(Declaration).filter(Declaration.dossier_id == d.id).delete(synchronize_session=False)
                db.query(PieceComptable).filter(PieceComptable.dossier_id == d.id).delete(synchronize_session=False)
                db.query(ConnexionComptable).filter(ConnexionComptable.dossier_id == d.id).delete(synchronize_session=False)
                db.query(Acces).filter(Acces.dossier_id == d.id).delete(synchronize_session=False)
                db.delete(d)

            db.query(Invitation).filter(Invitation.organisation_id == org.id).delete(synchronize_session=False)
            for u in users:
                db.query(Acces).filter(Acces.utilisateur_id == u.id).delete(synchronize_session=False)
                db.delete(u)
            db.delete(org)

        if args.confirm:
            db.commit()
            print(f"\n{len(orgs)} organisation(s) supprimée(s).")
        else:
            print("\nDry-run — relancer avec --confirm pour supprimer réellement.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
