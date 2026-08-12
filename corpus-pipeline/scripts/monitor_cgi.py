"""
Veille CGI — détecte et télécharge automatiquement le CGI de la nouvelle année.

Schéma d'URL prévisible (finances.gov.ma) :
  https://www.finances.gov.ma/Publication/dgi/{année-1}/CGI-{année}-FR.pdf
Ex. CGI 2026 → dossier 2025, fichier CGI-2026-FR.pdf
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone

import requests

from config import DB_PATH, RAW_PDF_DIR, MONITOR_STATE_PATH, HTTP_HEADERS, SOURCES


def load_state() -> dict:
    if MONITOR_STATE_PATH.exists():
        state = json.loads(MONITOR_STATE_PATH.read_text(encoding="utf-8"))
    else:
        state = {}
    if "last_cgi_year" not in state:
        # Année fiscale la plus récente connue dans config ou année courante - 1
        cgi_years = [
            int(s["id"].split("_")[1])
            for s in SOURCES
            if s["id"].startswith("cgi_") and s["id"].split("_")[1].isdigit()
        ]
        state["last_cgi_year"] = max(cgi_years) if cgi_years else datetime.now().year - 1
    return state


def save_state(state: dict):
    MONITOR_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def cgi_url(fiscal_year: int) -> str:
    folder = fiscal_year - 1
    return f"https://www.finances.gov.ma/Publication/dgi/{folder}/CGI-{fiscal_year}-FR.pdf"


def check_url(url: str) -> bool:
    try:
        resp = requests.head(url, headers=HTTP_HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            return True
        if resp.status_code in (403, 405):
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=15, stream=True)
            return resp.status_code == 200
        return False
    except requests.RequestException:
        return False


def seed_config_sources(conn: sqlite3.Connection):
    """Insère les sources de config.py si absentes de la base."""
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


def download_and_register(conn: sqlite3.Connection, fiscal_year: int, url: str):
    doc_id = f"cgi_{fiscal_year}"
    dest = RAW_PDF_DIR / f"{doc_id}.pdf"
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=60)
        resp.raise_for_status()
        if not resp.content[:4] == b"%PDF":
            print(f"  [WARNING] {url} ne ressemble pas a un PDF")
            return False
        dest.write_bytes(resp.content)
    except requests.RequestException as e:
        print(f"  [ERROR] Telechargement echoue : {e}")
        return False

    label = f"Code General des Impots {fiscal_year}"
    conn.execute(
        """
        INSERT INTO documents (id, label, type, url, date_version, chemin_local, date_telechargement, statut)
        VALUES (?, ?, 'CGI', ?, ?, ?, ?, 'telecharge')
        ON CONFLICT(id) DO UPDATE SET
            url=excluded.url,
            chemin_local=excluded.chemin_local,
            date_telechargement=excluded.date_telechargement,
            statut='telecharge'
        """,
        (
            doc_id,
            label,
            url,
            f"{fiscal_year}-01-01",
            str(dest),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    print(f"  [OK] CGI {fiscal_year} telecharge : {dest} ({len(resp.content) // 1024} Ko)")
    return True


def main():
    parser = argparse.ArgumentParser()
    # --year cible directement UNE année passée (backfill) au lieu de sonder
    # en avant : la boucle par défaut ne part que de `last_cgi_year + 1` et ne
    # peut donc jamais aller chercher un millésime antérieur (2024, 2025...).
    # Réutilise exactement download_and_register() — même enregistrement que
    # pour un CGI détecté par la boucle forward, juste appelé directement.
    parser.add_argument("--year", type=int, help="Télécharge/enregistre directement cette année (backfill), sans sonder en avant.")
    args = parser.parse_args()

    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    seed_config_sources(conn)

    if args.year:
        url = cgi_url(args.year)
        print(f"Backfill CGI {args.year} -> {url}")
        if not check_url(url):
            print(f"  [ERROR] CGI {args.year} introuvable a cette URL. Le nom de fichier a peut-etre change pour cette annee ; "
                  f"a verifier/ajuster manuellement si besoin.")
        elif download_and_register(conn, args.year, url):
            print(f"CGI {args.year} enregistre dans le corpus.")
        conn.close()
        return

    state = load_state()

    last_year = state["last_cgi_year"]
    probe_until = datetime.now().year + 1
    print(f"Dernier CGI connu : {last_year}")
    print(f"Recherche de CGI {last_year + 1} a {probe_until}...\n")

    found_any = False
    for year in range(last_year + 1, probe_until + 1):
        url = cgi_url(year)
        if not check_url(url):
            print(f"  CGI {year} : absent ({url})")
            continue

        print(f"Nouveau CGI detecte : {year} -> {url}")
        if download_and_register(conn, year, url):
            state["last_cgi_year"] = year
            found_any = True

    if found_any:
        save_state(state)
        print(f"\nEtat mis a jour : dernier CGI connu = {state['last_cgi_year']}")
    else:
        print("\nAucun nouveau CGI detecte.")

    conn.close()


if __name__ == "__main__":
    main()
