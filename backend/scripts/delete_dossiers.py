"""
delete_dossiers.py — Supprime, un par un, les dossiers désignés explicitement
par leur id. 
## Pourquoi par id, pas par nom

cleanup_test_dossiers.py / delete_organisations.py sélectionnent par
raison_sociale, ce qui marche tant que les noms sont uniques. Mais le
déclencheur de ce script est justement l'inverse : deux dossiers avec le
MÊME nom affiché (ex. "MA Company" vs "Nisab_demo" — une reconnexion Odoo
avant un correctif crée un doublon, voir OdooPage.jsx). Supprimer par nom
dans ce cas viserait le mauvais dossier au petit bonheur. `--list` affiche
les id pour lever l'ambiguïté avant de choisir.

Même ordre de suppression FK que les 3 scripts voisins : citations ->
alertes/simulations/notifications -> échéances/déclarations/pièces/connexions
-> accès -> dossier. (PropositionCorrection / CitationProposition ne sont pas
listées ici : elles ont ondelete="CASCADE" sur alerte_risque.id /
proposition_correction.id, donc Postgres les supprime tout seul quand on
supprime les alertes.)

Usage (depuis backend/) :
    python -m scripts.delete_dossiers --list
    python -m scripts.delete_dossiers --ids <uuid1>,<uuid2>              # dry-run
    python -m scripts.delete_dossiers --ids <uuid1>,<uuid2> --confirm    # supprime réellement
"""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import select

from app.db_admin import AdminSessionLocal
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


def lister(db) -> None:
    dossiers = db.execute(select(Dossier).order_by(Dossier.raison_sociale)).scalars().all()
    if not dossiers:
        print("Aucun dossier en base.")
        return

    orgs = {o.id: o.nom for o in db.execute(select(Organisation)).scalars().all()}

    print(f"{len(dossiers)} dossier(s) :\n")
    for d in dossiers:
        nb_alertes = db.query(AlerteRisque).filter(
            AlerteRisque.dossier_id == d.id, AlerteRisque.actif.is_(True)
        ).count()
        nb_pieces = db.query(PieceComptable).filter(PieceComptable.dossier_id == d.id).count()
        connexion = db.execute(
            select(ConnexionComptable).where(ConnexionComptable.dossier_id == d.id)
        ).scalars().first()
        sync = connexion.derniere_sync.strftime("%Y-%m-%d %H:%M") if connexion and connexion.derniere_sync else "jamais synchronisé"

        print(f"  {d.id}")
        print(f"    raison_sociale : {d.raison_sociale}")
        print(f"    organisation   : {orgs.get(d.organisation_id, '?')}")
        print(f"    secteur        : {d.secteur_activite or '—'}")
        print(f"    pièces / alertes actives : {nb_pieces} / {nb_alertes}")
        print(f"    dernière sync  : {sync}")
        print()


def supprimer_dossier(db, d: Dossier) -> None:
    """Supprime un dossier et tout ce qui en dépend, sans commit (appelant responsable)."""
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


def main():
    parser = argparse.ArgumentParser(description="Supprime des dossiers désignés explicitement par id.")
    parser.add_argument("--list", action="store_true", help="Liste tous les dossiers (id, organisation, nom, activité récente) puis quitte.")
    parser.add_argument("--ids", help="Id(s) de dossier à supprimer, séparés par des virgules (voir --list).")
    parser.add_argument("--confirm", action="store_true", help="Supprime réellement (sinon dry-run).")
    args = parser.parse_args()

    db = AdminSessionLocal()
    try:
        if args.list:
            lister(db)
            return

        if not args.ids:
            parser.error("précise --ids (voir --list pour les obtenir) ou --list seul.")

        brut = [s.strip() for s in args.ids.split(",") if s.strip()]
        ids: list[uuid.UUID] = []
        for s in brut:
            try:
                ids.append(uuid.UUID(s))
            except ValueError:
                print(f"Id invalide, ignoré : '{s}'")

        dossiers = db.execute(select(Dossier).where(Dossier.id.in_(ids))).scalars().all()
        trouves = {d.id for d in dossiers}
        introuvables = set(ids) - trouves
        if introuvables:
            print(f"Introuvable(s), ignoré(s) : {', '.join(str(i) for i in introuvables)}")
        if not dossiers:
            print("Aucun dossier correspondant à supprimer.")
            return

        orgs = {o.id: o.nom for o in db.execute(select(Organisation)).scalars().all()}
        print(f"{'Suppression' if args.confirm else 'À supprimer (dry-run)'} — {len(dossiers)} dossier(s) :")
        for d in dossiers:
            print(f"  - {d.raison_sociale} ({d.id}) — organisation « {orgs.get(d.organisation_id, '?')} »")

        if not args.confirm:
            print("\nDry-run — relancer avec --confirm pour supprimer réellement.")
            return

        for d in dossiers:
            supprimer_dossier(db, d)
        db.commit()
        print(f"\n{len(dossiers)} dossier(s) supprimé(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
