"""
tax_calendar.py — Calendrier des obligations fiscales marocaines pour Nisab.

Calcule les prochaines échéances en tenant compte du régime IS et du régime TVA
de la société. Les dates sont calculées dynamiquement à partir de la date actuelle.

AVERTISSEMENT ARCHITECTURE (à lire avant de faire confiance à ce fichier) :
Contrairement aux modules 2 (assistant fiscal) et 3 (détection de risques),
ce module N'EST PAS RAG-only. Toutes les valeurs `legal_article`,
`legal_source`, `doc_version` et `penalty` ci-dessous sont des LITTÉRAUX
PYTHON écrits à la main, jamais vérifiés contre la table `articles` du
corpus versionné. Chaque événement retourné porte "sourced": False pour
que le frontend puisse afficher ces références différemment d'une citation
RAG vérifiée (voir CalendarEvent.jsx). Les dates limites elles-mêmes (le
20, le 10...) reflètent des règles CGI/CNSS bien établies et stables, mais
n'ont pas non plus été revérifiées ligne par ligne à chaque mise à jour de
ce fichier — à auditer avant une communication publique/soutenance qui s'y
appuierait comme preuve de rigueur RAG.

Obligations couvertes :
  - TVA mensuelle (déclaration avant le 20 du mois suivant)
  - TVA trimestrielle (déclaration avant le 20 du mois suivant le trimestre)
  - Acomptes IS trimestriels (3e, 6e, 9e, 12e mois de l'exercice)
  - IR/RAS mensuel (retenues sur salaires)
  - CNSS mensuel (déclaration de salaires, portail Damancom)
  - Taxe professionnelle (TP) — janvier
  - Déclaration annuelle IS (3 mois après clôture d'exercice)
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal


def _next_occurrence_of_day(year: int, month: int, day: int) -> date:
    """Retourne la date pour le jour donné dans le mois/année, ou le dernier jour du mois."""
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


CATEGORIES_DECLARATION = {"TVA", "IS", "IR", "CNSS", "Taxes Locales"}


_MOTS_CLES_PAIEMENT: list[tuple[str, str | None]] = [
    ("tva", "TVA"),
    ("is", "IS"),
    ("acompte", "IS"),
    ("liasse", "IS"),
    ("ir", "IR"),
    ("ras", "IR"),
    ("salaire", "IR"),
    ("cnss", "CNSS"),
    ("damancom", "CNSS"),
    ("taxe professionnelle", "Taxes Locales"),
    ("tp", "Taxes Locales"),
    ("impot", None),
    ("impôt", None),
    ("dgi", None),
    ("simpl", None),
]


def detect_tax_payment_months(odoo_data: dict | None) -> set[tuple[str | None, str]]:
    """
    Détecte les mois où des paiements d'impôt ont été effectués, selon les écritures comptables.
    """
    detected: set[tuple[str | None, str]] = set()
    if not odoo_data:
        return detected

    for m in odoo_data.get("moves", []):
        texte = f"{m.get('ref') or ''} {m.get('name') or ''}".lower()
        mdate = m.get("date", "")
        if not mdate:
            continue
        mois = str(mdate)[:7]
        for mot, categorie in _MOTS_CLES_PAIEMENT:
            # \b...\b : « ir » ne doit pas matcher « virement ».
            if re.search(rf"\b{re.escape(mot)}\b", texte):
                detected.add((categorie, mois))
    return detected


def paiement_detecte(paiements: set[tuple[str | None, str]], categorie: str, mois: str) -> bool:
    """Un paiement de cette catégorie (ou non catégorisé) existe-t-il ce mois-là ?"""
    return (categorie, mois) in paiements or (None, mois) in paiements


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Décale un couple (année, mois) de `delta` mois, positif ou négatif."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


# ─── Exposition TVA (base chiffrable pour le ROI échéances) ────────────
#
# Seule la TVA a une base réellement calculable depuis le pivot comptable :
# IS (acompte = 25% de l'IS théorique de l'EXERCICE PRÉCÉDENT, une donnée
# que Nisab n'a pas), IR/CNSS (masse salariale, absente du pivot — ce sont
# des écritures d'ACHATS/VENTES, pas de paie) et Taxe Professionnelle
# (valeur locative, hors pivot) n'ont pas d'équivalent ici. Leur exposition
# reste donc du COMPTAGE (échéance suivie), jamais un montant en DH inventé
# — même discipline que regles_montant.py : pas de zéro silencieux quand on
# ne sait pas, jamais de montant sans base vérifiable.
#
# Préfixes CGNC des comptes de TVA. 5 chiffres dans ce corpus (34552, pas le
# "3455" officiel à 4 chiffres) — même convention de préfixe par chaîne que
# odoo_connector.resolve_account() pour les comptes CGNC, appliquée ici en
# str.startswith().
PREFIXE_TVA_DEDUCTIBLE = "3455"
PREFIXE_TVA_FACTUREE = "4455"

#: Majoration MINIMALE en cas de déclaration/paiement manqué (Art. 208 CGI :
#: 15% + 5% par mois de retard supplémentaire). On ne chiffre que ce
#: plancher : le retard réel d'une échéance qui n'a pas encore eu lieu n'est
#: pas connu, donc pas les 5%/mois — d'où `categorie_montant =
#: "calculable_hypothese"` plutôt que "calculable" sur le résultat.
TAUX_MAJORATION_TVA_PLANCHER = 0.15


def _montant_tva_periode(odoo_data: dict | None, mois: list[str]) -> dict:
    """
    TVA due = TVA facturée (ventes) - TVA déductible (achats), sur les
    LIGNES dont la date (`line["date"]`, pas la date du move) tombe dans un
    des mois de `mois` (liste de "YYYY-MM").

    Ne renvoie JAMAIS "calculable" à 0 DH par défaut : "non_calculable" si
    aucune ligne de compte TVA (34550/44550...) n'a été trouvée sur la
    période — absence de donnée (pivot CSV minimal, société en franchise de
    TVA...), pas un fait vérifié. Cf. regles_montant.py, même discipline.
    """
    if not odoo_data:
        return {"categorie_montant": "non_calculable", "montant_base": None, "detail": None}

    facturee = 0.0
    deductible = 0.0
    trouve = False
    for line in odoo_data.get("lines", []):
        line_mois = str(line.get("date") or "")[:7]
        if line_mois not in mois:
            continue
        compte = str((line.get("account_id") or [None])[0] or "")
        if compte.startswith(PREFIXE_TVA_FACTUREE):
            facturee += float(line.get("credit") or 0)
            trouve = True
        elif compte.startswith(PREFIXE_TVA_DEDUCTIBLE):
            deductible += float(line.get("debit") or 0)
            trouve = True

    if not trouve:
        return {"categorie_montant": "non_calculable", "montant_base": None, "detail": None}

    net = round(facturee - deductible, 2)
    detail_base = (
        f"TVA facturée {facturee:,.2f} DH - TVA déductible {deductible:,.2f} DH "
        f"= {net:,.2f} DH".replace(",", " ")
    )
    if net <= 0:
        # Crédit de TVA reportable : rien à payer, donc aucune pénalité de
        # paiement possible — la déclaration reste due, mais l'EXPOSITION
        # financière (ce que ce champ mesure) est nulle, pas "inconnue".
        return {
            "categorie_montant": "calculable",
            "montant_base": 0.0,
            "detail": detail_base + " (crédit de TVA, aucun montant à risque)",
        }

    exposition = round(net * TAUX_MAJORATION_TVA_PLANCHER, 2)
    return {
        "categorie_montant": "calculable_hypothese",
        "montant_base": exposition,
        "detail": (
            f"{detail_base}. Exposition en cas de retard (plancher Art. 208, 15%) : "
            f"{exposition:,.2f} DH — hors majoration additionnelle de 5%/mois de retard, "
            f"non chiffrable avant que le retard réel soit connu.".replace(",", " ")
        ),
    }


def get_calendar_events(
    regime: Literal["normal", "simplifie"] = "normal",
    tva_regime: Literal["mensuel", "trimestriel"] = "mensuel",
    exercise_end_month: int = 12,
    nb_months_ahead: int = 6,
    odoo_data: dict | None = None,
    nb_months_back: int = 0,
) -> list[dict]:
    """
    Retourne la liste des événements fiscaux à venir pour le calendrier, en tenant compte
    du régime IS et du régime TVA de la société, ainsi que des paiements détectés
    dans les écritures comptables Odoo.
    """
    today = date.today()
    events: list[dict] = []

    # Borne basse de la fenêtre : aujourd'hui, ou le 1er du mois situé
    # nb_months_back mois en arrière.
    if nb_months_back > 0:
        start_y, start_m = _shift_month(today.year, today.month, -nb_months_back)
        horizon_start = date(start_y, start_m, 1)
    else:
        horizon_start = today

    tax_payments_detected = detect_tax_payment_months(odoo_data)

    # Génère les mois à couvrir, du plus ancien au plus récent
    months_to_cover = []
    y, m = _shift_month(today.year, today.month, -nb_months_back)
    for _ in range(nb_months_back + nb_months_ahead + 1):
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
            if due >= horizon_start:
                tva = _montant_tva_periode(odoo_data, [f"{yr}-{mo:02d}"])
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
                    # Exposition chiffrée depuis les écritures (ROI échéances,
                    # cf. app.roi) — "non_calculable" si aucune ligne de TVA
                    # n'est trouvée sur le mois, jamais un 0 silencieux.
                    "categorie_montant": tva["categorie_montant"],
                    "montant_base": tva["montant_base"],
                    "montant_detail": tva["detail"],
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
                if due >= horizon_start and (yr, last_month) in months_to_cover:
                    tva = _montant_tva_periode(odoo_data, [f"{yr}-{m:02d}" for m in months])
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
                        "categorie_montant": tva["categorie_montant"],
                        "montant_base": tva["montant_base"],
                        "montant_detail": tva["detail"],
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
                if horizon_start <= due <= today + timedelta(days=nb_months_ahead * 31):
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
        if due_ir >= horizon_start:
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

    # ─── CNSS mensuel (déclaration de salaires + cotisations, portail DAMANCOM) ───
    # Distinct de l'IR/RAS ci-dessus : échéance différente (le 10, pas le 20),
    # organisme différent (CNSS, pas DGI), et le cahier des charges nomme
    # explicitement "calendrier TVA/IS/IR/CNSS (SIMPL)" comme 4 pistes séparées —
    # avant cette correction, seul un commentaire mentionnait CNSS, aucune
    # échéance n'était réellement générée pour cette catégorie.
    for (yr, mo) in months_to_cover:
        if mo == 12:
            due_year, due_month = yr + 1, 1
        else:
            due_year, due_month = yr, mo + 1
        due_cnss = _next_occurrence_of_day(due_year, due_month, 10)
        if due_cnss >= horizon_start:
            events.append({
                "date": due_cnss.isoformat(),
                "title": f"CNSS — Déclaration de salaires {_month_name(mo)} {yr}",
                "description": (
                    f"Déclaration de salaires (DS) et versement des cotisations CNSS pour "
                    f"{_month_name(mo)} {yr} avant le 10 {_month_name(due_month)} {due_year}, "
                    "via le portail DAMANCOM."
                ),
                "category": "CNSS",
                "urgency": _urgency(due_cnss, today),
                "penalty": "Pénalité de 3% le 1er mois de retard, puis 1% par mois supplémentaire",
                "legal_source": "CNSS",
                # Court, même gabarit que les autres `legal_article` (ex.
                # "Article 110 du CGI") : le disclaimer "non vérifié" vit déjà
                # dans le bandeau d'info de CalendarPage ET dans la texture
                # visuelle du chip (bordure pointillée, cf. CalendarEvent.jsx)
                # — le répéter en toutes lettres ici ne faisait que produire
                # une pastille 5x plus large que ses voisines sur la même page.
                "legal_article": "Réglementation CNSS",
                "doc_version": "DAMANCOM",
            })
    for (yr, mo) in months_to_cover:
        if mo == 1:
            due = _next_occurrence_of_day(yr, 1, 31)
            if due >= horizon_start:
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
        if horizon_start <= due_annual <= today + timedelta(days=nb_months_ahead * 31):
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
    # Marque explicitement que ces références légales sont des littéraux
    # non vérifiés contre le corpus (voir avertissement en tête de fichier) —
    # le frontend s'appuie sur ce champ pour ne pas les afficher comme une
    # citation RAG vérifiée (voir CalendarEvent.jsx).
    for e in events:
        e["sourced"] = False
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
            if paiement_detecte(tax_payments_detected, e["category"], due_month_key):
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
