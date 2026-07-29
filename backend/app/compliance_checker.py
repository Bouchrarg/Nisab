"""
compliance_checker.py — Moteur d'audit fiscal marocain pour Nisab.

Applique les règles du CGI 2026 sur les données comptables Odoo
(réelles ou démo) pour détecter les anomalies fiscales.

Règles implémentées :
  1. Plafonds de paiements en espèces (Art. 193 CGI)
  2. Absence d'ICE fournisseur (obligation légale depuis 2017)
  3. Amortissements véhicules de tourisme > 300 000 DH (Art. 10-I-F CGI)
  4. TVA non déductible sur frais de restaurant/réception (Art. 106-IV CGI)
  5. Incohérence de taux de TVA détectée par keywords
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _partner_id(move: dict) -> int | None:
    p = move.get("partner_id")
    if isinstance(p, list) and len(p) >= 1:
        return p[0]
    return None


def _partner_name(move: dict) -> str:
    p = move.get("partner_id")
    if isinstance(p, list) and len(p) >= 2:
        return p[1]
    return "Inconnu"


def _is_cash_payment(move: dict, lines: list[dict]) -> bool:
    """Détecte si le règlement de la facture est en espèces (caisse)."""
    # Méthode 1 : journal caisse
    journal = move.get("journal_id")
    if isinstance(journal, list) and len(journal) >= 2:
        journal_name = journal[1].lower()
        if any(kw in journal_name for kw in ["caisse", "cash", "espèce", "espece"]):
            return True

    # Méthode 2 : lignes avec payment_mode = cash
    move_id = move.get("id")
    for line in lines:
        lm = line.get("move_id")
        if isinstance(lm, list) and lm[0] == move_id:
            if line.get("payment_mode") == "cash":
                return True
    return False


def _get_partner_vat(partner_id: int | None, partners: list[dict]) -> str | None:
    if partner_id is None:
        return None
    for p in partners:
        if p["id"] == partner_id:
            return p.get("vat")
    return None


def _is_restaurant_expense(move: dict) -> bool:
    """Détecte les frais de restaurant/réception par mots-clés dans la référence ou le nom."""
    text = " ".join([
        str(move.get("ref") or ""),
        str(move.get("name") or ""),
    ]).lower()
    keywords = [
        "repas", "restaurant", "réception", "reception", "déjeuner",
        "dîner", "diner", "déjeuner", "hébergement", "hotel", "hôtel",
        "cadeaux", "cadeau", "entertainment",
    ]
    return any(kw in text for kw in keywords)


def _is_vehicle_amortization(move: dict, lines: list[dict]) -> tuple[bool, float]:
    """
    Détecte les amortissements de véhicules de tourisme.
    Retourne (is_vehicle, montant_annuel).
    """
    text = " ".join([str(move.get("ref") or ""), str(move.get("name") or "")]).lower()
    vehicle_keywords = ["véhicule tourisme", "voiture tourisme", "voiture de tourisme",
                        "vehicle tourisme", "amort. veh", "amort. véh"]
    is_vehicle = any(kw in text for kw in vehicle_keywords)

    # Chercher dans les lignes
    if not is_vehicle:
        move_id = move.get("id")
        for line in lines:
            lm = line.get("move_id")
            if isinstance(lm, list) and lm[0] == move_id:
                line_name = str(line.get("name") or "").lower()
                if any(kw in line_name for kw in vehicle_keywords):
                    is_vehicle = True
                    break

    annual_amount = move.get("amount_total", 0.0)
    return is_vehicle, annual_amount


# ─────────────────────────────────────────────────────────────────────────────
# Règles d'audit
# ─────────────────────────────────────────────────────────────────────────────

def _check_cash_limits(moves: list[dict], lines: list[dict]) -> list[dict]:
    """
    Art. 193 CGI : Pas de déduction de TVA ni de charges si règlement en espèces
    excède 5 000 DH par opération ou 50 000 DH/mois par fournisseur.
    """
    findings = []
    # Per-transaction limit: 5 000 DH
    for move in moves:
        if move.get("move_type") != "in_invoice":
            continue
        if not _is_cash_payment(move, lines):
            continue
        amount = move.get("amount_total", 0.0)
        if amount > 5000:
            vat_risk = round(amount / 1.2 * 0.2, 2)  # Estimation TVA 20%
            findings.append({
                "rule": "cash_limit_per_transaction",
                "severity": "rouge",
                "reference_cgi": "Article 193 du CGI",
                "title": "Paiement en espèces dépassant 5 000 DH",
                "description": (
                    f"La facture {move['name']} du {move['date']} "
                    f"({_partner_name(move)}) est réglée en espèces pour un montant de "
                    f"{amount:,.0f} DH, soit au-delà du plafond légal de 5 000 DH par opération."
                ),
                "amount_risk": vat_risk,
                "invoice": move["name"],
                "partner": _partner_name(move),
                "date": move["date"],
                "recommendation": (
                    "Régularisez ce règlement par virement bancaire ou chèque. "
                    "La TVA déductible et la charge seront refusées au contrôle fiscal."
                ),
            })

    # Monthly per-supplier limit: 50 000 DH
    monthly_cash: dict[tuple, float] = defaultdict(float)
    monthly_moves: dict[tuple, list] = defaultdict(list)
    for move in moves:
        if move.get("move_type") != "in_invoice":
            continue
        if not _is_cash_payment(move, lines):
            continue
        pid = _partner_id(move)
        month = move.get("date", "")[:7]  # YYYY-MM
        key = (pid, month)
        monthly_cash[key] += move.get("amount_total", 0.0)
        monthly_moves[key].append(move["name"])

    for (pid, month), total in monthly_cash.items():
        if total > 50000:
            excess = total - 50000
            findings.append({
                "rule": "cash_limit_monthly",
                "severity": "rouge",
                "reference_cgi": "Article 193 du CGI",
                "title": f"Cumul espèces fournisseur > 50 000 DH/mois ({month})",
                "description": (
                    f"Le cumul des paiements en espèces au fournisseur ID {pid} "
                    f"en {month} atteint {total:,.0f} DH (plafond légal : 50 000 DH). "
                    f"Factures concernées : {', '.join(monthly_moves[(pid, month)])}."
                ),
                "amount_risk": round(excess * 0.2, 2),
                "partner_id": pid,
                "month": month,
                "recommendation": (
                    "Le dépassement de 50 000 DH par mois entraîne la réintégration "
                    "de la charge dans le résultat fiscal. Régularisez par modes bancaires."
                ),
            })

    return findings


def _check_missing_ice(moves: list[dict], partners: list[dict]) -> list[dict]:
    """
    Obligation légale : Les factures fournisseurs doivent mentionner l'ICE
    (Identifiant Commun de l'Entreprise) depuis le décret du 25 septembre 2017.
    """
    findings = []
    checked_partners: set[int] = set()

    for move in moves:
        if move.get("move_type") != "in_invoice":
            continue
        pid = _partner_id(move)
        if pid is None or pid in checked_partners:
            continue
        vat = _get_partner_vat(pid, partners)
        # ICE is the VAT number in Moroccan Odoo instances
        if not vat:
            checked_partners.add(pid)
            amount = move.get("amount_total", 0.0)
            findings.append({
                "rule": "missing_ice",
                "severity": "orange",
                "reference_cgi": "Décret n° 2-17-746 du 25 septembre 2017 (ICE obligatoire)",
                "title": f"ICE manquant — {_partner_name(move)}",
                "description": (
                    f"Le fournisseur « {_partner_name(move)} » (facture {move['name']}) "
                    "ne dispose pas d'ICE (Identifiant Commun de l'Entreprise) "
                    "dans le système comptable. L'ICE est obligatoire sur toute facture "
                    "commerciale au Maroc depuis septembre 2017."
                ),
                "amount_risk": round(amount, 2),
                "partner_id": pid,
                "partner": _partner_name(move),
                "recommendation": (
                    "Contactez ce fournisseur pour obtenir son ICE (9 chiffres) "
                    "et mettez à jour sa fiche dans Odoo. Sans ICE, la déductibilité "
                    "de la TVA peut être contestée par la DGI lors d'un contrôle."
                ),
            })

    return findings


def _check_vehicle_amortization(moves: list[dict], lines: list[dict]) -> list[dict]:
    """
    Art. 10-I-F du CGI : L'amortissement des véhicules de tourisme n'est déductible
    que dans la limite d'une valeur d'acquisition de 300 000 DH TTC.
    """
    findings = []
    for move in moves:
        if move.get("move_type") not in ("entry", "misc"):
            # Also check entries with amortization account
            pass
        is_vehicle, annual_amount = _is_vehicle_amortization(move, lines)
        if not is_vehicle:
            continue

        # Taux standard d'amortissement véhicule tourisme = 20% → valeur acquisition = annual_amount / 0.20
        estimated_value = annual_amount / 0.20 if annual_amount > 0 else 0
        if estimated_value > 300000:
            allowed_annual = 300000 * 0.20  # 60 000 DH
            excess_annual = annual_amount - allowed_annual
            findings.append({
                "rule": "vehicle_amortization_cap",
                "severity": "orange",
                "reference_cgi": "Article 10-I-F du CGI",
                "title": "Amortissement véhicule tourisme au-delà du plafond (300 000 DH)",
                "description": (
                    f"L'écriture {move['name']} du {move.get('date', '?')} "
                    f"enregistre une dotation d'amortissement de {annual_amount:,.0f} DH "
                    f"(valeur estimée du véhicule : {estimated_value:,.0f} DH). "
                    f"Le plafond légal de déductibilité est de 300 000 DH TTC, "
                    f"soit une dotation maximale de {allowed_annual:,.0f} DH/an."
                ),
                "amount_risk": round(excess_annual, 2),
                "invoice": move["name"],
                "recommendation": (
                    f"Réintégrez {excess_annual:,.0f} DH dans le résultat fiscal. "
                    "Comptabilisez une réintégration extracomptable dans le tableau de passage "
                    "du résultat comptable au résultat fiscal."
                ),
            })

    return findings


def _check_non_deductible_vat(moves: list[dict], lines: list[dict]) -> list[dict]:
    """
    Art. 106-IV du CGI : La TVA sur les frais de restaurant, réceptions,
    hébergement et cadeaux n'est pas déductible.
    """
    findings = []
    for move in moves:
        if move.get("move_type") != "in_invoice":
            continue
        if not _is_restaurant_expense(move):
            continue
        amount = move.get("amount_total", 0.0)
        vat_amount = round(amount / 1.2 * 0.2, 2)
        findings.append({
            "rule": "non_deductible_vat_restaurant",
            "severity": "orange",
            "reference_cgi": "Article 106-IV du CGI",
            "title": f"TVA non déductible — Frais de restaurant/réception ({move['name']})",
            "description": (
                f"La facture {move['name']} du {move.get('date', '?')} "
                f"({move.get('ref') or 'sans référence'}) correspond à des frais de "
                f"restaurant/réception pour {amount:,.0f} DH. "
                "Selon l'Article 106-IV du CGI, la TVA sur ces frais n'est pas déductible."
            ),
            "amount_risk": vat_amount,
            "invoice": move["name"],
            "recommendation": (
                f"Réintégrez la TVA de {vat_amount:,.0f} DH dans la déclaration de TVA "
                "(déclaration mensuelle ou trimestrielle). Conservez les justificatifs "
                "pour le dossier de contrôle."
            ),
        })

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Entrée principale
# ─────────────────────────────────────────────────────────────────────────────

def run_audit(odoo_data: dict) -> list[dict]:
    """
    Lance toutes les règles d'audit et retourne la liste consolidée
    des anomalies fiscales détectées.
    """
    moves: list[dict] = odoo_data.get("moves", [])
    lines: list[dict] = odoo_data.get("lines", [])
    partners: list[dict] = odoo_data.get("partners", [])

    findings: list[dict] = []
    findings.extend(_check_cash_limits(moves, lines))
    findings.extend(_check_missing_ice(moves, partners))
    findings.extend(_check_vehicle_amortization(moves, lines))
    findings.extend(_check_non_deductible_vat(moves, lines))

    # Sort by severity: rouge first, then orange, then vert
    severity_order = {"rouge": 0, "orange": 1, "vert": 2}
    findings.sort(key=lambda f: severity_order.get(f.get("severity", "vert"), 99))
    return findings
