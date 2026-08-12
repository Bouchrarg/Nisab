"""
simulation_pdf.py — Export PDF du rapport de simulation de contrôle (Module 4).

Génère un PDF côté backend (fpdf2). Ne relance rien : même principe anti-hallucination que
control_simulator.py, on ne fait que mettre en page ce qui existe déjà.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fpdf import FPDF

from app.models import Dossier, SimulationControle

RAPPEL_USAGE_INTERNE = (
    "Usage interne uniquement -- ce rapport reste dans votre cabinet, "
    "rien n'est transmis a la DGI."
)


_LATIN1_REPLACEMENTS = {
    "—": "-",   # —
    "–": "-",   # –
    "‘": "'",   # '
    "’": "'",   # '
    "“": '"',   # "
    "”": '"',   # "
    "…": "...",  # …
    "°": "deg.",  # °
}


def _latin1_safe(text: str | None) -> str:
    if not text:
        return ""
    for src, dst in _LATIN1_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _format_dh(montant: float) -> str:
    return f"{montant:,.2f} DH".replace(",", " ").replace(".", ",")


class _SimulationPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def build_simulation_pdf(dossier: Dossier, simulation: SimulationControle) -> bytes:
    rapport = simulation.rapport_json or {}
    plan = simulation.plan_remediation_json or {}
    themes = rapport.get("themes", [])
    plan_by_theme = {t["theme"]: t.get("plan_remediation", "") for t in plan.get("themes", [])}
    exposition_totale = sum(float(t.get("exposition_totale_mad") or 0) for t in themes)

    pdf = _SimulationPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # En-tête
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Nisab -- Simulation de controle fiscal", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 7, _latin1_safe(dossier.raison_sociale), new_x="LMARGIN", new_y="NEXT")

    date_simulation = simulation.created_at.strftime("%d/%m/%Y %H:%M") if simulation.created_at else "N/A"
    date_generation = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Simulation du {date_simulation} (UTC) -- document genere le {date_generation} (UTC)",
              new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Bandeau rappel
    pdf.set_fill_color(255, 244, 214)
    pdf.set_text_color(120, 84, 0)
    pdf.set_font("Helvetica", "B", 9)
    pdf.multi_cell(0, 6, _latin1_safe(RAPPEL_USAGE_INTERNE), fill=True)
    pdf.set_text_color(30, 30, 30)
    pdf.ln(4)

    if not themes:
        pdf.set_font("Helvetica", "", 11)
        message = rapport.get("message") or "Aucune alerte de risque ouverte -- rien a simuler pour le moment."
        pdf.multi_cell(0, 7, _latin1_safe(message), new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    # KPIs
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(95, 8, f"Themes examines : {len(themes)}", border=1)
    pdf.cell(95, 8, f"Exposition totale : {_latin1_safe(_format_dh(exposition_totale))}", border=1,
              new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    for theme in themes:
        nom = theme.get("theme", "")
        nb_alertes = theme.get("nb_alertes", 0)
        articles = ", ".join(theme.get("articles_cites") or [])
        exposition = float(theme.get("exposition_totale_mad") or 0)
        argumentaire = theme.get("argumentaire", "")
        plan_remediation = plan_by_theme.get(nom, "")

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_fill_color(235, 238, 242)
        pdf.multi_cell(0, 8, _latin1_safe(nom), fill=True, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(90, 90, 90)
        sous_titre = f"{nb_alertes} anomalie(s) liee(s)"
        if articles:
            sous_titre += f" -- {articles}"
        sous_titre += f" -- exposition : {_format_dh(exposition)}"
        pdf.multi_cell(0, 6, _latin1_safe(sous_titre), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 30)
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Argumentaire de defense", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9.5)
        pdf.multi_cell(0, 5.5, _latin1_safe(argumentaire), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

        if plan_remediation:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, "Plan de remediation", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9.5)
            pdf.multi_cell(0, 5.5, _latin1_safe(plan_remediation), new_x="LMARGIN", new_y="NEXT")

        pdf.ln(6)

    return bytes(pdf.output())
