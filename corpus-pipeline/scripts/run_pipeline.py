import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
BACKEND_SCRIPTS_DIR = SCRIPTS_DIR.parent.parent / "backend" / "scripts"
PYTHON = sys.executable


def run(script: Path, *args, label: str = ""):
    cmd = [PYTHON, str(script)] + list(args)
    label = label or script.name
    print(f"\n{'='*55}")
    print(f"RUN: {label}")
    print(f"{'='*55}")
    result = subprocess.run(cmd, cwd=str(script.parent))
    if result.returncode != 0:
        print(f"\nFAILURE: {label} (code {result.returncode})")
        sys.exit(result.returncode)
    print(f"SUCCESS: {label}")


def main():
    parser = argparse.ArgumentParser(description="Orchestrateur pipeline Nisab")
    parser.add_argument("--skip-download", action="store_true",
                        help="Ne pas retelecharger les PDFs")
    parser.add_argument("--skip-monitor", action="store_true",
                        help="Ne pas surveiller les nouveaux Bulletins Officiels")
    parser.add_argument("--skip-cgi-monitor", action="store_true",
                        help="Ne pas detecter automatiquement le nouveau CGI")
    parser.add_argument("--auto-validate", action="store_true",
                        help="Valider automatiquement tous les articles")
    parser.add_argument("--include-a-verifier", action="store_true",
                        help="Inclure les articles a_verifier dans Supabase")
    args = parser.parse_args()

    print("\nStarting Nisab pipeline\n")

    # 1. Initialiser la base SQLite locale
    run(SCRIPTS_DIR / "init_db.py", label="Initialisation base locale (init_db)")

    # 2. Veille CGI (nouvelle annee fiscale)
    if not args.skip_cgi_monitor:
        run(SCRIPTS_DIR / "monitor_cgi.py", label="Veille CGI (nouvelle annee)")
    else:
        print("\nSkip CGI monitor")

    # 3. Telecharger les sources
    if not args.skip_download:
        run(SCRIPTS_DIR / "download_sources.py", label="Telechargement des PDFs")
    else:
        print("\nSkip download")

    # 4. Veille Bulletin Officiel
    if not args.skip_monitor:
        run(SCRIPTS_DIR / "monitor_bo.py", label="Veille Bulletin Officiel")
    else:
        print("\nSkip monitor")

    # 5. Extraction
    run(SCRIPTS_DIR / "extract_corpus.py", label="Extraction (extract_corpus)")

    # 6. Validation optionnelle
    if args.auto_validate:
        run(SCRIPTS_DIR / "validate_articles.py", "--all",
            label="Validation automatique des articles")
    else:
        print("\nArticles en statut 'a_verifier'.")

    # 7. Ingestion Supabase
    ingest_args = ["--include-a-verifier"] if args.include_a_verifier else []
    run(BACKEND_SCRIPTS_DIR / "ingest_to_supabase.py", *ingest_args,
        label="Ingestion Supabase (ingest_to_supabase)")

    print("\n" + "="*55)
    print("Nisab pipeline completed successfully!")
    print("="*55 + "\n")


if __name__ == "__main__":
    main()
