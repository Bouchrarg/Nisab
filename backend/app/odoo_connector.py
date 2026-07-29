
from __future__ import annotations

import xmlrpc.client
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class OdooConnector:
    url: str
    db: str
    username: str
    password: str
    uid: Optional[int] = None

    


    def authenticate(self) -> int:
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        uid = common.authenticate(self.db, self.username, self.password, {})
        if not uid:
            raise ValueError(
                f"Authentification échouée pour {self.username} sur {self.url}/{self.db}. "
                "Vérifiez l'URL, la base de données, le login et le mot de passe."
            )
        self.uid = uid
        return uid

    def _models(self):
        return xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _execute(self, model: str, method: str, *args, **kwargs):
        """Wrapper générique pour exécuter une méthode Odoo."""
        if self.uid is None:
            raise RuntimeError("Non authentifié — appelez authenticate() d'abord.")
        return self._models().execute_kw(
            self.db, self.uid, self.password,
            model, method, list(args), kwargs
        )

    def fetch_accounting_data(self) -> dict:
        # Company info
        company_fields = ["name", "vat", "country_id", "currency_id"]
        companies = self._execute("res.company", "search_read",
                                [], fields=company_fields, limit=1)
        company = companies[0] if companies else {}

        # Partners (fournisseurs avec ICE/VAT)
        partner_fields = ["id","name", "vat", "supplier_rank", "customer_rank", "street", "city"]
        partners = self._execute("res.partner", "search_read",
                                [["active", "=", True]],
                                fields=partner_fields, limit=200)

        # Validated journal entries (last 12 months)
        cutoff = (date.today() - timedelta(days=365)).isoformat()
        move_fields = ["id", "name", "date", "journal_id", "partner_id", "move_type",
                    "amount_total", "payment_state", "ref", "state"]
        moves = self._execute("account.move", "search_read",
                            [["state", "=", "posted"],
                            ["date", ">=", cutoff]],
                            fields=move_fields, limit=500, order="date desc")

        # Journal entry lines
        line_fields = ["move_id", "account_id", "name", "debit", "credit",
                    "tax_ids", "tax_line_id", "partner_id", "date",
                    "amount_currency"]
        move_ids = [m["id"] for m in moves]
        lines = []
        if move_ids:
            lines = self._execute("account.move.line", "search_read",
                                [["move_id", "in", move_ids]],
                                fields=line_fields, limit=5000)

        return {
            "company": company,
            "partners": partners,
            "moves": moves,
            "lines": lines,
            "source": "odoo_live",
        }


# ─────────────────────────────────────────────────────────────────────────────
# DONNÉES DE DÉMONSTRATION (PME fictive avec anomalies fiscales réelles)
# ─────────────────────────────────────────────────────────────────────────────

def get_demo_data() -> dict:
    """
    Simule les données comptables d'une PME marocaine (Atlas Négoce SARL)
    avec des anomalies fiscales typiques pour illustrer le moteur d'audit.
    """
    company = {
        "id": 1,
        "name": "Atlas Négoce SARL",
        "vat": "MA002345678901",
        "country_id": [110, "Maroc"],
        "currency_id": [147, "MAD"],
    }

    partners = [
        {"id": 10, "name": "Fournisseur Al Baraka", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Casablanca"},
        {"id": 11, "name": "Fournisseur TechMaroc SARL", "vat": "MA001234567890",
         "supplier_rank": 1, "customer_rank": 0, "city": "Rabat"},
        {"id": 12, "name": "Fournisseur Equipements Pro", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Fès"},
        {"id": 13, "name": "Client Marjane Holding", "vat": "MA009876543210",
         "supplier_rank": 0, "customer_rank": 1, "city": "Casablanca"},
        {"id": 14, "name": "Client Al Mazar SAS", "vat": None,
         "supplier_rank": 0, "customer_rank": 1, "city": "Marrakech"},
        {"id": 15, "name": "Fournisseur Carburants Sud", "vat": None,
         "supplier_rank": 1, "customer_rank": 0, "city": "Agadir"},
    ]

    moves = [
        # Facture normale
        {"id": 101, "name": "FACT-2026-001", "date": "2026-01-15",
         "journal_id": [1, "Achats"], "partner_id": [11, "Fournisseur TechMaroc SARL"],
         "move_type": "in_invoice", "amount_total": 24000.0,
         "payment_state": "paid", "ref": "INV-2026-001", "state": "posted"},
        # Achat en espèces dépassant 5000 DH (Anomalie → Art. 193)
        {"id": 102, "name": "FACT-2026-002", "date": "2026-01-20",
         "journal_id": [2, "Caisse"], "partner_id": [10, "Fournisseur Al Baraka"],
         "move_type": "in_invoice", "amount_total": 8500.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Fournisseur sans ICE (Anomalie → ICE obligatoire depuis 2017)
        {"id": 103, "name": "FACT-2026-003", "date": "2026-02-05",
         "journal_id": [1, "Achats"], "partner_id": [12, "Fournisseur Equipements Pro"],
         "move_type": "in_invoice", "amount_total": 45000.0,
         "payment_state": "paid", "ref": "EQ-2026-03", "state": "posted"},
        # Amortissement voiture de tourisme > 300 000 DH (Anomalie → Art. 10-I-F)
        {"id": 104, "name": "IMMO-2026-001", "date": "2026-01-01",
         "journal_id": [5, "OD Amortissements"], "partner_id": False,
         "move_type": "entry", "amount_total": 85000.0,
         "payment_state": False, "ref": "Amort. Véhicule Tourisme 450000DH",
         "state": "posted"},
        # Facture client normale
        {"id": 105, "name": "VENTE-2026-001", "date": "2026-02-10",
         "journal_id": [3, "Ventes"], "partner_id": [13, "Client Marjane Holding"],
         "move_type": "out_invoice", "amount_total": 120000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Deuxième achat en espèces même fournisseur (cumul > 50000/mois)
        {"id": 106, "name": "FACT-2026-004", "date": "2026-01-28",
         "journal_id": [2, "Caisse"], "partner_id": [10, "Fournisseur Al Baraka"],
         "move_type": "in_invoice", "amount_total": 47000.0,
         "payment_state": "paid", "ref": None, "state": "posted"},
        # Note de restaurant d'affaires (TVA non déductible sur resto)
        {"id": 107, "name": "FACT-2026-005", "date": "2026-03-12",
         "journal_id": [1, "Achats"], "partner_id": [15, "Fournisseur Carburants Sud"],
         "move_type": "in_invoice", "amount_total": 3200.0,
         "payment_state": "paid", "ref": "Repas d'affaires clients mars 2026",
         "state": "posted"},
    ]

    lines = [
        # Lines pour FACT-2026-002 (espèces)
        {"id": 201, "move_id": [102, "FACT-2026-002"], "account_id": [612, "Achats"],
         "name": "Marchandises", "debit": 7500.0, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [10, "Fournisseur Al Baraka"],
         "date": "2026-01-20", "payment_mode": "cash", "amount_currency": 0.0},
        {"id": 202, "move_id": [102, "FACT-2026-002"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20%", "debit": 1000.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [10, "Fournisseur Al Baraka"],
         "date": "2026-01-20", "payment_mode": "cash", "amount_currency": 0.0},
        # Lines pour IMMO (amortissement voiture)
        {"id": 203, "move_id": [104, "IMMO-2026-001"],
         "account_id": [61930, "Dotations amortissements"],
         "name": "Amort. véhicule tourisme 450000 DH (taux 20%)",
         "debit": 90000.0, "credit": 0.0,
         "tax_ids": [], "tax_line_id": False, "partner_id": False,
         "date": "2026-01-01", "payment_mode": False, "amount_currency": 0.0},
        # Lines pour resto
        {"id": 204, "move_id": [107, "FACT-2026-005"],
         "account_id": [6185, "Charges de réception"], "name": "Repas d'affaires clients",
         "debit": 2666.67, "credit": 0.0,
         "tax_ids": [10], "tax_line_id": False, "partner_id": [15, "Fournisseur Carburants Sud"],
         "date": "2026-03-12", "payment_mode": "bank", "amount_currency": 0.0},
        {"id": 205, "move_id": [107, "FACT-2026-005"], "account_id": [34552, "TVA déductible"],
         "name": "TVA 20% Repas d'affaires", "debit": 533.33, "credit": 0.0,
         "tax_ids": [], "tax_line_id": 10, "partner_id": [15, "Fournisseur Carburants Sud"],
         "date": "2026-03-12", "payment_mode": "bank", "amount_currency": 0.0},
    ]

    return {
        "company": company,
        "partners": partners,
        "moves": moves,
        "lines": lines,
        "source": "demo",
    }
if __name__ == "__main__":
    connector = OdooConnector(
        url="http://localhost:8069",
        db="Nisab_demo",
        username="rguibi.bouchra@ensam-casa.ma",
        password="odoo123",
    )
    connector.authenticate()

    # --- Diagnostic : lister les champs disponibles ---
    fields_info = connector._execute(
        "account.move.line", "fields_get", [], attributes=["string", "type"]
    )
    print(list(fields_info.keys()))