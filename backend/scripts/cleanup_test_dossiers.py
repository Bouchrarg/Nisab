"""
cleanup_test_dossiers.py — Supprime, au sein d'UNE organisation, tous les
dossiers sauf une liste explicite à conserver (--keep). Complète
cleanup_test_orgs.py, qui ne cible que des organisations entières nommées
"string" — ici on nettoie des dossiers de test accumulés dans une
organisation par ailleurs légitime.

Même ordre de suppression FK que cleanup_test_orgs.py : citations ->
alertes/simulations/notifications -> échéances/déclarations/pièces/connexions
-> accès -> dossier.

Usage (depuis backend/) :
    python -m scripts.cleanup_test_dossiers --org "Atlas Négoce SARL" --keep "Atlas Négoce SARL,nisab_demo"
    python -m scripts.cleanup_test_dossiers --org "Atlas Négoce SARL" --keep "Atlas Négoce SARL,nisab_demo" --confirm
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
    NotificationVeille,
    Organisation,
    PieceComptable,
    SimulationControle,
)


def main():
    parser = argparse.ArgumentParser(description="Supprime les dossiers de test d'une organisation, sauf ceux listés dans --keep.")
    parser.add_argument("--org", required=True, help="Nom exact de l'organisation (Organisation.nom).")
    parser.add_argument("--keep", required=True, help="Raisons sociales à conserver, séparées par des virgules.")
    parser.add_argument("--confirm", action="store_true", help="Supprime réellement (sinon dry-run).")
    args = parser.parse_args()

    keep_names = {n.strip() for n in args.keep.split(",") if n.strip()}

    db = SessionLocal()
    try:
        org = db.execute(select(Organisation).where(Organisation.nom == args.org)).scalar_one_or_none()
        if not org:
            print(f"Aucune organisation nommée '{args.org}' trouvée.")
            return

        dossiers = db.execute(select(Dossier).where(Dossier.organisation_id == org.id)).scalars().all()
        to_delete = [d for d in dossiers if d.raison_sociale not in keep_names]
        to_keep = [d for d in dossiers if d.raison_sociale in keep_names]

        print(f"Organisation '{org.nom}' ({org.id}) : {len(dossiers)} dossier(s) au total.")
        print(f"\nConservés ({len(to_keep)}) :")
        for d in to_keep:
            print(f"  - {d.raison_sociale} ({d.id})")
        print(f"\n{'Supprimés' if args.confirm else 'À supprimer'} ({len(to_delete)}) :")
        for d in to_delete:
            print(f"  - {d.raison_sociale} ({d.id})")

        if not args.confirm:
            print("\nDry-run — relancer avec --confirm pour supprimer réellement.")
            return

        for d in to_delete:
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

        db.commit()
        print(f"\n{len(to_delete)} dossier(s) supprimé(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
