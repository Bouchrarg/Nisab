"""
odoo_connecteur.py — Adaptateur d'OdooConnector vers l'interface commune.

Volontairement mince, et volontairement séparé de `app/odoo_connector.py` :
ce dernier est importé tel quel par routes_dossiers.py et contient toute la
logique XML-RPC + les scénarios de démonstration. Le déplacer pour « ranger »
aurait produit un gros diff sans corriger quoi que ce soit.

Ici on ne fait qu'une chose : donner à Odoo la même forme d'appel qu'aux
autres sources, pour que les routes n'aient pas à savoir de qui elles parlent.
"""

from __future__ import annotations

from app.connectors.base import AccountingConnector, ConnectorError
from app.models import TypeConnexion
from app.odoo_connector import OdooConnector


class OdooAccountingConnector(AccountingConnector):
    type_connexion = TypeConnexion.odoo

    def __init__(self, url: str, db: str, username: str, password: str):
        self._client = OdooConnector(url=url, db=db, username=username, password=password)

    def test_connection(self) -> dict:
        try:
            uid = self._client.authenticate()
        except Exception as exc:
            # ValueError (mauvais identifiants) et les erreurs réseau de
            # xmlrpc.client remontent ici de la même façon : dans les deux cas
            # c'est la source qui est en cause, pas Nisab.
            raise ConnectorError(f"Connexion Odoo impossible : {exc}") from exc
        return {"ok": True, "message": f"Authentifié sur {self._client.db} (uid {uid})."}

    def fetch_accounting_data(self) -> dict:
        try:
            if self._client.uid is None:
                self._client.authenticate()
            return self._client.fetch_accounting_data()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Lecture des données Odoo impossible : {exc}") from exc

    @property
    def client(self) -> OdooConnector:
        """
        Accès au client bas niveau, pour ce qui n'est pas dans le contrat commun
        (création d'un brouillon d'écriture — voir le workflow de correction).
        Aucune autre source ne sait écrire, donc ça n'a pas sa place dans l'ABC.
        """
        return self._client
