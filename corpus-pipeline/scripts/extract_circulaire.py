"""
extract_circulaire.py — Ingestion d'UNE note circulaire DGI dans corpus.db.

Appelé par `POST /admin/corpus/circulaires/upload` (backend/app/admin.py) via
subprocess, comme le reste du pipeline (pipeline_run, monitor_run,
monitor_cgi_run, ingest_run) — admin.py ne fait jamais d'import direct dans
corpus-pipeline, il l'invoque en sous-processus, cf. son en-tête.

## Pourquoi ce n'est PAS extract_corpus.py appliqué aux circulaires

extract_corpus.py découpe un PDF en articles via ARTICLE_PATTERN
("Article 12", "Article premier bis"...), une convention typographique du CGI
et du BO. Une note circulaire DGI n'a pas cette structure : c'est un texte
continu qui COMMENTE un ou plusieurs articles du CGI, sans porter lui-même de
numérotation d'article. Lui appliquer ARTICLE_PATTERN découperait le
commentaire n'importe où (ou pas du tout) — le mauvais outil pour ce document.

Une note circulaire devient donc UN SEUL article en base (tout son texte),
identifié par sa référence officielle (ex. "Note circulaire n° 728"), et
rattaché explicitement aux articles CGI qu'il commente via la colonne
`articles_cgi_commentes` (liste de références, séparées par ` | `).

## La règle d'autorité qu'exprime cette colonne

Une circulaire engage l'administration, pas le contribuable, et ne peut pas
contredire le CGI — elle ne doit donc jamais être citée SEULE : c'est ce que
`articles_cgi_commentes` rend vérifiable a posteriori (rag_retrieval.py filtre
tout hit NOTE_CIRCULAIRE dont le lot de résultats ne contient aucun des
articles CGI listés ici).

Usage :
    python extract_circulaire.py --pdf chemin/vers/fichier.pdf \\
        --document-id note_circulaire_728 --label "Note circulaire n° 728" \\
        --reference "Note circulaire n° 728" --date-version 2024-03-15 \\
        --articles-cgi-commentes "Article 145,Article 146"
"""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH
from extract_corpus import extract_pdf_text
from text_cleaning import clean_article_text

#: Séparateur des références dans articles_cgi_commentes. Un espace autour
#: du pipe pour rester lisible dans un export CSV/SQL direct (contrairement à
#: une simple virgule, jamais ambigu avec une référence qui en contiendrait une).
SEPARATEUR_REFERENCES = " | "


def ensure_schema(conn: sqlite3.Connection) -> None:
    """
    `articles.articles_cgi_commentes` n'existe pas dans le schéma historique
    (init_db.py) — ajoutée ici plutôt que dans init_db.py pour ne pas
    modifier un schéma déjà déployé par une simple relance de init_db.py.
    Idempotent : SQLite ne connaît pas `ADD COLUMN IF NOT EXISTS`, donc on
    tente et on avale l'erreur "duplicate column" si elle existe déjà.
    """
    try:
        conn.execute("ALTER TABLE articles ADD COLUMN articles_cgi_commentes TEXT")
        conn.commit()
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def normaliser_references(brut: str) -> list[str]:
    """'Article 145,  article146' -> ['Article 145', 'article146'] — la
    normalisation fine (casse, espaces) est déjà gérée côté RAG par
    ai_auditor._normalize_ref ; ici on ne fait que découper et nettoyer les
    espaces superflus de la saisie admin."""
    return [r.strip() for r in brut.split(",") if r.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, help="Chemin du PDF de la circulaire")
    parser.add_argument("--document-id", required=True, help='Ex: "note_circulaire_728"')
    parser.add_argument("--label", required=True, help='Ex: "Note circulaire n° 728"')
    parser.add_argument("--reference", required=True, help="Référence citée dans les réponses de l'assistant")
    parser.add_argument("--date-version", required=True, help="Date de PUBLICATION de la circulaire (YYYY-MM-DD)")
    parser.add_argument(
        "--articles-cgi-commentes", required=True,
        help="Références CGI commentées, séparées par des virgules (ex: 'Article 145,Article 146')",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"[ERROR] PDF introuvable : {pdf_path}")
        return 1

    references_cgi = normaliser_references(args.articles_cgi_commentes)
    if not references_cgi:
        # Non négociable : cf. la règle d'autorité en tête de fichier. Une
        # circulaire sans article CGI rattaché ne peut jamais être filtrée
        # correctement au retrieval, donc ne doit pas exister en base.
        print("[ERROR] --articles-cgi-commentes est vide : une circulaire doit toujours "
              "être rattachée à au moins un article CGI (cf. règle d'autorité, voir docstring).")
        return 1

    print(f"Extraction : {args.label}")
    texte = clean_article_text(extract_pdf_text(pdf_path)) or ""
    if len(texte.strip()) < 40:
        print(f"[ERROR] Texte extrait trop court ({len(texte)} caractères) — PDF illisible ou vide ?")
        return 1
    print(f"  {len(texte)} caractères extraits")

    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)

    now = datetime.now(timezone.utc).isoformat()

    # Idempotent comme process_document (extract_corpus.py) : un re-upload du
    # même document_id remplace plutôt que de dupliquer.
    conn.execute("DELETE FROM documents WHERE id=?", (args.document_id,))
    conn.execute("DELETE FROM articles WHERE document_id=?", (args.document_id,))
    conn.execute(
        """
        INSERT INTO documents (id, label, type, url, date_version, chemin_local, date_telechargement, statut)
        VALUES (?, ?, 'NOTE_CIRCULAIRE', ?, ?, ?, ?, 'extrait')
        """,
        (args.document_id, args.label, f"upload_admin://{pdf_path.name}", args.date_version, str(pdf_path), now),
    )
    conn.execute(
        """
        INSERT INTO articles
            (document_id, reference, texte, source_label, date_version, statut, date_extraction, articles_cgi_commentes)
        VALUES (?, ?, ?, ?, ?, 'a_verifier', ?, ?)
        """,
        (
            args.document_id, args.reference, texte, args.label, args.date_version, now,
            SEPARATEUR_REFERENCES.join(references_cgi),
        ),
    )
    conn.commit()
    conn.close()

    print(f"  1 article inséré (statut='a_verifier') — rattaché à : {', '.join(references_cgi)}")
    print("  À valider dans l'admin (relecture articles) avant qu'elle soit citable par l'assistant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
