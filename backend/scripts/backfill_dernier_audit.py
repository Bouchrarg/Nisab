"""
backfill_dernier_audit.py — Rattrape dossier.dernier_audit_le pour les
dossiers audités AVANT la migration c9e1b3d6f204.

## Le trou que ce script corrige

La migration c9e1b3d6f204 a ajouté dossier.dernier_audit_le /
dernier_audit_hash SANS backfill (choix documenté dans la migration :
inventer une date aurait été pire que ne rien mettre). Conséquence
immédiate, mesurée en gérant un retour utilisateur : sur une base avec de
l'historique d'audit réel, TOUS les dossiers audités avant cette migration
s'affichent comme « jamais analysé », alors qu'ils ont des AlerteRisque et
des CitationRisque bien réels. Le correctif ne change pas de doctrine (on
n'invente toujours pas de date), il RÉCUPÈRE une date réelle déjà en base :

  MAX(citation_risque.created_at) par dossier, en priorité — les
  CitationRisque sont supprimées et RECRÉÉES à chaque run d'audit
  (_reecrire_citations, routes_dossiers.py), donc leur date reflète le
  DERNIER run, contrairement à AlerteRisque.created_at qui reste figé à la
  PREMIÈRE détection d'une alerte (cle_metier fait survivre id/statut aux
  runs suivants).

  À défaut (alertes actives sans citation, cas résiduel), repli sur
  MAX(alerte_risque.created_at) — moins précis (première détection, pas
  dernier run), mais toujours une date RÉELLE, jamais fabriquée.

`dernier_audit_hash` reste volontairement NULL après ce backfill : on ne
sait pas quelles données ont produit ce run passé, le prétendre serait
inventer. NULL fait afficher le dossier comme "analysé, résultat
possiblement périmé" (`resultat_perime=True` tant qu'aucun audit ne
retourne dessus) — honnête, jamais "jamais analysé" pour un dossier qui l'a
été.

Dry-run par défaut (même convention que cleanup_test_orgs.py) : affiche ce
qui serait mis à jour, --confirm pour écrire.

Usage (depuis backend/) :
    python -m scripts.backfill_dernier_audit
    python -m scripts.backfill_dernier_audit --confirm
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()
sys.path.insert(0, os.path.abspath("."))


def main(confirm: bool) -> int:
    engine = create_engine(os.environ["ADMIN_DATABASE_URL"])
    Session = sessionmaker(bind=engine)
    db = Session()

    # Priorité 1 : dernier run réel via les citations (voir docstring).
    rows_citations = db.execute(text("""
        SELECT ar.dossier_id, MAX(cr.created_at) AS derniere_date
        FROM citation_risque cr
        JOIN alerte_risque ar ON ar.id = cr.alerte_id
        WHERE ar.dossier_id NOT IN (SELECT id FROM dossier WHERE dernier_audit_le IS NOT NULL)
        GROUP BY ar.dossier_id
    """)).fetchall()

    couverts = {r.dossier_id for r in rows_citations}

    # Priorité 2 (repli) : dossiers avec des alertes mais aucune citation
    # (cas résiduel — ex. anomalies antérieures à c3e6a1b8d9f5).
    rows_alertes = db.execute(text("""
        SELECT dossier_id, MAX(created_at) AS derniere_date
        FROM alerte_risque
        WHERE dossier_id NOT IN (SELECT id FROM dossier WHERE dernier_audit_le IS NOT NULL)
        GROUP BY dossier_id
    """)).fetchall()

    a_backfiller = {r.dossier_id: (r.derniere_date, "citation_risque") for r in rows_citations}
    for r in rows_alertes:
        if r.dossier_id not in couverts:
            a_backfiller[r.dossier_id] = (r.derniere_date, "alerte_risque (repli, moins précis)")

    if not a_backfiller:
        print("Rien à backfiller — tous les dossiers avec historique ont déjà dernier_audit_le.")
        return 0

    print(f"{len(a_backfiller)} dossier(s) à corriger :\n")
    for dossier_id, (date, source) in a_backfiller.items():
        print(f"  {dossier_id}  ->  dernier_audit_le = {date}  (source : {source})")

    if not confirm:
        print("\nDry-run — relancez avec --confirm pour écrire.")
        return 0

    for dossier_id, (date, _source) in a_backfiller.items():
        db.execute(
            text("UPDATE dossier SET dernier_audit_le = :date WHERE id = :id"),
            {"date": date, "id": dossier_id},
        )
    db.commit()
    print(f"\n{len(a_backfiller)} dossier(s) mis à jour.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Écrit réellement (sinon dry-run)")
    args = parser.parse_args()
    sys.exit(main(args.confirm))
