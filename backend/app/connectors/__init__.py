"""
connectors — Sources de données comptables, derrière une interface commune.

Le contrat et le schéma pivot sont documentés dans `base.py`. C'est le fichier
à lire en premier.

Implémentations :
    odoo_connecteur.py     XML-RPC, opérationnel
    fichier_connecteur.py  CSV / Excel, opérationnel
    sage_connecteur.py     stub explicite, non implémenté (raison documentée)
"""

from __future__ import annotations

from app.connectors.base import AccountingConnector, ConnectorError
from app.connectors.fichier_connecteur import FichierAccountingConnector
from app.connectors.odoo_connecteur import OdooAccountingConnector
from app.connectors.sage_connecteur import SageAccountingConnector
from app.models import TypeConnexion

__all__ = [
    "AccountingConnector",
    "ConnectorError",
    "FichierAccountingConnector",
    "OdooAccountingConnector",
    "SageAccountingConnector",
    "get_connector",
]


def get_connector(type_connexion: TypeConnexion, config: dict) -> AccountingConnector:
    """
    Fabrique le connecteur correspondant au type demandé.

    `config` porte ce dont l'implémentation a besoin : identifiants pour Odoo,
    octets du fichier pour l'import. Volontairement un dict et non un modèle
    Pydantic par source — c'est la route qui valide ses entrées, la fabrique
    n'a pas à connaître la forme de chaque formulaire.
    """
    if type_connexion == TypeConnexion.odoo:
        return OdooAccountingConnector(
            url=config["url"], db=config["db"],
            username=config["username"], password=config["password"],
        )
    if type_connexion in (TypeConnexion.csv, TypeConnexion.ocr):
        return FichierAccountingConnector(
            contenu=config["contenu"], nom_fichier=config.get("nom_fichier", "import.csv"),
        )
    if type_connexion == TypeConnexion.sage:
        return SageAccountingConnector()
    raise ConnectorError(f"Type de connexion non pris en charge : {type_connexion}")
