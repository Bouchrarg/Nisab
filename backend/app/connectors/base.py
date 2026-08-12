"""
base.py — Contrat commun à toutes les sources de données comptables.

## La décision structurante de la Phase 5

Le schéma pivot n'est pas inventé pour l'occasion : **c'est déjà le dict que
produit OdooConnector.fetch_accounting_data()**. ai_auditor.run_ai_rag_audit(),
tax_calendar.get_calendar_events() et dashboard_summary() le consomment tous
les trois aujourd'hui.

Le choix aurait pu être de définir un « vrai » modèle pivot neutre et d'écrire
un adaptateur Odoo vers ce modèle. On ne l'a pas fait, pour une raison simple :
ça aurait obligé à réécrire les trois consommateurs, c'est-à-dire tout le
moteur d'audit, sans qu'aucun utilisateur y gagne quoi que ce soit. Le cahier
des charges dit « se brancher sur l'existant, ne pas le refaire » — la même
discipline s'applique à notre propre code.

Conséquence assumée : le vocabulaire du schéma pivot est celui d'Odoo
(`move_type`, `amount_total`, `partner_id`). C'est une dette de nommage, pas
une dette de conception, et elle est documentée ici plutôt que subie.

## Le schéma pivot, champ par champ

    {
      "company":  {"name": str, "vat": str|False, ...},
      "partners": [
          {"id": int, "name": str, "vat": str|False,
           "supplier_rank": int, "customer_rank": int, ...}
      ],
      "moves": [
          {"id": int,               # DOIT être stable entre deux imports
           "name": str,             # n° de pièce lisible, ex. "FACT-2026-002"
           "date": "YYYY-MM-DD",
           "journal_id": [int, str],
           "partner_id": [int, str] | False,
           "move_type": "in_invoice" | "out_invoice" | "entry",
           "amount_total": float,
           "ref": str,
           "state": "posted"}
      ],
      "lines": [
          {"move_id": [int, str],
           "account_id": [int, str],
           "name": str,             # libellé
           "debit": float, "credit": float,
           "date": "YYYY-MM-DD",
           "payment_mode": str}     # lu par ai_auditor._build_transaction_summary
      ],
      "source": str                 # "odoo_live" | "csv" | "demo_commerce" | ...
    }

Les couples `[id, libellé]` (journal_id, partner_id, account_id, move_id) sont
la convention many2one d'Odoo en XML-RPC. Un connecteur non-Odoo doit les
produire dans la même forme, sinon ai_auditor casse silencieusement.

## Contrainte non négociable sur `move["id"]`

L'identifiant doit être **déterministe** : réimporter le même fichier doit
produire les mêmes ids. La clé métier des alertes (voir AlerteRisque dans
models.py) en dépend indirectement, et une correction validée par un humain se
détacherait de son anomalie si les ids bougeaient à chaque import.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import TypeConnexion


class ConnectorError(Exception):
    """
    Échec côté source de données (identifiants, réseau, fichier illisible).

    Distincte d'une exception technique quelconque : les routes la traduisent en
    4xx avec un message lisible par un comptable, pas en 500. Une erreur de mot
    de passe Odoo n'est pas un bug de Nisab.
    """


class AccountingConnector(ABC):
    """
    Toute source de données comptables implémente ce contrat.

    Trois implémentations aujourd'hui : Odoo (XML-RPC), fichier (CSV/Excel),
    Sage (non implémenté, voir sage_connecteur.py).
    """

    #: Valeur écrite dans ConnexionComptable.type pour tracer l'origine.
    type_connexion: TypeConnexion

    @abstractmethod
    def test_connection(self) -> dict:
        """
        Vérifie l'accès à la source sans rapatrier les données.

        Retourne toujours un dict, jamais un booléen nu :
            {"ok": bool, "message": str, "untested": bool (optionnel)}
        `untested=True` signale une implémentation écrite mais jamais exécutée
        contre un vrai système — ne jamais l'afficher comme un succès.
        """

    @abstractmethod
    def fetch_accounting_data(self) -> dict:
        """
        Rapatrie les données au schéma pivot documenté en tête de module.

        Lève ConnectorError si la source est inaccessible ou illisible.
        """
