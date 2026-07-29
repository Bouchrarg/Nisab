"""
check_pattern.py — Validation rapide des occurrences retenues après resolve_duplicates().

Vérifie que chaque ligne "retenu_par_defaut=1" du CSV articles_conflits_a_verifier.csv
respecte le pattern typographique du corps législatif principal du CGI :
"Article N.- Titre" (point-tiret suivi d'un titre court), qui distingue de façon
fiable un vrai article du corps principal d'un fragment d'annexe/arrêté/loi
rectificative (qui commence directement par du contenu, sans ce format).

Usage :
    python check_pattern.py chemin/vers/articles_conflits_a_verifier.csv
    (si aucun argument n'est donné, cherche "articles_conflits_a_verifier.csv"
    dans le dossier courant)
"""

import csv
import re
import sys

TITLE_PATTERN = re.compile(r"^Article\s+(?:premier|\d+)(?:\s+\w+)?\s*\.\s*-\s+\S")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "articles_conflits_a_verifier.csv"

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print(f"Fichier introuvable : {path}")
        print("Indique le bon chemin, par ex. : python check_pattern.py exports/articles_conflits_a_verifier.csv")
        sys.exit(1)

    suspects = []
    total_retenus = 0
    for row in rows:
        if row.get("retenu_par_defaut") == "1":
            total_retenus += 1
            apercu = row.get("apercu_200_caracteres", "")
            if not TITLE_PATTERN.match(apercu):
                suspects.append((row.get("reference"), apercu[:80]))

    print(f"{total_retenus} occurrence(s) retenue(s) par défaut analysée(s).\n")

    if suspects:
        print(f"⚠️  A VERIFIER MANUELLEMENT ({len(suspects)}) — ne respectent pas le pattern 'Article N.- Titre' :\n")
        for ref, apercu in suspects:
            print(f"  - {ref} : \"{apercu}...\"")
        print("\nPour chacune, ouvre articles_conflits_a_verifier.csv, regarde les autres occurrences")
        print("de cette même reference, et vérifie si une autre occurrence est en réalité le bon article.")
    else:
        print("✅ OK — toutes les occurrences retenues respectent le pattern 'Article N.- Titre'.")
        print("Le corpus peut être réindexé en confiance.")


if __name__ == "__main__":
    main()