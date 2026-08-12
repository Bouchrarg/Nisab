"""
test_qualification_bo.py — date_version d'un BO fraîchement détecté n'est
plus la date de détection, et peut être confirmée après coup (Lot 2.3).

Script manuel (pas pytest), même convention que test_langue.py.
Lancer depuis backend/ :  python test_qualification_bo.py

## Ce qu'on vérifie

1. `veille._version_precedente` / `_existe_version_plus_recente` traitent
   déjà NULL comme « pas de version comparable » — condition nécessaire au
   correctif de monitor_bo.py, vérifiée ici pour ne pas la supposer par cœur.
2. `admin.qualifier_document` : refuse un CGI (règle d'architecture — les
   millésimes CGI coexistent, ne sont jamais marqués "remplacés"), refuse un
   appel sans rien à modifier, accepte de poser `date_version` et/ou
   `statut_juridique` sur un document existant, rejette une date malformée.
3. `_ensure_documents_columns` est idempotente (deux appels de suite ne
   lèvent pas).

Utilise une base SQLite temporaire, jamais le corpus.db réel.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.abspath("."))

from app import admin
from app import veille

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


print("\n-- 1. veille.py traite déjà NULL date_version comme non comparable --")
tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
conn = sqlite3.connect(tmp_db.name)
conn.executescript("""
CREATE TABLE documents (id TEXT PRIMARY KEY, label TEXT, type TEXT, statut TEXT, date_version TEXT, statut_juridique TEXT);
CREATE TABLE articles (id INTEGER PRIMARY KEY, document_id TEXT, reference TEXT, texte TEXT, statut TEXT, date_version TEXT);
INSERT INTO documents VALUES ('bo_ancien', 'BO ancien', 'BULLETIN_OFFICIEL', 'extrait', '2024-01-01', NULL);
INSERT INTO articles VALUES (1, 'bo_ancien', 'Article 2', 'texte ancien', 'valide', '2024-01-01');
""")
conn.commit()
conn.close()

conn = sqlite3.connect(tmp_db.name)
prec = veille._version_precedente(conn, "Article 2", "bo_nouveau", "BULLETIN_OFFICIEL", None)
check("date_version=None -> pas de comparaison (retourne None)", prec is None, str(prec))
plus_recente = veille._existe_version_plus_recente(conn, "Article 2", "bo_nouveau", "BULLETIN_OFFICIEL", None)
check("date_version=None -> pas de comparaison (retourne False)", plus_recente is False, str(plus_recente))
conn.close()
os.unlink(tmp_db.name)

print("\n-- 2. admin.qualifier_document --")
tmp_db2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db2.close()
admin._corpus_db_path = lambda: tmp_db2.name  # redirige la route vers la base de test
conn = sqlite3.connect(tmp_db2.name)
conn.executescript("""
CREATE TABLE documents (id TEXT PRIMARY KEY, label TEXT, type TEXT, statut TEXT, date_version TEXT, chemin_local TEXT, date_telechargement TEXT);
CREATE TABLE articles (id INTEGER PRIMARY KEY, document_id TEXT, reference TEXT, texte TEXT, statut TEXT, date_version TEXT);
INSERT INTO documents (id, label, type, statut, date_version) VALUES
    ('bo_test', 'BO test', 'BULLETIN_OFFICIEL', 'a_qualifier', NULL),
    ('cgi_test', 'CGI test', 'CGI', 'extrait', '2026-01-01');
""")
conn.commit()
conn.close()

try:
    admin.qualifier_document("cgi_test", admin.DocumentQualificationRequest(date_version="2026-06-01"))
    check("un document CGI est refusé", False)
except Exception as exc:
    check("un document CGI est refusé", getattr(exc, "status_code", None) == 400, str(exc))

try:
    admin.qualifier_document("bo_test", admin.DocumentQualificationRequest())
    check("appel sans rien à modifier est refusé", False)
except Exception as exc:
    check("appel sans rien à modifier est refusé", getattr(exc, "status_code", None) == 400)

try:
    admin.qualifier_document("bo_test", admin.DocumentQualificationRequest(date_version="pas-une-date"))
    check("date malformée refusée", False)
except Exception as exc:
    check("date malformée refusée", getattr(exc, "status_code", None) == 400)

resultat = admin.qualifier_document(
    "bo_test", admin.DocumentQualificationRequest(date_version="2025-12-16", statut_juridique="en_vigueur")
)
check("date_version confirmée", resultat["date_version"] == "2025-12-16", resultat["date_version"])
check("statut_juridique posé", resultat["statut_juridique"] == "en_vigueur", resultat["statut_juridique"])

resultat2 = admin.qualifier_document("bo_test", admin.DocumentQualificationRequest(statut_juridique="remplacee_par:bo_suivant"))
check("statut_juridique seul modifiable sans re-fournir date_version", resultat2["statut_juridique"] == "remplacee_par:bo_suivant")
check("date_version précédente préservée", resultat2["date_version"] == "2025-12-16", resultat2["date_version"])

os.unlink(tmp_db2.name)

print("\n-- 3. _ensure_documents_columns est idempotente --")
tmp_db3 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db3.close()
conn = sqlite3.connect(tmp_db3.name)
conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, label TEXT, type TEXT, statut TEXT, date_version TEXT)")
conn.commit()
try:
    admin._ensure_documents_columns(conn)
    admin._ensure_documents_columns(conn)
    check("deux appels de suite ne lèvent pas", True)
except Exception as exc:
    check("deux appels de suite ne lèvent pas", False, str(exc))
conn.close()
os.unlink(tmp_db3.name)

print("\n" + ("TOUT EST VERT" if ok else "DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
