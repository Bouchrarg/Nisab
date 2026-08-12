"""
sage_connecteur.py — Connecteur Sage 100c : NON IMPLÉMENTÉ, et assumé comme tel.

## Pourquoi ce fichier existe alors qu'il ne fait rien

Le cahier des charges cite « connecteurs logiciels comptables (Sage, Odoo...) ».
La réponse honnête, pour un stage de 2 mois sans licence ni instance Sage, est :
l'abstraction est le livrable, pas le connecteur.

Écrire du SQL ODBC qui n'a jamais été exécuté une seule fois contre une vraie
base Sage aurait produit du code d'apparence fonctionnelle, impossible à
démontrer et probablement faux dans le détail (les schémas Sage varient selon
la version et le paramétrage du dossier). Un stub explicite vaut mieux qu'une
implémentation invérifiable : il dit la vérité au lecteur du code comme au jury.

Ce que prouve réellement la Phase 5 : que le moteur d'audit ne dépend plus
d'Odoo. C'est démontré par fichier_connecteur.py, qui alimente exactement le
même pipeline sans qu'aucune ligne d'ai_auditor n'ait été touchée.

## Ce qu'il faudrait faire pour l'implémenter

Sage 100c expose ses données via ODBC (pilote Sage 100 ODBC) sur des tables
préfixées `F_` :

    F_ECRITUREC   écritures comptables  -> moves + lines
    F_COMPTET     comptes de tiers      -> partners
    F_COMPTEG     plan comptable général-> account_id des lignes
    F_JOURNAL     journaux              -> journal_id

Le travail consisterait à écrire quatre requêtes SELECT et à mapper leurs
colonnes vers le schéma pivot documenté dans base.py. Rien d'intellectuellement
difficile ; ce qui manque est l'accès à un système réel pour valider le mapping.

`pyodbc` n'est volontairement pas dans requirements.txt (ligne commentée) : le
backend doit démarrer sans lui.
"""

from __future__ import annotations

from app.connectors.base import AccountingConnector, ConnectorError
from app.models import TypeConnexion

#: Aucune requête de ce module n'a jamais été exécutée contre une instance Sage.
#: Cette constante existe pour que l'information soit lisible dans le code et
#: remontable à l'interface, plutôt que cachée dans un commentaire.
SAGE_TESTE_EN_REEL = False

_MESSAGE = (
    "Connecteur Sage non implémenté. L'interface commune est en place "
    "(voir connectors/base.py) mais le mapping ODBC n'a pas pu être écrit ni "
    "validé faute d'instance Sage disponible. Utilisez l'import de fichier "
    "CSV/Excel pour alimenter un dossier depuis Sage : l'export comptable de "
    "Sage produit exactement les colonnes attendues."
)


class SageAccountingConnector(AccountingConnector):
    type_connexion = TypeConnexion.sage

    def test_connection(self) -> dict:
        # Ni ok=True ni exception : l'appelant doit pouvoir afficher « non
        # testé » sans que ça ressemble à une panne ni à un succès.
        return {"ok": False, "untested": True, "message": _MESSAGE}

    def fetch_accounting_data(self) -> dict:
        raise ConnectorError(_MESSAGE)
