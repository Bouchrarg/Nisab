"""
test_journal_acces.py — Vérifie `app.journal_acces.enregistrer_acces()`
(journal des accès CNDP, cf. models.py::JournalAcces).

Script manuel (pas pytest), même convention que les autres test_*.py. Tape la
vraie base (`DATABASE_URL`) : pas de RLS sur cette table (cf. models.py,
raison documentée), donc pas besoin de contexte tenant pour la lire/écrire —
mais on nettoie quand même en `finally`, sans exception.

Ce qu'on vérifie :
  1. Un accès complet (organisation + utilisateur connus) est bien inséré
     avec les bonnes valeurs.
  2. Un accès SANS jeton valide (organisation_id=None, utilisateur_id=None)
     s'insère aussi — c'est le cas d'usage qui justifie ces colonnes
     nullable (cf. JournalAcces, docstring).
  3. Une erreur DB ne remonte JAMAIS à l'appelant (best-effort) : on pointe
     temporairement `app.db.SessionLocal` vers un engine invalide et on
     vérifie que `enregistrer_acces` ne lève toujours pas.
"""
import io
import os
import sys
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath("."))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import journal_acces as ja_module
from app.db import SessionLocal
from app.models import JournalAcces, Organisation, RoleUtilisateur, TypeOrganisation, Utilisateur
from app.journal_acces import enregistrer_acces

ok = True


def check(label, condition, detail=""):
    global ok
    print(("  OK   " if condition else "  ECHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        ok = False


ENDPOINT_TEST_COMPLET = "ZZ_TEST_JOURNAL_ACCES_complet"
ENDPOINT_TEST_ANONYME = "ZZ_TEST_JOURNAL_ACCES_anonyme"

db = SessionLocal()
org = None
user = None
try:
    # `utilisateur_id`/`organisation_id` sont des FK réelles (contrainte
    # découverte en écrivant ce test, cf. migration 834f91da7e7e) — il faut
    # donc une organisation et un utilisateur réellement présents en base,
    # pas des UUID fictifs.
    org = Organisation(id=uuid.uuid4(), nom="ZZ_TEST_JOURNAL_ACCES_org", type_organisation=TypeOrganisation.cabinet)
    user = Utilisateur(
        id=uuid.uuid4(), organisation_id=org.id, email=f"zz_test_journal_acces_{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x", nom_complet="ZZ_TEST", role=RoleUtilisateur.admin_cabinet,
    )
    db.add_all([org, user])
    db.commit()

    # ── 1. Accès complet ──────────────────────────────────────────────────
    org_id = str(org.id)
    user_id = str(user.id)
    enregistrer_acces(org_id, user_id, ENDPOINT_TEST_COMPLET)

    ligne = db.execute(
        select(JournalAcces).where(JournalAcces.endpoint == ENDPOINT_TEST_COMPLET)
    ).scalars().first()
    check("accès complet inséré", ligne is not None)
    check("organisation_id correct", ligne is not None and str(ligne.organisation_id) == org_id)
    check("utilisateur_id correct", ligne is not None and str(ligne.utilisateur_id) == user_id)
    check("created_at renseigné", ligne is not None and ligne.created_at is not None)

    # ── 2. Accès anonyme (pas de jeton valide) ──────────────────────────
    enregistrer_acces(None, None, ENDPOINT_TEST_ANONYME)
    ligne_anon = db.execute(
        select(JournalAcces).where(JournalAcces.endpoint == ENDPOINT_TEST_ANONYME)
    ).scalars().first()
    check("accès anonyme inséré (organisation_id/utilisateur_id = None)", ligne_anon is not None)
    check("organisation_id = None accepté", ligne_anon is not None and ligne_anon.organisation_id is None)
    check("utilisateur_id = None accepté", ligne_anon is not None and ligne_anon.utilisateur_id is None)

    # ── 3. Best-effort : une erreur DB ne doit jamais remonter ───────────
    engine_invalide = create_engine("postgresql+psycopg://invalid:invalid@localhost:1/invalid")
    SessionInvalide = sessionmaker(bind=engine_invalide)
    ancien = ja_module.SessionLocal
    ja_module.SessionLocal = SessionInvalide
    try:
        enregistrer_acces("x", "y", "ZZ_TEST_JOURNAL_ACCES_erreur")
        check("enregistrer_acces() n'a pas levé malgré une base injoignable", True)
    except Exception as exc:
        check("enregistrer_acces() n'a pas levé malgré une base injoignable", False, str(exc))
    finally:
        ja_module.SessionLocal = ancien

finally:
    db.rollback()
    # Ordre imposé par les FK : les lignes journal_acces d'abord, puis
    # l'utilisateur, puis l'organisation.
    db.query(JournalAcces).filter(JournalAcces.endpoint.in_(
        [ENDPOINT_TEST_COMPLET, ENDPOINT_TEST_ANONYME, "ZZ_TEST_JOURNAL_ACCES_erreur"]
    )).delete(synchronize_session=False)
    if user is not None:
        db.query(Utilisateur).filter(Utilisateur.id == user.id).delete(synchronize_session=False)
    if org is not None:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()
    db.close()
    print("\nNettoyage effectué.")

print("\n" + ("TOUS LES TESTS PASSENT" if ok else "DES TESTS ONT ÉCHOUÉ"))
sys.exit(0 if ok else 1)
