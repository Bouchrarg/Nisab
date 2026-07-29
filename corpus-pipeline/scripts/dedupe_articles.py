"""Supprime les articles en double (meme document + meme reference). Garde le plus recent."""

import sqlite3

from config import DB_PATH


def main():
    conn = sqlite3.connect(DB_PATH)
    before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    conn.execute("""
        DELETE FROM articles
        WHERE id NOT IN (
            SELECT MAX(id) FROM articles GROUP BY document_id, reference
        )
    """)
    conn.commit()

    after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    removed = before - after
    conn.close()

    print(f"{removed} doublon(s) supprime(s). {after} article(s) restant(s).")


if __name__ == "__main__":
    main()
