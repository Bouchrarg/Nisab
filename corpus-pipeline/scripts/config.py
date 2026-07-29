from pathlib import Path

# --- Chemins ---
ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_PDF_DIR = ROOT_DIR / "data" / "raw_pdfs"
EXPORTS_DIR = ROOT_DIR / "data" / "exports"
DB_PATH = ROOT_DIR / "data" / "corpus.db"
MONITOR_STATE_PATH = ROOT_DIR / "data" / "monitor_state.json"

# --- Sources initiales (corpus MVP : CGI + Bulletin Officiel) ---
# Les entrées ci-dessous servent de seed au premier lancement.
# Le CGI des nouvelles années est détecté automatiquement par monitor_cgi.py
# (schéma URL : .../Publication/dgi/{N-1}/CGI-{N}-FR.pdf).
SOURCES = [
    {
        "id": "cgi_2026",
        "label": "Code Général des Impôts 2026",
        "type": "CGI",
        "url": "https://www.finances.gov.ma/Publication/dgi/2025/CGI-2026-FR.pdf",
        "date_version": "2026-01-01",
    },
    {
        "id": "bo_7465_bis_2025",
        "label": "Bulletin Officiel n°7465 bis — Loi de Finances n°50-25 (2026)",
        "type": "BULLETIN_OFFICIEL",
        "url": "https://www.sgg.gov.ma/BO/FR/2873/2025/BO_7465-bis_fr.pdf",
        "date_version": "2025-12-16",
    },
]

# --- Monitoring Bulletin Officiel ---
# Le portail sgg.gov.ma utilise un schéma d'URL prévisible :
#   https://www.sgg.gov.ma/BO/FR/{CATALOG_ID}/{annee}/BO_{numero}[-bis|-ter]_fr.pdf
# CATALOG_ID = 2873 correspond à l'édition de traduction officielle (français).
BO_CATALOG_ID = 2873
BO_BASE_URL = f"https://www.sgg.gov.ma/BO/FR/{BO_CATALOG_ID}"

# sans User-Agent de navigateur.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
