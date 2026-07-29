import sqlite3
import sys
from datetime import datetime, timezone
import requests

from config import DB_PATH, RAW_PDF_DIR, SOURCES, HTTP_HEADERS


def download_one(source: dict) -> bool:
    dest = RAW_PDF_DIR / f"{source['id']}.pdf"
    print(f"Telechargement : {source['label']}")
    print(f"  URL : {source['url']}")
    try:
        resp = requests.get(source["url"], headers=HTTP_HEADERS, timeout=30)
        resp.raise_for_status()
        if resp.headers.get("Content-Type", "").lower().find("pdf") == -1 and not resp.content[:4] == b"%PDF":
            print("  [WARNING] La reponse ne ressemble pas a un PDF - verifie l'URL manuellement.")
            return False
        dest.write_bytes(resp.content)
        print(f"  [OK] Enregistre : {dest} ({len(resp.content) // 1024} Ko)")
        return True
    except requests.RequestException as e:
        print(f"  [ERROR] Echec du telechargement : {e}")
        print("  -> Solution de secours : telecharge le PDF manuellement dans un navigateur")
        print(f"    et place-le dans {dest}")
        return False


def register_in_db(source: dict, downloaded: bool):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO documents (id, label, type, url, date_version, chemin_local, date_telechargement, statut)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            chemin_local=excluded.chemin_local,
            date_telechargement=excluded.date_telechargement,
            statut=excluded.statut
        """,
        (
            source["id"],
            source["label"],
            source["type"],
            source["url"],
            source["date_version"],
            str(RAW_PDF_DIR / f"{source['id']}.pdf") if downloaded else None,
            datetime.now(timezone.utc).isoformat(),
            "telecharge" if downloaded else "erreur",
        ),
    )
    conn.commit()
    conn.close()


def seed_config_sources(conn: sqlite3.Connection):
    for source in SOURCES:
        conn.execute(
            """
            INSERT INTO documents (id, label, type, url, date_version, statut)
            VALUES (?, ?, ?, ?, ?, 'telecharge')
            ON CONFLICT(id) DO NOTHING
            """,
            (source["id"], source["label"], source["type"], source["url"], source["date_version"]),
        )
    conn.commit()


def get_sources_from_db(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT id, label, type, url, date_version FROM documents ORDER BY id"
    ).fetchall()
    return [
        {"id": r[0], "label": r[1], "type": r[2], "url": r[3], "date_version": r[4]}
        for r in rows
    ]


def main():
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    seed_config_sources(conn)
    sources = get_sources_from_db(conn)

    results = []
    for source in sources:
        ok = download_one(source)
        register_in_db(source, ok)
        results.append((source["id"], ok))
        print()

    conn.close()

    print("=" * 50)
    print("Resume :")
    for sid, ok in results:
        print(f"  {'OK' if ok else 'ERROR'} {sid}")

    if not all(ok for _, ok in results):
        print("\nCertains telechargements ont echoue - corrige-les avant de lancer extract_corpus.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
