import os
import sys
import uuid

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()
sys.path.insert(0, os.path.abspath("."))

from app import routes_dossiers as rd
from app.models import AlerteRisque, CitationRisque, Dossier, Organisation, StatutAlerte, TypeOrganisation

engine = create_engine(os.environ["ADMIN_DATABASE_URL"])
Session = sessionmaker(bind=engine)

ok = True


def check(label, condition, detail=""):
    global ok
    print(("  OK   " if condition else "  ECHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        ok = False


def finding(piece, ref, severity="rouge", montant=1500.0, titre="TVA non déductible"):
    return {
        "rule": f"ai_rag_{piece}",
        "status": "anomalie",
        "severity": severity,
        "reference_cgi": ref,
        "title": titre,
        "description": "Description de test.",
        "amount_risk": montant,
        "invoice": piece,
        "partner": "Fournisseur Test SARL",
        "date": "2026-03-14",
        "recommendation": "Régulariser la déduction.",
        # ref + une seconde source distincte -> 2 CitationRisque attendues
        "rag_sources": [ref, "Article 105"],
        "odoo_path": {"section": "Factures fournisseurs", "record_name": piece, "move_id": 4242, "move_type": "in_invoice"},
    }


db = Session()
org = Organisation(id=uuid.uuid4(), nom="ZZ_TEST_cle_metier", type_organisation=TypeOrganisation.cabinet)
dossier = Dossier(id=uuid.uuid4(), organisation_id=org.id, raison_sociale="ZZ_TEST Dossier", secteur_activite="test")
db.add(org)
db.add(dossier)
db.commit()
did = dossier.id
print(f"\nDossier de test : {did}\n")

try:
    # La détection réglée est neutralisée par défaut : ce script vérifie la
    # réconciliation par clé métier, pas les règles. Elle est réactivée
    # explicitement dans le dernier bloc, pour le seul cas où les deux
    # sources se disputent la même clé.
    rd.detecter = lambda data: []

    # ── Run 1 : deux anomalies ───────────────────────────────────────────
    rd.run_ai_rag_audit = lambda data, document_id=None: (
        [finding("FACT-001", "Article 106"), finding("FACT-002", "Article 193")], [], [])
    out1, _, _ = rd._execute_audit(db, did, {"moves": [1]}, org.id, force=True)
    check("run 1 renvoie 2 findings", len(out1) == 2, f"{len(out1)}")
    id_fact1 = next(f["id"] for f in out1 if f["invoice"] == "FACT-001")
    check("cle_metier lisible", out1[0]["cle_metier"].count("|") == 1, out1[0]["cle_metier"])
    check("contexte présent (chemin frais)", all(out1[0].get(k) for k in ("invoice", "partner", "date", "recommendation", "odoo_path")))

    # ── Le collaborateur classe FACT-001 comme traitée ───────────────────
    a = db.get(AlerteRisque, uuid.UUID(id_fact1))
    a.statut = StatutAlerte.traitee
    db.commit()

    # ── Run 2 : mêmes données -> id ET statut doivent survivre ───────────
    out2, _, _ = rd._execute_audit(db, did, {"moves": [1]}, org.id, force=True)
    id_fact1_apres = next(f["id"] for f in out2 if f["invoice"] == "FACT-001")
    check("id stable après ré-audit", id_fact1_apres == id_fact1, f"{id_fact1[:8]} -> {id_fact1_apres[:8]}")
    db.expire_all()
    check("statut 'traitee' préservé", db.get(AlerteRisque, uuid.UUID(id_fact1)).statut == StatutAlerte.traitee)
    check("pas de doublon", db.query(AlerteRisque).filter(AlerteRisque.dossier_id == did).count() == 2)

    # ── Run 3 : FACT-002 disparaît des données ──────────────────────────
    rd.run_ai_rag_audit = lambda data, document_id=None: ([finding("FACT-001", "Article 106")], [], [])
    out3, _, _ = rd._execute_audit(db, did, {"moves": [2]}, org.id, force=True)
    check("run 3 ne renvoie que l'anomalie encore détectée", len(out3) == 1, f"{len(out3)}")
    db.expire_all()
    total = db.query(AlerteRisque).filter(AlerteRisque.dossier_id == did).count()
    inactives = db.query(AlerteRisque).filter(AlerteRisque.dossier_id == did, AlerteRisque.actif.is_(False)).count()
    check("aucune ligne supprimée", total == 2, f"{total} lignes")
    check("l'anomalie disparue est désactivée", inactives == 1, f"{inactives} inactive(s)")

    # ── Chemin de cache : même forme que le chemin frais ─────────────────
    rd.run_ai_rag_audit = lambda data, document_id=None: (_ for _ in ()).throw(AssertionError("le LLM ne doit PAS être rappelé"))
    out4, _, _ = rd._execute_audit(db, did, {"moves": [2]}, org.id, force=False)
    check("cache réutilisé sans rappeler le LLM", len(out4) == 1)
    check("cache renvoie la même forme que le chemin frais", set(out4[0]) == set(out3[0]), str(set(out3[0]) ^ set(out4[0])))
    check("contexte présent (chemin cache)", all(out4[0].get(k) for k in ("invoice", "partner", "date", "recommendation", "odoo_path")))

    # ── Citations réécrites, pas accumulées ─────────────────────────────
    n_cit = db.query(CitationRisque).filter(CitationRisque.alerte_id == uuid.UUID(id_fact1)).count()
    check("citations non dupliquées après 3 runs", n_cit == 2, f"{n_cit} citations pour 2 refs distinctes")

    # ── Collision RAG / détection réglée sur la MÊME clé métier ─────────
    # Les deux sources peuvent décrire le même fait : le LLM sans montant
    # chiffrable, la règle avec le calcul. La déduplication doit garder le
    # montant, même si le finding RAG est plus "grave" — sinon on
    # réintroduirait par la déduplication le symptôme que la détection
    # réglée existe pour corriger (voir routes_dossiers._remplace).
    rag_sans_montant = finding("FACT-003", "Article 11", severity="rouge", montant=None)
    rag_sans_montant["categorie_montant"] = "non_calculable"
    regle_chiffree = finding("FACT-003", "Article 11", severity="orange", montant=15000.0)
    regle_chiffree["categorie_montant"] = "calculable_hypothese"
    regle_chiffree["rule"] = "regle_article_11_4242"

    rd.run_ai_rag_audit = lambda data, document_id=None: ([rag_sans_montant], [], [])
    rd.detecter = lambda data: [regle_chiffree]
    out5, _, _ = rd._execute_audit(db, did, {"moves": [3]}, org.id, force=True)

    fact3 = [f for f in out5 if f["invoice"] == "FACT-003"]
    check("une seule alerte pour (FACT-003, Article 11)", len(fact3) == 1, f"{len(fact3)}")
    check("c'est la version CHIFFRÉE qui est retenue, pas la plus grave",
          fact3 and fact3[0]["amount_risk"] == 15000.0, fact3 and fact3[0]["amount_risk"])
    check("la catégorie de montant suit",
          fact3 and fact3[0]["categorie_montant"] == "calculable_hypothese")

    # Deux articles distincts sur la MÊME pièce doivent coexister : c'est tout
    # l'intérêt d'une clé "{pièce}|{article}".
    rd.run_ai_rag_audit = lambda data, document_id=None: ([finding("FACT-004", "Article 146", montant=None)], [], [])
    rd.detecter = lambda data: [finding("FACT-004", "Article 11", severity="orange", montant=9000.0)]
    out6, _, _ = rd._execute_audit(db, did, {"moves": [4]}, org.id, force=True)
    fact4 = sorted(f["reference_cgi"] for f in out6 if f["invoice"] == "FACT-004")
    check("une pièce peut porter 2 alertes sur 2 articles différents",
          fact4 == ["Article 11", "Article 146"], str(fact4))

finally:
    db.execute(text("DELETE FROM citation_risque WHERE alerte_id IN (SELECT id FROM alerte_risque WHERE dossier_id = :d)"), {"d": did})
    db.execute(text("DELETE FROM alerte_risque WHERE dossier_id = :d"), {"d": did})
    db.execute(text("DELETE FROM dossier WHERE id = :d"), {"d": did})
    db.execute(text("DELETE FROM organisation WHERE id = :o"), {"o": org.id})
    db.commit()
    db.close()
    print("\nDonnées de test nettoyées.")

print("\n=> " + ("TOUT PASSE" if ok else "DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
