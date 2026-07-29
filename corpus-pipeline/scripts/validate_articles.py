import argparse
import sqlite3

from config import DB_PATH


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Valider tous les articles en attente")
    group.add_argument("--ids", nargs="+", type=int, help="Valider uniquement ces IDs")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    if args.all:
        cur = conn.execute("UPDATE articles SET statut='valide' WHERE statut='a_verifier'")
    else:
        placeholders = ",".join("?" for _ in args.ids)
        cur = conn.execute(
            f"UPDATE articles SET statut='valide' WHERE id IN ({placeholders})", args.ids
        )

    conn.commit()
    print(f"{cur.rowcount} article(s) marqué(s) comme 'valide'.")

    remaining = conn.execute("SELECT COUNT(*) FROM articles WHERE statut='a_verifier'").fetchone()[0]
    print(f"{remaining} article(s) encore en attente de relecture.")
    conn.close()


if __name__ == "__main__":
    main()
