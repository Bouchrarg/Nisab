"""
test_audit_lecture.py — L'audit ne se lance QUE si on le demande.

Script manuel (pas pytest), même convention que test_cle_metier.py.
Lancer depuis backend/ :  python test_audit_lecture.py

## Ce qu'on vérifie et pourquoi

L'audit partait tout seul dans six situations différentes (montage de l'app,
changement de dossier, changement de millésime dans le sélecteur, chargement
de données Odoo/CSV, vue d'ensemble du cabinet qui l'appelait une fois PAR
dossier, shell dirigeant). La cause profonde n'était pas côté frontend : c'est
`GET /dashboard/summary` qui appelait `_execute_audit`, donc n'importe quelle
LECTURE pouvait devenir un CALCUL de plusieurs minutes.

Ce script attrape les trois régressions qui rendraient le problème silencieux :

  1. lire un audit ne doit JAMAIS appeler le LLM (on remplace run_ai_rag_audit
     par une fonction qui lève : si elle est appelée, le test échoue) ;
  2. « jamais audité » et « audité, zéro anomalie » doivent rester deux états
     DISTINCTS — sinon l'écran affiche « bonne conformité » sur un dossier que
     personne n'a jamais analysé ;
  3. un dossier conforme (zéro anomalie) doit servir son cache — avant, sa
     liste d'alertes étant vide, la condition de cache était fausse et il
     relançait un audit complet à chaque consultation.

Aucune clé LLM n'est nécessaire : tous les appels au moteur sont remplacés.
"""

import os
import sys
import uuid

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()
sys.path.insert(0, os.path.abspath("."))

from app import routes_dossiers as rd
from app.models import AlerteRisque, CitationRisque, Dossier, Organisation, TypeOrganisation

engine = create_engine(os.environ["ADMIN_DATABASE_URL"])
Session = sessionmaker(bind=engine)

ok = True


def check(label, condition, detail=""):
    global ok
    print(("  OK   " if condition else "  ECHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        ok = False


def finding(piece, ref):
    return {
        "rule": f"ai_rag_{piece}",
        "status": "anomalie",
        "severity": "rouge",
        "reference_cgi": ref,
        "title": "TVA non déductible",
        "description": "Description de test.",
        "amount_risk": 1500.0,
        "categorie_montant": "calculable",
        "montant_detail": "Test : 1 500,00 DH.",
        "invoice": piece,
        "partner": "ZZ_TEST Fournisseur",
        "date": "2026-03-15",
        "recommendation": "Régulariser.",
        "rag_sources": [ref],
        "odoo_path": {"section": "Factures fournisseurs", "record_name": piece, "move_id": 4242,
                      "move_type": "in_invoice"},
    }


def interdit_llm(*_a, **_k):
    raise AssertionError("le LLM a été appelé sur un chemin qui doit être en LECTURE SEULE")


db = Session()
org = Organisation(id=uuid.uuid4(), nom="ZZ_TEST_audit_lecture", type_organisation=TypeOrganisation.cabinet)
dossier = Dossier(id=uuid.uuid4(), organisation_id=org.id, raison_sociale="ZZ_TEST Lecture", secteur_activite="test")
vierge = Dossier(id=uuid.uuid4(), organisation_id=org.id, raison_sociale="ZZ_TEST Vierge", secteur_activite="test")
db.add_all([org, dossier, vierge])
db.commit()
did, vid = dossier.id, vierge.id
print(f"\nDossiers de test : {did} (analysé) / {vid} (jamais analysé)\n")

DATA = {"moves": [1], "company": {"name": "ZZ_TEST"}, "partners": []}

try:
    rd.detecter = lambda data: []

    # ── 1. Dossier jamais audité ─────────────────────────────────────────
    print("1. Dossier jamais audité")
    rd.run_ai_rag_audit = interdit_llm
    lu = rd._lire_audit_persiste(db, vid, DATA)
    check("audit_status == 'jamais_lance'", lu["audit_status"] == "jamais_lance", lu["audit_status"])
    check("aucune date de dernier audit", lu["date_dernier_audit"] is None)
    check("aucun finding", lu["findings"] == [])
    # None et non False : sans audit de référence, on ne PEUT PAS savoir si le
    # résultat est périmé. Répondre False affirmerait qu'il est à jour.
    check("resultat_perime == None (indéterminé, pas False)", lu["resultat_perime"] is None, str(lu["resultat_perime"]))

    # ── 2. Un audit tourne, puis on relit ────────────────────────────────
    print("\n2. Après un audit avec 2 anomalies")
    rd.run_ai_rag_audit = lambda data, document_id=None: (
        [finding("FACT-001", "Article 106"), finding("FACT-002", "Article 193")], [], [])
    out, _, _ = rd._execute_audit(db, did, DATA, org.id, force=True)
    check("l'audit renvoie 2 findings", len(out) == 2, str(len(out)))

    rd.run_ai_rag_audit = interdit_llm
    lu = rd._lire_audit_persiste(db, did, DATA)
    check("la lecture n'appelle pas le LLM", True)  # atteint = interdit_llm n'a pas levé
    check("audit_status == 'done'", lu["audit_status"] == "done", lu["audit_status"])
    check("2 findings relus", len(lu["findings"]) == 2, str(len(lu["findings"])))
    check("date de dernier audit renseignée", lu["date_dernier_audit"] is not None)
    check("resultat_perime == False sur données inchangées", lu["resultat_perime"] is False, str(lu["resultat_perime"]))
    check(
        "la lecture renvoie la même forme que le chemin frais",
        set(lu["findings"][0]) == set(out[0]),
        str(set(lu["findings"][0]) ^ set(out[0])),
    )

    # ── 3. Les données changent : périmé, mais toujours pas de calcul ────
    print("\n3. Données comptables modifiées")
    lu = rd._lire_audit_persiste(db, did, {"moves": [1, 2], "company": {"name": "ZZ_TEST"}, "partners": []})
    check("resultat_perime == True", lu["resultat_perime"] is True, str(lu["resultat_perime"]))
    check("les findings précédents restent lisibles", len(lu["findings"]) == 2, str(len(lu["findings"])))
    check("audit_status reste 'done' (périmé n'est pas 'jamais lancé')", lu["audit_status"] == "done")

    # Changer de millésime périme aussi le résultat : le hash couvre le couple
    # (données, document_id). C'est ce qui rendait le cache inopérant quand
    # dashboard_summary appelait avec document_id=None.
    lu = rd._lire_audit_persiste(db, did, DATA, document_id="cgi_2024")
    check("changer de millésime périme le résultat", lu["resultat_perime"] is True, str(lu["resultat_perime"]))

    # ── 4. Dossier CONFORME : zéro anomalie != jamais audité ─────────────
    print("\n4. Dossier audité SANS anomalie (le cas qui cassait)")
    rd.run_ai_rag_audit = lambda data, document_id=None: ([], [], [])
    out, _, _ = rd._execute_audit(db, vid, DATA, org.id, force=True)
    check("l'audit renvoie 0 finding", out == [], str(out))
    n_lignes = db.query(AlerteRisque).filter(AlerteRisque.dossier_id == vid).count()
    check("aucune ligne d'alerte en base", n_lignes == 0, f"{n_lignes} ligne(s)")

    rd.run_ai_rag_audit = interdit_llm
    lu = rd._lire_audit_persiste(db, vid, DATA)
    check("audit_status == 'done', PAS 'jamais_lance'", lu["audit_status"] == "done", lu["audit_status"])
    check("date de dernier audit renseignée malgré 0 alerte", lu["date_dernier_audit"] is not None)

    # Le cache doit répondre alors qu'il n'existe aucune alerte : c'est
    # précisément ce que l'ancienne condition (`existing and all(...)`) ne
    # savait pas faire — un dossier parfaitement conforme relançait un audit
    # LLM complet à chaque consultation, sans que rien ne le montre à l'écran.
    out, _, _ = rd._execute_audit(db, vid, DATA, org.id, force=False)
    check("cache servi sans rappeler le LLM sur un dossier conforme", out == [], str(out))

    # ── 5. force=True passe outre le cache ──────────────────────────────
    print("\n5. force=True reste le seul moyen de recalculer")
    appels = {"n": 0}

    def compte(data, document_id=None):
        appels["n"] += 1
        return ([], [], [])

    rd.run_ai_rag_audit = compte
    rd._execute_audit(db, vid, DATA, org.id, force=True)
    check("force=True rappelle bien le moteur", appels["n"] == 1, f"{appels['n']} appel(s)")
    rd._execute_audit(db, vid, DATA, org.id, force=False)
    check("force=False ne le rappelle pas", appels["n"] == 1, f"{appels['n']} appel(s)")

finally:
    db.rollback()
    # Ordre imposé par les clés étrangères : les CitationRisque référencent
    # alerte_risque.id, il faut les retirer avant les alertes elles-mêmes.
    alerte_ids = [
        a.id for a in db.query(AlerteRisque).filter(AlerteRisque.dossier_id.in_([did, vid])).all()
    ]
    if alerte_ids:
        db.query(CitationRisque).filter(CitationRisque.alerte_id.in_(alerte_ids)).delete(synchronize_session=False)
    db.query(AlerteRisque).filter(AlerteRisque.dossier_id.in_([did, vid])).delete(synchronize_session=False)
    db.query(Dossier).filter(Dossier.id.in_([did, vid])).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()
    db.close()
    print("\nNettoyage effectué.")

print("\n" + ("TOUT EST VERT" if ok else "DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
