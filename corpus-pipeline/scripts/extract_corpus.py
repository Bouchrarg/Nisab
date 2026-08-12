import csv
import re
import sqlite3
from datetime import datetime, timezone
from typing import List, Tuple

import pdfplumber

from config import DB_PATH, RAW_PDF_DIR, EXPORTS_DIR
from text_cleaning import clean_article_text

ARTICLE_PATTERN = re.compile(
    r"(?m)^\s*(Article\s+(?:premier|\d+)"
    r"(?:\s*(?:bis|ter|quater|quinquies|sexies|septies|octies))?"
    r"(?:[ \t\-]*(?:[IVXLC]+|[A-Z]|\d+°))*)"
    r"\s*(?:[\.\-–]|$)"
)

# Longueur minimale d'un texte d'article pour être considéré comme substantiel
# (un article très court est plus probablement un fragment de renvoi/note de bas
# de page qu'un vrai article de fond).
MIN_SUBSTANTIAL_LENGTH = 80


def ensure_conflict_table(conn: sqlite3.Connection) -> None:
    """
    Table séparée pour les références d'article qui apparaissent plusieurs fois
    dans un même document PDF (corps principal + annexes/arrêtés/lois rectificatives
    imprimés à la suite). On ne les insère jamais dans `articles` sans passage ici,
    pour éviter qu'un contenu d'annexe soit indexé sous le numéro d'un article du
    corps législatif principal (bug identifié : "Article 3" contenant un extrait
    d'abrogation d'une loi de finances rectificative plutôt que le vrai article 3).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles_conflits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            reference TEXT NOT NULL,
            occurrence_index INTEGER NOT NULL,
            texte TEXT NOT NULL,
            longueur INTEGER NOT NULL,
            retenu INTEGER NOT NULL DEFAULT 0,
            date_extraction TEXT NOT NULL
        )
        """
    )
    conn.commit()


def validate_chunk(reference: str, texte: str) -> List[str]:
    """Retourne une liste de signaux d'alerte pour un chunk douteux."""
    issues: List[str] = []
    if not reference or reference.startswith("À"):
        issues.append("reference_manquante_ou_fallback")
    if len((texte or "").strip()) < 40 and "Article" not in (texte or ""):
        issues.append("texte_trop_court")
    if reference == "À DÉCOUPER MANUELLEMENT":
        issues.append("fallback_manuel")
    return issues


def extract_pdf_text(pdf_path) -> str:
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
    return "\n".join(pages_text)


def split_by_article(full_text: str):
    """
    Retourne une liste de (reference, texte) pour chaque occurrence détectée,
    SANS déduplication — la déduplication est déléguée à resolve_duplicates(),
    pour que la logique de choix (quelle occurrence garder) soit isolée et
    testable indépendamment du parsing brut.
    """
    matches = list(ARTICLE_PATTERN.finditer(full_text))
    if not matches:
        return []

    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        reference = m.group(1).strip()
        texte = clean_article_text(full_text[start:end].strip())
        issues = validate_chunk(reference, texte)
        if issues:
            print(f"    [WARNING] {reference}: {', '.join(issues)}")
        # Filtre les faux positifs manifestes (bloc trop court = probable bruit)
        if len(texte) < 20:
            continue
        chunks.append((reference, texte))
    return chunks


def resolve_duplicates(
    chunks: List[Tuple[str, str]]
) -> Tuple[List[Tuple[str, str]], List[dict]]:
    """
    Sépare les références qui apparaissent une seule fois (cas normal, insérées
    directement dans `articles`) des références dupliquées (routées vers
    `articles_conflits` pour revue manuelle, avec une occurrence marquée comme
    "retenue" par défaut selon une heuristique simple, à valider par un humain).

    Heuristique de choix par défaut pour l'occurrence retenue : la PREMIÈRE
    occurrence dans le document. Dans un CGI, le corps législatif principal est
    imprimé avant les annexes, arrêtés d'application et extraits de lois de
    finances rectificatives — donc la première occurrence d'un numéro donné est
    la plus susceptible d'être le vrai article du corps principal. Ce n'est PAS
    une garantie absolue : c'est une heuristique de départ, à confirmer via le
    CSV de relecture (colonne `retenu` dans articles_conflits).
    """
    by_reference: dict[str, list[Tuple[str, str]]] = {}
    for reference, texte in chunks:
        by_reference.setdefault(reference, []).append((reference, texte))

    clean_chunks: List[Tuple[str, str]] = []
    conflicts: List[dict] = []

    for reference, occurrences in by_reference.items():
        if len(occurrences) == 1:
            clean_chunks.append(occurrences[0])
            continue

        # Référence dupliquée : ne va PAS dans `articles` automatiquement.
        # On journalise toutes les occurrences avec l'heuristique "première
        # occurrence retenue par défaut", pour revue manuelle via le CSV.
        print(f"    [CONFLIT] {reference} apparaît {len(occurrences)} fois — "
              f"routé vers articles_conflits, revue manuelle nécessaire")
        for idx, (ref, texte) in enumerate(occurrences):
            conflicts.append({
                "reference": ref,
                "occurrence_index": idx,
                "texte": texte,
                "longueur": len(texte),
                "retenu": 1 if idx == 0 else 0,
            })

        # Par défaut, on insère quand même la première occurrence dans `articles`
        # avec le statut 'a_verifier' habituel (pas de régression de couverture),
        # mais elle est aussi tracée dans articles_conflits pour audit.
        clean_chunks.append(occurrences[0])

    return clean_chunks, conflicts


def get_documents_to_extract(conn: sqlite3.Connection):
    """Documents avec PDF local — config initiale + veille BO/CGI."""
    rows = conn.execute(
        "SELECT id, label, date_version FROM documents ORDER BY id"
    ).fetchall()
    docs = []
    for doc_id, label, date_version in rows:
        if (RAW_PDF_DIR / f"{doc_id}.pdf").exists():
            docs.append({"id": doc_id, "label": label, "date_version": date_version})
    return docs


def process_document(source: dict, conn: sqlite3.Connection):
    pdf_path = RAW_PDF_DIR / f"{source['id']}.pdf"
    if not pdf_path.exists():
        print(f"[ERROR] {source['id']} : PDF introuvable ({pdf_path}) - lance download_sources.py d'abord")
        return 0

    print(f"Extraction : {source['label']}")
    # Idempotent : remplace les articles existants pour ce document
    deleted = conn.execute(
        "DELETE FROM articles WHERE document_id=?", (source["id"],)
    ).rowcount
    if deleted:
        print(f"  {deleted} ancien(s) article(s) remplace(s)")
    conn.execute("DELETE FROM articles_conflits WHERE document_id=?", (source["id"],))

    full_text = extract_pdf_text(pdf_path)
    print(f"  {len(full_text)} caracteres extraits")

    raw_chunks = split_by_article(full_text)
    print(f"  {len(raw_chunks)} occurrences brutes detectees")

    chunks, conflicts = resolve_duplicates(raw_chunks)
    print(f"  {len(chunks)} articles uniques retenus | {len(conflicts)} occurrences en conflit")

    if not chunks:
        chunks = [("À DÉCOUPER MANUELLEMENT", full_text)]
        print("  [WARNING] Aucun en-tete d'article detecte - texte insere en un seul bloc a verifier")

    now = datetime.now(timezone.utc).isoformat()
    for reference, texte in chunks:
        conn.execute(
            """
            INSERT INTO articles (document_id, reference, texte, source_label, date_version, statut, date_extraction)
            VALUES (?, ?, ?, ?, ?, 'a_verifier', ?)
            """,
            (source["id"], reference, texte, source["label"], source["date_version"], now),
        )

    for c in conflicts:
        conn.execute(
            """
            INSERT INTO articles_conflits (document_id, reference, occurrence_index, texte, longueur, retenu, date_extraction)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source["id"], c["reference"], c["occurrence_index"], c["texte"], c["longueur"], c["retenu"], now),
        )

    conn.execute("UPDATE documents SET statut='extrait' WHERE id=?", (source["id"],))
    conn.commit()
    return len(chunks)


def export_review_csv(conn: sqlite3.Connection):
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPORTS_DIR / "articles_a_verifier.csv"
    rows = conn.execute(
        "SELECT id, reference, source_label, substr(texte, 1, 220) AS apercu, statut FROM articles ORDER BY document_id, id"
    ).fetchall()

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "reference", "source", "apercu_200_caracteres", "statut"])
        writer.writerows(rows)

    print(f"\nExport de relecture genere : {out_path}")
    print(f"  -> {len(rows)} lignes a parcourir rapidement (pas a retaper)")

    # Export dédié aux conflits — c'est le fichier prioritaire à relire en premier,
    # car il pointe précisément les endroits où le corpus peut contenir un mauvais
    # rattachement article <-> texte.
    conflicts_path = EXPORTS_DIR / "articles_conflits_a_verifier.csv"
    conflict_rows = conn.execute(
        """
        SELECT document_id, reference, occurrence_index, longueur, retenu, substr(texte, 1, 220)
        FROM articles_conflits
        ORDER BY document_id, reference, occurrence_index
        """
    ).fetchall()

    with open(conflicts_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["document_id", "reference", "occurrence_index", "longueur", "retenu_par_defaut", "apercu_200_caracteres"])
        writer.writerows(conflict_rows)

    print(f"Export des CONFLITS genere : {conflicts_path}")
    print(f"  -> {len(conflict_rows)} occurrences en double a trancher manuellement en priorite")


def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_conflict_table(conn)

    documents = get_documents_to_extract(conn)
    if not documents:
        print("Aucun PDF local trouve — lance download_sources.py ou monitor_cgi.py d'abord.")
        conn.close()
        return

    total = 0
    for source in documents:
        total += process_document(source, conn)
        print()

    export_review_csv(conn)
    conn.close()

    print("=" * 50)
    print(f"Total : {total} articles inseres (statut = 'a_verifier')")
    print("PRIORITE : ouvrir articles_conflits_a_verifier.csv en premier.")
    print("Chaque reference qui y apparait a ete inseree en 'articles' avec sa")
    print("PREMIERE occurrence par defaut (heuristique corps principal < annexes).")
    print("Verifier que ce choix est correct pour les cas a fort impact (ex. articles")
    print("cites frequemment par l'audit IA), corriger manuellement en base sinon.")


if __name__ == "__main__":
    main()