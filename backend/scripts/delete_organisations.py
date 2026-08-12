"""
delete_organisations.py — Supprime intégralement une ou plusieurs
organisations données par nom exact (utilisateurs, dossiers et toutes
leurs dépendances). Généralise cleanup_test_orgs.py (qui ne cible que le
nom littéral "string") à n'importe quelle organisation de test désignée
explicitement.

Même ordre de suppression FK : citations -> alertes/simulations/
notifications -> échéances/déclarations/pièces/connexions -> accès ->
dossiers -> invitations -> utilisateurs -> organisation.

Usage (depuis backend/) :
    python -m scripts.delete_organisations --names "Cabinet Test A,Cabinet Test B"
    python -m scripts.delete_organisations --names "Cabinet Test A,Cabinet Test B" --confirm
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


def main():
    parser = argparse.ArgumentParser(description="Supprime intégralement les organisations désignées par nom exact.")
    parser.add_argument("--names", required=True, help="Noms exacts d'organisations à supprimer, séparés par des virgules.")
    parser.add_argument("--confirm", action="store_true", help="Supprime réellement (sinon dry-run).")
    args = parser.parse_args()

    names = [n.strip() for n in args.names.split(",") if n.strip()]

    db = SessionLocal()
    try:
        orgs = db.execute(select(Organisation).where(Organisation.nom.in_(names))).scalars().all()
        found_names = {o.nom for o in orgs}
        missing = set(names) - found_names
        if missing:
            print(f"Introuvable(s), ignoré(s) : {', '.join(missing)}")
        if not orgs:
            print("Aucune organisation correspondante trouvée.")
            return

        for org in orgs:
            dossiers = db.execute(select(Dossier).where(Dossier.organisation_id == org.id)).scalars().all()
            users = db.execute(select(Utilisateur).where(Utilisateur.organisation_id == org.id)).scalars().all()
            print(f"\nOrganisation '{org.nom}' ({org.id}) : {len(users)} utilisateur(s), {len(dossiers)} dossier(s)")
            for u in users:
                print(f"  utilisateur : {u.email} ({u.role.value})")
            for d in dossiers:
                print(f"  dossier     : {d.raison_sociale}")

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
