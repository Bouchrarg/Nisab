import sqlite3
from config import DB_PATH, RAW_PDF_DIR, EXPORTS_DIR

SCHEMA = """
-- Documents sources (un PDF téléchargé = une ligne)
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,      -- ex: "cgi_2026"
    label           TEXT NOT NULL,
    type            TEXT NOT NULL,         -- 'CGI' | 'BULLETIN_OFFICIEL'
    url             TEXT NOT NULL,
    date_version    TEXT,
    chemin_local    TEXT,
    date_telechargement TEXT,
    statut          TEXT DEFAULT 'telecharge'  -- telecharge | extrait | erreur
);

-- Articles extraits et découpés (l'unité que le RAG va interroger)
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id),
    reference       TEXT NOT NULL,         -- ex: "Article 91-I-C-5°"
    texte           TEXT NOT NULL,
    source_label    TEXT NOT NULL,         -- libellé lisible de la source
    date_version    TEXT,
    statut          TEXT DEFAULT 'a_verifier', -- a_verifier | valide
    date_extraction TEXT
);

-- Journal du monitoring (chaque vérification, trouvée ou non)
CREATE TABLE IF NOT EXISTS veille_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_bo       TEXT NOT NULL,
    annee           INTEGER NOT NULL,
    url             TEXT NOT NULL,
    statut          TEXT NOT NULL,         -- nouveau | deja_connu | absent
    date_detection  TEXT NOT NULL
);
"""


def main():
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Base initialisée : {DB_PATH}")


if __name__ == "__main__":
    main()
