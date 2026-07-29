"""
tax_calendar.py — Calendrier des obligations fiscales marocaines pour Nisab.

Calcule les prochaines échéances en tenant compte du régime IS et du régime TVA
de la société. Les dates sont calculées dynamiquement à partir de la date actuelle.

Obligations couvertes :
  - TVA mensuelle (déclaration avant le 20 du mois suivant)
  - TVA trimestrielle (déclaration avant le 20 du mois suivant le trimestre)
  - Acomptes IS trimestriels (3e, 6e, 9e, 12e mois de l'exercice)
  - IR/CNSS mensuel (salaires)
  - Taxe professionnelle (TP) — janvier
  - Déclaration annuelle IS (3 mois après clôture d'exercice)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal


def _next_occurrence_of_day(year: int, month: int, day: int) -> date:
    """Retourne la date pour le jour donné dans le mois/année, ou le dernier jour du mois."""
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def get_calendar_events(
    regime: Literal["normal", "simplifie"] = "normal",
    tva_regime: Literal["mensuel", "trimestriel"] = "mensuel",
    exercise_end_month: int = 12,
    nb_months_ahead: int = 6,
    odoo_data: dict | None = None,
) -> list[dict]:
    """
    Génère les prochaines échéances fiscales pour les 'nb_months_ahead' prochains mois.
    Si odoo_data est fourni, croise les écritures comptables pour détecter les paiements effectués.
    """
    today = date.today()
    events: list[dict] = []

    # Extraire les dates des écritures de paiement de taxes si odoo_data est présent
    tax_payments_detected = set()
    if odoo_data:
        moves = odoo_data.get("moves", [])
        for m in moves:
            ref = str(m.get("ref") or "").lower()
            name = str(m.get("name") or "").lower()
            mdate = m.get("date", "")
            # Détections par mots-clés d'impôt et règlement
            if any(kw in ref or kw in name for kw in ["tva", "is", "acompte", "ir", "taxe", "impot"]):
                if mdate:
                    tax_payments_detected.add(mdate[:7])  # YYYY-MM

    # Génère les mois à couvrir
    months_to_cover = []
    y, m = today.year, today.month
    for _ in range(nb_months_ahead + 1):
        months_to_cover.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    # ─── TVA ───────────────────────────────────────────────────
    if tva_regime == "mensuel":
        for (yr, mo) in months_to_cover:
            # TVA du mois M à déclarer avant le 20 du mois M+1
            if mo == 12:
                due_year, due_month = yr + 1, 1
            else:
                due_year, due_month = yr, mo + 1
            due = _next_occurrence_of_day(due_year, due_month, 20)
            if due >= today:
                events.append({
                    "date": due.isoformat(),
                    "title": f"TVA mensuelle — Déclaration {_month_name(mo)} {yr}",
                    "description": (
                        f"Dépôt de la déclaration TVA du mois de {_month_name(mo)} {yr} "
                        "et paiement de la TVA collectée nette. "
                        "Référence : Art. 110 et suivants du CGI."
                    ),
                    "category": "TVA",
                    "urgency": _urgency(due, today),
                    "penalty": "Majoration de 15% + 5% par mois de retard (Art. 208 CGI)",
                    "legal_source": "CGI 2026",
                    "legal_article": "Article 110 du CGI",
                    "doc_version": "v2026.1 (BO n° 7365)",
                })
    elif tva_regime == "trimestriel":
        for quarter, months in [(1, [1, 2, 3]), (2, [4, 5, 6]),
                                  (3, [7, 8, 9]), (4, [10, 11, 12])]:
            last_month = months[-1]
            for (yr, _) in months_to_cover:
                # TVA trimestrielle due le 20 du mois suivant la fin du trimestre
                due_month = last_month + 1 if last_month < 12 else 1
                due_year = yr if last_month < 12 else yr + 1
                due = _next_occurrence_of_day(due_year, due_month, 20)
                if due >= today and (yr, last_month) in months_to_cover:
                    events.append({
                        "date": due.isoformat(),
                        "title": f"TVA trimestrielle — T{quarter} {yr}",
                        "description": (
                            f"Dépôt de la déclaration TVA du {quarter}e trimestre {yr} "
                            f"({_month_name(months[0])} au {_month_name(last_month)}). "
                            "Référence : Art. 110 du CGI."
                        ),
                        "category": "TVA",
                        "urgency": _urgency(due, today),
                        "penalty": "Majoration de 15% + 5% par mois de retard (Art. 208 CGI)",
                        "legal_source": "CGI 2026",
                        "legal_article": "Article 110 du CGI",
                        "doc_version": "v2026.1 (BO n° 7365)",
                    })
                    break

    # ─── Acomptes IS (régime normal) ────────────────────────────
    if regime == "normal":
        # Les 4 acomptes IS sont dus à la fin du 3e, 6e, 9e et 12e mois de l'exercice
        acompte_months = [
            exercise_end_month - 9,
            exercise_end_month - 6,
            exercise_end_month - 3,
            exercise_end_month,
        ]
        acompte_months = [m if m > 0 else m + 12 for m in acompte_months]

        for yr in set(y for y, m in months_to_cover):
            for am in acompte_months:
                # Acompte IS dû le dernier jour du mois (ou au plus tard le 31)
                due = _next_occurrence_of_day(yr, am, 31)
                if due >= today and due <= today + timedelta(days=nb_months_ahead * 31):
                    events.append({
                        "date": due.isoformat(),
                        "title": f"Acompte IS — {_month_name(am)} {yr}",
                        "description": (
                            f"Versement d'un acompte provisionnel d'IS avant le 31 {_month_name(am)} {yr}. "
                            "L'acompte = 25% de l'IS théorique de l'exercice précédent "
                            "ou de la Cotisation Minimale si supérieure. "
                            "Référence : Art. 170 du CGI."
                        ),
                        "category": "IS",
                        "urgency": _urgency(due, today),
                        "penalty": "Majoration de 10% sur le montant non payé (Art. 208 CGI)",
                        "legal_source": "CGI 2026",
                        "legal_article": "Article 170 du CGI",
                        "doc_version": "v2026.1 (BO n° 7365)",
                    })

    # ─── IR/CNSS mensuel (retenues sur salaires) ────────────────
    for (yr, mo) in months_to_cover:
        if mo == 12:
            due_year, due_month = yr + 1, 1
        else:
            due_year, due_month = yr, mo + 1
        # IR sur salaires : avant le 20 du mois suivant
        due_ir = _next_occurrence_of_day(due_year, due_month, 20)
        if due_ir >= today:
            events.append({
                "date": due_ir.isoformat(),
                "title": f"IR/Salaires (RAS) — {_month_name(mo)} {yr}",
                "description": (
                    f"Déclaration et versement des retenues à la source (IR) sur les salaires "
                    f"de {_month_name(mo)} {yr} avant le 20 {_month_name(due_month)} {due_year}. "
                    "Référence : Art. 79 et 157 du CGI."
                ),
                "category": "IR",
                "urgency": _urgency(due_ir, today),
                "penalty": "Majoration de 10% + intérêts de retard (Art. 208 CGI)",
                "legal_source": "CGI 2026",
                "legal_article": "Article 157 du CGI",
                "doc_version": "v2026.1 (BO n° 7365)",
            })

    # ─── Taxe Professionnelle (TP) ───────────────────────────────
    for (yr, mo) in months_to_cover:
        if mo == 1:
            due = _next_occurrence_of_day(yr, 1, 31)
            if due >= today:
                events.append({
                    "date": due.isoformat(),
                    "title": f"Taxe Professionnelle (TP) — {yr}",
                    "description": (
                        f"Paiement de la Taxe Professionnelle {yr} avant le 31 janvier. "
                        "Applicable à toutes les entreprises ayant un établissement professionnel au Maroc. "
                        "Référence : Loi n° 47-06 relative à la fiscalité des collectivités locales."
                    ),
                    "category": "Taxes Locales",
                    "urgency": _urgency(due, today),
                    "penalty": "Majoration de 10% pour paiement tardif",
                    "legal_source": "Loi 47-06",
                    "legal_article": "Loi 47-06 Collectivités Locales",
                    "doc_version": "v2026.1",
                })

    # ─── Déclaration annuelle IS ────────────────────────────────
    # Dépôt des états de synthèse : 3 mois après la clôture
    for yr in set(y for y, m in months_to_cover):
        close_date = _next_occurrence_of_day(yr - 1, exercise_end_month, 31)
        due_annual = date(close_date.year, close_date.month, 1)
        # + 3 mois
        m3 = close_date.month + 3
        y3 = close_date.year
        if m3 > 12:
            m3 -= 12
            y3 += 1
        due_annual = _next_occurrence_of_day(y3, m3, 31)
        if today <= due_annual <= today + timedelta(days=nb_months_ahead * 31):
            events.append({
                "date": due_annual.isoformat(),
                "title": f"Déclaration annuelle IS — Exercice {yr - 1}",
                "description": (
                    f"Dépôt de la liasse fiscale (états de synthèse, compte de résultat, bilan) "
                    f"pour l'exercice clos le {_month_name(exercise_end_month)} {yr - 1}. "
                    f"Délai : 3 mois après la clôture, soit avant le {due_annual.isoformat()}. "
                    "Référence : Art. 20 du CGI."
                ),
                "category": "IS",
                "urgency": _urgency(due_annual, today),
                "penalty": "Majoration de 15% sur l'IS dû (Art. 184 CGI)",
                "legal_source": "CGI 2026",
                "legal_article": "Article 20 du CGI",
                "doc_version": "v2026.1 (BO n° 7365)",
            })

    # Trier par date
    events.sort(key=lambda e: e["date"])
    # Dédupliquer (même date + titre) et qualifier le statut de paiement
    seen = set()
    unique_events = []
    for e in events:
        key = (e["date"], e["title"])
        if key not in seen:
            seen.add(key)
            # Qualification du statut de paiement
            due_date = date.fromisoformat(e["date"])
            due_month_key = e["date"][:7]
            if due_month_key in tax_payments_detected:
                e["payment_status"] = "paye"
            elif due_date < today:
                e["payment_status"] = "en_retard"
            else:
                e["payment_status"] = "a_venir"

            unique_events.append(e)
    return unique_events


def _month_name(month: int) -> str:
    names = ["", "janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return names[month] if 1 <= month <= 12 else "?"


def _urgency(due: date, today: date) -> str:
    delta = (due - today).days
    if delta <= 7:
        return "critique"
    elif delta <= 20:
        return "urgent"
    elif delta <= 45:
        return "normal"
    return "planifié"
