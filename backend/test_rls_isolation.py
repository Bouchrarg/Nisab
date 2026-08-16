"""
test_rls_isolation.py — Preuve automatisée de l'isolation multi-tenant RLS.

Script manuel (pas pytest), même convention que les autres test_*.py.
Vérifie la règle d'architecture n°1 du projet (CLAUDE.md : "Multi-tenant
strict : isolation par dossier_id / organisation_id via RLS") — jusqu'ici
jamais prouvée automatiquement : les scripts existants qui touchent
organisation_id (test_audit_lecture, test_cle_metier, test_veille)
n'instancient chacun qu'UNE SEULE organisation, donc ne peuvent pas détecter
une fuite croisée.

## ATTENTION — ce script tape la vraie base (il n'existe qu'un seul
## environnement DATABASE_URL dans ce projet, pas de base de test isolée)

Toutes les données créées ici sont préfixées `ZZ_TEST_RLS_` et nettoyées
INCONDITIONNELLEMENT en `finally`. Ne jamais retirer ce préfixe ni ce
nettoyage, et ne jamais lancer ce script contre un environnement contenant
de vrais cabinets clients.

## Ce qui est vérifié

1. Setup (via ADMIN_DATABASE_URL, rôle propriétaire des tables — Postgres
   n'applique jamais les policies RLS au propriétaire) : deux organisations
   A et B, chacune avec un dossier + une pièce comptable + une alerte +
   une citation.
2. Lecture croisée bloquée (via DATABASE_URL, rôle applicatif `nisab_app`,
   contexte tenant = org A) : dossier B, sa pièce, son alerte, sa citation
   (double jointure dossier -> alerte_risque -> citation_risque, la policy
   la plus indirecte du schéma) doivent être invisibles.
3. Écriture croisée bloquée — LE test qui manquait le plus : sous contexte
   org A, insérer une ligne rattachée à org B doit être rejeté par la
   policy WITH CHECK, pas seulement resté invisible en lecture. Testé sur
   `dossier` (policy directe) et `alerte_risque` (policy par sous-requête
   sur dossier_id) — les deux ont un WITH CHECK explicite dans la
   migration. `citation_risque` n'a volontairement PAS de WITH CHECK
   explicite dans la migration (834f91da7e7e) : par défaut Postgres réutilise
   alors la clause USING comme contrôle d'écriture, donc pas de trou de
   sécurité — mais ce n'est testé qu'en lecture ici, pas en écriture, pour
   rester sur les deux policies qui déclarent le WITH CHECK explicitement.
4. Symétrie A<->B : les mêmes vérifications tournent dans les deux sens —
   un bug directionnel dans une policy (ex. un test `<=` au lieu de `=`)
   pourrait passer inaperçu si on ne testait qu'un seul sens.
5. Non-régression du garde-fou DOCUMENTÉ (CLAUDE.md, migration
   834f91da7e7e) : `utilisateur` et `organisation` sont VOLONTAIREMENT sans
   RLS (le login doit pouvoir chercher un email avant de connaître le
   tenant). Sous contexte org A, la table `utilisateur` doit rester visible
   dans son intégralité, pas filtrée. Un échec ICI ne serait pas un
   renforcement de la sécurité : ce serait la preuve que quelqu'un a
   "corrigé" cette exclusion volontaire en pensant réparer un oubli, et
   cassé le login au passage.
6. Sanity check admin : via ADMIN_DATABASE_URL, les deux dossiers de test
   restent visibles simultanément (la voie admin_plateforme n'a pas été
   affectée par les policies).

## Point technique à connaître avant d'y toucher

Une violation RLS (WITH CHECK) avorte la transaction Postgres EN COURS :
toute requête suivante sur la même session échoue avec "current transaction
is aborted" tant qu'un db.rollback() n'a pas eu lieu. Le listener
`after_begin` (db_session.py) repose alors automatiquement
`app.current_org_id` sur la NOUVELLE transaction que SQLAlchemy ouvre après
le rollback — donc `db.rollback()` suffit à repartir proprement, pas besoin
de rappeler `set_tenant_context()`.

Si ce script échoue, la première hypothèse doit être une VRAIE régression
RLS (policy retirée ou modifiée par erreur sur une migration récente), pas
un test mal calibré.
"""
import os
import sys
import uuid

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

load_dotenv()
sys.path.insert(0, os.path.abspath("."))

from app.db_session import clear_tenant_context, set_tenant_context
from app.models import (
    AlerteRisque,
    CitationRisque,
    Dossier,
    NiveauRisque,
    Organisation,
    PieceComptable,
    TypeOrganisation,
    Utilisateur,
)

PREFIX = "ZZ_TEST_RLS_"

admin_engine = create_engine(os.environ["ADMIN_DATABASE_URL"])
AdminSession = sessionmaker(bind=admin_engine)
tenant_engine = create_engine(os.environ["DATABASE_URL"])
TenantSession = sessionmaker(bind=tenant_engine)

ok = True


def check(label, condition, detail=""):
    global ok
    print(("  OK   " if condition else "  ECHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        ok = False


admin_db = AdminSession()
tenant_db = None
orgs: dict[str, Organisation] = {}
dossiers: dict[str, Dossier] = {}
alertes: dict[str, AlerteRisque] = {}
citations: dict[str, CitationRisque] = {}

try:
    # ── 1. Setup (bypass RLS, rôle propriétaire) ─────────────────────────
    for tag in ("A", "B"):
        org = Organisation(id=uuid.uuid4(), nom=f"{PREFIX}ORG_{tag}", type_organisation=TypeOrganisation.cabinet)
        dossier = Dossier(
            id=uuid.uuid4(), organisation_id=org.id,
            raison_sociale=f"{PREFIX}DOSSIER_{tag}", secteur_activite="test",
        )
        admin_db.add_all([org, dossier])
        admin_db.flush()

        piece = PieceComptable(
            id=uuid.uuid4(), dossier_id=dossier.id, source="csv", type_piece="facture",
            donnees_json={"test": tag},
        )
        alerte = AlerteRisque(
            id=uuid.uuid4(), dossier_id=dossier.id, titre=f"{PREFIX}ALERTE_{tag}",
            niveau_risque=NiveauRisque.eleve, cle_metier=f"{PREFIX}PIECE_{tag}|article 11",
        )
        admin_db.add_all([piece, alerte])
        admin_db.flush()

        citation = CitationRisque(id=uuid.uuid4(), alerte_id=alerte.id, article_reference="Article 11")
        admin_db.add(citation)
        admin_db.flush()

        orgs[tag], dossiers[tag], alertes[tag], citations[tag] = org, dossier, alerte, citation

    admin_db.commit()
    print(f"Setup : org A={orgs['A'].id}, org B={orgs['B'].id}\n")

    # ── 2/3/4. Lecture et écriture croisées, dans les deux sens ──────────
    tenant_db = TenantSession()
    for me, other in (("A", "B"), ("B", "A")):
        print(f"== Contexte org {me} (ne doit voir/écrire QUE {me}) ==")
        set_tenant_context(tenant_db, str(orgs[me].id))

        check(f"dossier {other} invisible depuis {me}",
              tenant_db.get(Dossier, dossiers[other].id) is None)

        pieces_autre = tenant_db.execute(
            select(PieceComptable).where(PieceComptable.dossier_id == dossiers[other].id)
        ).scalars().all()
        check(f"pièce comptable {other} invisible depuis {me}", pieces_autre == [])

        check(f"alerte {other} invisible depuis {me}",
              tenant_db.get(AlerteRisque, alertes[other].id) is None)

        # Double jointure — dossier -> alerte_risque -> citation_risque.
        check(f"citation (double jointure) {other} invisible depuis {me}",
              tenant_db.get(CitationRisque, citations[other].id) is None)

        # Mes propres données restent bien lisibles (l'isolation ne doit
        # pas non plus bloquer par excès).
        check(f"dossier {me} bien visible depuis {me}",
              tenant_db.get(Dossier, dossiers[me].id) is not None)

        # ── Écriture croisée : doit être REJETÉE, pas juste invisible ────
        faux_dossier = Dossier(
            id=uuid.uuid4(), organisation_id=orgs[other].id,
            raison_sociale=f"{PREFIX}INTRUSION_{me}_vers_{other}", secteur_activite="test",
        )
        tenant_db.add(faux_dossier)
        try:
            tenant_db.flush()
            check(f"INSERT dossier pour {other} depuis contexte {me} -> rejeté par la policy", False,
                  "l'insertion a réussi : la policy WITH CHECK n'a pas bloqué")
        except DBAPIError:
            check(f"INSERT dossier pour {other} depuis contexte {me} -> rejeté par la policy", True)
        finally:
            tenant_db.rollback()  # after_begin (db_session.py) repose le contexte tenant

        faux_alerte = AlerteRisque(
            id=uuid.uuid4(), dossier_id=dossiers[other].id, titre=f"{PREFIX}INTRUSION_ALERTE",
            niveau_risque=NiveauRisque.eleve,
        )
        tenant_db.add(faux_alerte)
        try:
            tenant_db.flush()
            check(f"INSERT alerte sur dossier {other} depuis contexte {me} -> rejeté par la policy", False,
                  "l'insertion a réussi : la policy WITH CHECK n'a pas bloqué")
        except DBAPIError:
            check(f"INSERT alerte sur dossier {other} depuis contexte {me} -> rejeté par la policy", True)
        finally:
            tenant_db.rollback()

        print()

    # ── 5. Non-régression : utilisateur/organisation restent SANS RLS ────
    print("== Garde-fou : utilisateur reste visible cross-tenant (voulu, pas un oubli) ==")
    set_tenant_context(tenant_db, str(orgs["A"].id))
    total_tenant = tenant_db.execute(select(Utilisateur)).scalars().all()
    total_admin = admin_db.execute(select(Utilisateur)).scalars().all()
    check(
        "utilisateur non filtré par RLS (même total vu sous contexte org A que via l'admin)",
        len(total_tenant) == len(total_admin), f"{len(total_tenant)} vs {len(total_admin)}",
    )
    clear_tenant_context(tenant_db)

    # ── 6. Sanity check admin : les deux dossiers restent visibles ───────
    print("\n== Sanity check : la voie admin_plateforme voit toujours les deux organisations ==")
    admin_dossiers = admin_db.execute(
        select(Dossier).where(Dossier.id.in_([dossiers["A"].id, dossiers["B"].id]))
    ).scalars().all()
    check("les 2 dossiers de test visibles via ADMIN_DATABASE_URL", len(admin_dossiers) == 2, len(admin_dossiers))

finally:
    if tenant_db is not None:
        tenant_db.rollback()
        tenant_db.close()

    # Nettoyage inconditionnel, même ordre de dépendances FK que
    # scripts/cleanup_test_orgs.py : citations -> alertes -> pièces ->
    # dossiers -> organisations.
    admin_db.rollback()
    for tag in ("A", "B"):
        dossier = dossiers.get(tag)
        if dossier is None:
            continue
        alerte_ids = [a.id for a in admin_db.execute(
            select(AlerteRisque).where(AlerteRisque.dossier_id == dossier.id)
        ).scalars()]
        if alerte_ids:
            admin_db.query(CitationRisque).filter(CitationRisque.alerte_id.in_(alerte_ids)).delete(synchronize_session=False)
        admin_db.query(AlerteRisque).filter(AlerteRisque.dossier_id == dossier.id).delete(synchronize_session=False)
        admin_db.query(PieceComptable).filter(PieceComptable.dossier_id == dossier.id).delete(synchronize_session=False)
        admin_db.query(Dossier).filter(Dossier.id == dossier.id).delete(synchronize_session=False)
    for tag in ("A", "B"):
        org = orgs.get(tag)
        if org is not None:
            admin_db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    admin_db.commit()
    admin_db.close()
    print("\nNettoyage effectué.")

print("\n" + ("TOUS LES TESTS PASSENT" if ok else "DES TESTS ONT ÉCHOUÉ — RÉGRESSION RLS PROBABLE"))
sys.exit(0 if ok else 1)
