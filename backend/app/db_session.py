"""
db_session.py — Bascule le contexte "tenant courant" sur une session Postgres,
pour que les policies Row-Level Security (voir migration 0001) filtrent
automatiquement chaque requête par organisation.

Utilisation typique (dans une dependency FastAPI, après authentification) :

    def get_tenant_db(db: Session = Depends(get_db), user=Depends(get_current_user)):
        set_tenant_context(db, user.organisation_id)
        return db

## Pourquoi le contexte se réapplique tout seul (et pourquoi il le doit)

`set_config(..., true)` est de portée TRANSACTION, pas session. Conséquence :
tout `db.commit()` efface le tenant courant, et la requête suivante ouvre une
nouvelle transaction où `app.current_org_id` vaut `''`. Les policies évaluant
`current_setting('app.current_org_id', true)::uuid`, Postgres échoue alors sur
`invalid input syntax for type uuid: ""` — une erreur 500 qui ne dit rien de
sa vraie cause.

Ce n'était pas théorique : `odoo_connect` persistait les données (commit) puis
cherchait la ligne `connexion_comptable` pour y écrire les identifiants
chiffrés. Le second SELECT partait sans tenant et plantait — mais seulement
quand l'utilisateur cochait « mémoriser les identifiants », d'où un bug resté
invisible longtemps.

Le correctif ne consiste pas à rappeler `set_tenant_context()` après chaque
commit dans chaque route : cette discipline se périme au premier oubli, et
l'oubli ne se voit qu'en production, sur la route la moins testée. On mémorise
l'organisation SUR la session (`Session.info`) et un listener `after_begin`
repose le paramètre à chaque nouvelle transaction. L'invariant devient une
propriété de la session, plus une convention d'écriture des routes.

Les sessions qui n'ont jamais appelé `set_tenant_context` (celles de
`get_admin_db`, volontairement cross-tenant) n'ont pas la clé dans `info` : le
listener les ignore.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db import get_db

#: Clé sous laquelle l'organisation courante est mémorisée dans `Session.info`.
#: Préfixée pour ne pas entrer en collision avec une clé d'une bibliothèque.
TENANT_INFO_KEY = "nisab_current_org_id"

_SQL_SET_ORG = text("SELECT set_config('app.current_org_id', :org_id, true)")


def get_tenant_db(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Session:
    set_tenant_context(db, user.organisation_id)
    return db


def set_tenant_context(db: Session, organisation_id: str) -> None:
    """
    Positionne le tenant courant pour la transaction EN COURS, et le mémorise
    sur la session pour qu'il soit reposé sur toutes les suivantes.

    L'écriture dans `info` précède l'exécution SQL : si cet appel est ce qui
    ouvre la transaction, le listener `after_begin` ci-dessous se déclenche
    pendant `db.execute` et trouve déjà la valeur. Le paramètre est alors posé
    deux fois — `set_config` est idempotent, ça ne coûte qu'un aller-retour.
    """
    db.info[TENANT_INFO_KEY] = str(organisation_id)
    db.execute(_SQL_SET_ORG, {"org_id": str(organisation_id)})


def clear_tenant_context(db: Session) -> None:
    """
    Repasse en mode 'aucun tenant' (utile pour les routes admin globales).

    Retire aussi la mémoire portée par la session, sinon le listener
    `after_begin` réinstallerait le tenant à la transaction suivante et
    annulerait silencieusement l'effet de cet appel.

    set_config(..., true) plutôt que RESET : RESET est scope session, donc via
    le pooler Supabase (PgBouncer, transaction mode) la valeur '' qu'il laisse
    peut être récupérée par une connexion pooled complètement différente sur
    sa prochaine transaction. set_config(..., true) reste scope transaction,
    comme set_tenant_context.
    """
    db.info.pop(TENANT_INFO_KEY, None)
    db.execute(text("SELECT set_config('app.current_org_id', '', true)"))


@event.listens_for(Session, "after_begin")
def _reposer_contexte_tenant(session: Session, transaction, connection) -> None:
    """
    Réinstalle `app.current_org_id` à chaque début de transaction.

    `after_begin` est le bon point d'accroche : il reçoit la connexion et se
    déclenche APRÈS que la transaction existe, donc le `set_config` local a
    bien une transaction à laquelle s'attacher. On écrit sur `connection` et
    non sur `session` pour ne pas rouvrir récursivement une transaction.

    Sans clé dans `session.info`, la session n'est pas tenant-scoped : on ne
    touche à rien (cas de `get_admin_db`, cross-tenant par conception).
    """
    org_id = session.info.get(TENANT_INFO_KEY)
    if org_id:
        connection.execute(_SQL_SET_ORG, {"org_id": org_id})
