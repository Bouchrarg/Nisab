"""
reconciliation.py — Détection des déclarations manquantes (Module 1).

## Ce que « réconciliation » veut dire ici

Le cahier des charges demande « réconciliation, détection des pièces
manquantes » sans préciser à quel niveau. Deux lectures étaient possibles :

  1. Croiser les obligations déclaratives attendues avec ce qu'on trouve dans
     les données comptables : « la TVA de mars était due le 20 avril, aucune
     trace de dépôt ni de paiement ».
  2. Vérifier que chaque écriture a sa facture justificative (Art. 146 CGI).

C'est la lecture 1 qui est implémentée. La lecture 2 suppose de disposer des
pièces justificatives elles-mêmes — ce qu'un export CSV ne contient jamais.
Elle est identifiée comme extension et documentée comme telle dans le rapport,
pas silencieusement oubliée.

## Pourquoi ce module est court

Parce qu'il ne calcule presque rien de neuf. tax_calendar.py sait déjà quelles
obligations tombent à quelle date pour un régime donné, et sait déjà qualifier
chaque échéance en `paye` / `en_retard` / `a_venir` en croisant les écritures.
Réconcilier, c'est lire ce résultat sur une fenêtre qui inclut le passé, au
lieu de ne regarder que ce qui reste à faire.

La seule chose qu'il fallait corriger pour que ça marche : get_calendar_events
ne générait que des échéances futures. On ne peut pas constater qu'une
déclaration manque si on ne regarde jamais en arrière — d'où le paramètre
`nb_months_back` ajouté là-bas.

## Statut non-RAG, hérité et assumé

tax_calendar.py est volontairement hors du pipeline RAG : ses références
légales sont des littéraux écrits à la main, marqués `sourced: False`. Tout ce
que produit ce module en hérite. Concrètement :

  - la réponse porte `"sourced": false` en clair ;
  - aucune ligne `Citation` n'est jamais créée ici ;
  - le frontend doit afficher ces références autrement qu'une citation vérifiée.

C'est la règle d'architecture du projet : une affirmation non sourcée a le
droit d'exister, à condition de ne jamais se faire passer pour une affirmation
sourcée.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Declaration, Dossier
from app.tax_calendar import get_calendar_events

#: Profondeur d'analyse rétrospective. 12 mois couvre un exercice complet, donc
#: au moins une occurrence de chaque obligation, y compris annuelle (IS, TP).
FENETRE_MOIS_ARRIERE = 12


def _periode_de(evenement: dict) -> str:
    """
    Période de rattachement d'une échéance, au format 'YYYY-MM'.

    On prend le mois de l'échéance elle-même, pas celui de l'obligation :
    c'est la convention déjà retenue par get_calendar_events pour qualifier
    `payment_status`, et deux conventions différentes pour la même notion
    finiraient inévitablement par diverger.
    """
    return evenement["date"][:7]


def _declarations_deposees(db: Session, dossier_id: uuid.UUID) -> set[tuple[str, str]]:
    """
    Couples (type, période) déjà déposés d'après la table `declaration`.

    Cette table existe depuis la Phase 1 et n'est encore alimentée par aucun
    flux : elle est le point d'entrée prévu pour une saisie manuelle
    (« j'ai déposé, tu peux arrêter de me le signaler »). Tant qu'elle est
    vide, la détection repose uniquement sur les traces comptables, ce qui est
    le comportement voulu et non un bug.
    """
    lignes = db.execute(
        select(Declaration).where(
            Declaration.dossier_id == dossier_id,
            Declaration.statut.in_(("deposee", "payee")),
        )
    ).scalars().all()
    return {(d.type_declaration, d.periode) for d in lignes}


def rapprochement_declaratif(
    db: Session,
    dossier_id: uuid.UUID,
    dossier: Dossier,
    data: dict | None,
) -> dict:
    """
    Compare les obligations déclaratives échues aux traces disponibles.

    Une échéance est considérée **couverte** si l'un des deux signaux est
    présent :
      - une ligne `declaration` déposée pour ce type et cette période ;
      - une écriture comptable qui ressemble à un paiement d'impôt sur ce mois
        (détection par mots-clés, voir tax_calendar.detect_tax_payment_months).

    Sinon elle est **manquante**. Le second signal est une heuristique, pas une
    preuve : d'où le vocabulaire employé côté interface — « aucune trace de »,
    jamais « vous n'avez pas déclaré ». Nisab signale, le comptable tranche.
    """
    aujourdhui = date.today()

    evenements = get_calendar_events(
        regime=dossier.regime_is,
        tva_regime=dossier.regime_tva,
        exercise_end_month=dossier.exercice_cloture_mois,
        odoo_data=data,
        nb_months_back=FENETRE_MOIS_ARRIERE,
    )

    deposees = _declarations_deposees(db, dossier_id)

    manquantes: list[dict] = []
    couvertes: list[dict] = []

    for ev in evenements:
        if ev["date"] >= aujourdhui.isoformat():
            continue  # pas encore échu : c'est du calendrier, pas de la réconciliation

        periode = _periode_de(ev)
        declaree = (ev["category"], periode) in deposees
        payee = ev.get("payment_status") == "paye"

        ligne = {
            "date_echeance": ev["date"],
            "periode": periode,
            "categorie": ev["category"],
            "titre": ev["title"],
            "penalite": ev.get("penalty"),
            "reference_legale": ev.get("legal_article"),
            "signal": "declaration_saisie" if declaree else ("paiement_detecte" if payee else None),
            # Rappel de statut par ligne, pour que le frontend n'ait pas à
            # se souvenir de la règle globale de non-sourçage.
            "sourced": False,
        }

        (couvertes if (declaree or payee) else manquantes).append(ligne)

    manquantes.sort(key=lambda e: e["date_echeance"])
    par_categorie: dict[str, int] = {}
    for m in manquantes:
        par_categorie[m["categorie"]] = par_categorie.get(m["categorie"], 0) + 1

    return {
        "echeances_manquantes": manquantes,
        "echeances_couvertes": couvertes,
        "nb_manquantes": len(manquantes),
        "nb_couvertes": len(couvertes),
        "par_categorie": par_categorie,
        "fenetre_mois": FENETRE_MOIS_ARRIERE,
        "a_des_donnees_comptables": bool(data),
        # Le champ qui empêche cette sortie d'être confondue avec une analyse RAG.
        "sourced": False,
        "avertissement": (
            "Analyse fondée sur le calendrier légal et sur la détection de "
            "paiements dans les écritures — références non issues du corpus "
            "RAG versionné, et absence de trace ne vaut pas absence de dépôt."
        ),
    }
