"""
check_detection_reglee.py — Diagnostic EN LECTURE SEULE : que produirait la
détection réglée (`app.detection_reglee`) sur les vraies données comptables
d'un dossier ?

Aucune écriture : ni en base applicative, ni dans Odoo. Le script se contente
d'appeler `fetch_accounting_data()` puis `detecter()` et d'afficher le
résultat. Même genre que `check_odoo18.py`, et à lancer pour la même raison :
vérifier ce qu'il y a AVANT de se demander pourquoi l'écran est vide.

## À quoi il répond

L'audit peut n'afficher aucun montant pour deux raisons opposées, qu'on ne
distingue pas depuis l'interface :

  - il n'y a réellement rien à chiffrer dans les données (bon résultat) ;
  - il y a de quoi chiffrer, mais le signal ne remonte pas — typiquement le
    caractère "réglé en espèces", qui n'existe dans AUCUN champ standard
    d'`account.move.line` (voir detection_reglee.est_regle_en_especes).

Le script affiche les deux : combien d'écritures sont identifiées comme
réglées en espèces et par quel signal, puis les alertes chiffrables qui en
découlent.

## Usage (depuis backend/)

    python -m scripts.check_detection_reglee

Réutilise les identifiants Odoo chiffrés en base, comme le fait
`routes_corrections.pousser_proposition`. Si aucun n'est mémorisé, le script
le dit : c'est aussi ce qui empêcherait de pousser un brouillon de correction.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

from app.detection_reglee import _lignes_du_move, detecter, est_regle_en_especes
from app.odoo_connector import OdooConnector
from app.secrets_store import cle_disponible, dechiffrer


def main() -> int:
    if not cle_disponible():
        print("NISAB_SECRET_KEY absente de l'environnement : impossible de relire les "
              "identifiants Odoo chiffrés.")
        return 1

    url = os.environ.get("ADMIN_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("ADMIN_DATABASE_URL / DATABASE_URL manquant dans .env")
        return 1
    sqla = url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url

    with create_engine(sqla, future=True).connect() as conn:
        connexions = conn.execute(text("""
            SELECT d.raison_sociale, c.identifiants_chiffres
            FROM connexion_comptable c
            JOIN dossier d ON d.id = c.dossier_id
            WHERE c.type = 'odoo' AND c.identifiants_chiffres IS NOT NULL
            ORDER BY d.raison_sociale
        """)).fetchall()

    if not connexions:
        print("Aucun dossier n'a d'identifiants Odoo mémorisés.\n")
        print("Conséquence directe : POST /dossiers/{id}/propositions/{id}/pousser répondra 400")
        print("pour tous les dossiers — il n'y a rien à déchiffrer pour se connecter à Odoo.")
        print("\nPour corriger : page Odoo de l'application, se reconnecter en cochant")
        print("« Mémoriser les identifiants (chiffrés) », puis relancer ce script.")
        return 1

    for nom, chiffre in connexions:
        print("=" * 78)
        print(f"Dossier : {nom}")
        print("=" * 78)

        identifiants = dechiffrer(chiffre)
        connecteur = OdooConnector(
            url=identifiants["url"], db=identifiants["db"],
            username=identifiants["username"], password=identifiants["password"],
        )
        connecteur.authenticate()
        data = connecteur.fetch_accounting_data()

        moves = data.get("moves", [])
        lignes = data.get("lines", [])
        societe = (data.get("company") or {}).get("name")
        print(f"  société auditée : {societe} (id={data.get('company_id')})")
        print(f"  {len(moves)} écriture(s), {len(lignes)} ligne(s)")

        par_type: dict[str | None, int] = {}
        for m in moves:
            par_type[m.get("journal_type")] = par_type.get(m.get("journal_type"), 0) + 1
        print(f"  écritures par type de journal : {par_type}")

        especes = []
        for m in moves:
            detecte, origine = est_regle_en_especes(m, _lignes_du_move(m, lignes))
            if detecte:
                especes.append((m.get("name"), m.get("move_type"), m.get("date"), origine))

        print(f"\n  {len(especes)} écriture(s) identifiée(s) comme réglée(s) en espèces :")
        for piece, move_type, date_piece, origine in especes[:20]:
            print(f"    - {piece} ({move_type}, {date_piece}) — signal : {origine}")
        if not especes:
            print("    (aucune — l'Art. 11-II ne peut donc rien chiffrer sur ce dossier)")

        findings = detecter(data)
        print(f"\n  >>> {len(findings)} alerte(s) chiffrable(s) produite(s) par la détection réglée :")
        for f in findings:
            print(f"    - {f['invoice']:20} {f['reference_cgi']:12} "
                  f"{f['amount_risk']:>12,.2f} DH   ({f['categorie_montant']})")
        if not findings:
            print("    (aucune)")
            print("\n    Ce n'est pas nécessairement un bug : si la base ne contient aucun")
            print("    règlement en espèces, aucun véhicule de tourisme au-delà de 400 000 DH")
            print("    et aucune TVA déduite sur catégorie exclue, il n'y a rien à chiffrer.")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
