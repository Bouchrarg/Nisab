import json
import sqlite3
import sys
from datetime import datetime, timezone

import requests

from config import (
    DB_PATH, RAW_PDF_DIR, MONITOR_STATE_PATH, BO_BASE_URL, HTTP_HEADERS,
)

MAX_LOOKAHEAD = 15          
SUFFIXES = ["", "-bis", "-ter"]
CASE_VARIANTS = ["fr", "Fr"]  


def load_state() -> dict:
    if MONITOR_STATE_PATH.exists():
        return json.loads(MONITOR_STATE_PATH.read_text(encoding="utf-8"))
    return {"last_number": 7465, "last_year": 2025}


def save_state(state: dict):
    MONITOR_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def candidate_urls(number: int, year: int):
    for suffix in SUFFIXES:
        for case in CASE_VARIANTS:
            yield f"{BO_BASE_URL}/{year}/BO_{number}{suffix}_{case}.pdf", suffix


def check_url(url: str) -> bool:
    try:
        resp = requests.head(url, headers=HTTP_HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            return True
        # Certains serveurs ne supportent pas HEAD correctement -> on retente en GET léger
        if resp.status_code in (403, 405):
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=15, stream=True)
            return resp.status_code == 200
        return False
    except requests.RequestException:
        return False


def log_event(conn, numero, annee, url, statut):
    conn.execute(
        "INSERT INTO veille_log (numero_bo, annee, url, statut, date_detection) VALUES (?, ?, ?, ?, ?)",
        (str(numero), annee, url, statut, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def download_and_register(conn, numero, annee, url, suffix):
    doc_id = f"bo_{numero}{suffix.replace('-', '_')}_{annee}"
    dest = RAW_PDF_DIR / f"{doc_id}.pdf"
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    except requests.RequestException as e:
        print(f"  [ERROR] Telechargement echoue pour {url} : {e}")
        return

    conn.execute(
        """
        INSERT INTO documents (id, label, type, url, date_version, chemin_local, date_telechargement, statut)
        VALUES (?, ?, 'BULLETIN_OFFICIEL', ?, ?, ?, ?, 'a_qualifier')
        ON CONFLICT(id) DO NOTHING
        """,
        (
            doc_id,
            f"Bulletin Officiel n°{numero}{suffix} ({annee}) - detecte automatiquement",
            url,
            datetime.now(timezone.utc).date().isoformat(),
            str(dest),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    print(f"  [OK] Telecharge et enregistre (statut = a_qualifier) : {dest}")


def main():
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    state = load_state()

    last_number = state["last_number"]
    year = state["last_year"]
    print(f"Dernier numero connu : BO n°{last_number} ({year})")
    print(f"Recherche de nouveautes jusqu'a BO n°{last_number + MAX_LOOKAHEAD}...\n")

    found_any = False
    highest_found = last_number

    for offset in range(1, MAX_LOOKAHEAD + 1):
        numero = last_number + offset
        found_for_this_number = False

        for url, suffix in candidate_urls(numero, year):
            exists = check_url(url)
            if exists:
                print(f"Nouveau : BO n°{numero}{suffix} -> {url}")
                log_event(conn, f"{numero}{suffix}", year, url, "nouveau")
                download_and_register(conn, numero, year, url, suffix)
                found_any = True
                found_for_this_number = True
                highest_found = max(highest_found, numero)
                break  # inutile de tester les autres variantes de casse pour ce suffixe

        if not found_for_this_number:
            log_event(conn, str(numero), year, next(candidate_urls(numero, year))[0], "absent")

    if found_any:
        state["last_number"] = highest_found
        save_state(state)
        print(f"\nEtat mis a jour : dernier numero connu = {highest_found}")
    else:
        print("\nAucune nouveaute detectee depuis la derniere verification.")

    conn.close()


if __name__ == "__main__":
    main()
