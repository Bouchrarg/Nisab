"""
journal_acces.py — Journalisation des accès aux données personnelles/
comptables, exigence CNDP (loi 09-08 — cf. cahier-des-charges.md :
"confidentialité et hébergement conformes").

## Ce que ce module ne doit JAMAIS faire

`enregistrer_acces()` est appelée depuis le middleware HTTP (app/main.py),
donc sur CHAQUE requête entrante d'un préfixe surveillé. Une exception levée
ici ferait échouer la requête réelle pour une raison qui n'a rien à voir avec
elle — journaliser un accès ne doit jamais pouvoir bloquer cet accès. D'où le
`try/except` large : toute erreur (base indisponible, contrainte violée) est
avalée et seulement signalée en log, jamais propagée.

## Pourquoi une session indépendante plutôt que la session de la requête

Le middleware s'exécute APRÈS `call_next` (voir main.py) : à ce stade, la
session de la requête (posée par `get_db`/`get_tenant_db`) a déjà pu être
fermée par sa dependency FastAPI. Utiliser `SessionLocal` directement isole
l'écriture du journal de tout ce qui s'est passé sur la requête elle-même.
"""

from __future__ import annotations

from app.db import SessionLocal
from app.models import JournalAcces


def enregistrer_acces(organisation_id: str | None, utilisateur_id: str | None, endpoint: str) -> None:
    """
    Best-effort : journalise une ligne, ne lève jamais.

    `organisation_id`/`utilisateur_id` à None couvrent les accès sans jeton
    valide (ou avant résolution du tenant) — cf. JournalAcces, docstring de
    tête dans models.py.
    """
    db = SessionLocal()
    try:
        db.add(JournalAcces(
            organisation_id=organisation_id,
            utilisateur_id=utilisateur_id,
            endpoint=endpoint,
        ))
        db.commit()
    except Exception as exc:
        print(f"[JOURNAL_ACCES] Échec de journalisation (ignoré, requête non affectée) : {exc}")
        db.rollback()
    finally:
        db.close()
