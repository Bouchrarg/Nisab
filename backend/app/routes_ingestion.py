"""
routes_ingestion.py — Alimentation d'un dossier autrement que par Odoo (Phase 5).

Routeur séparé de routes_dossiers.py, qui dépasse déjà 700 lignes. Même préfixe
`/dossiers` : du point de vue du client HTTP, rien ne trahit qu'il y a deux
modules derrière, et c'est voulu — le découpage est une commodité de lecture,
pas un choix d'API.

Toutes les routes passent par `get_tenant_db` (contexte RLS posé) et par
`get_dossier_or_404` (droit d'accès au dossier vérifié). Aucune n'utilise
`get_db` seul.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.connectors import ConnectorError, FichierAccountingConnector
from app.connectors.fichier_connecteur import MODELE_CSV
from app.connectors.sage_connecteur import SageAccountingConnector
from app.db_session import get_tenant_db
from app.models import Declaration, TypeConnexion
from app.ocr_extraction import EXTENSIONS_ACCEPTEES as EXTENSIONS_OCR
from app.ocr_extraction import OcrError, extraire_champs_facture
from app.reconciliation import rapprochement_declaratif
# Réutilisation assumée des deux helpers de persistance de routes_dossiers :
# ils écrivent le snapshot comptable et la ligne ConnexionComptable, exactement
# ce qu'un import doit faire. Les redéfinir ici aurait créé deux façons
# d'alimenter un dossier, donc deux comportements à maintenir en phase.
from app.routes_dossiers import (
    _fusionner_donnees_comptables,
    _get_active_accounting_data,
    _persist_accounting_data,
)
from app.tax_calendar import CATEGORIES_DECLARATION
from app.tenant_guard import get_dossier_or_404

router = APIRouter(prefix="/dossiers", tags=["Ingestion"])

#: Plafond d'upload. Un export comptable annuel de PME pèse quelques centaines
#: de Ko ; 10 Mo laisse une marge très large tout en évitant qu'un fichier
#: aberrant soit entièrement chargé en mémoire.
TAILLE_MAX_OCTETS = 10 * 1024 * 1024

EXTENSIONS_ACCEPTEES = (".csv", ".txt", ".xlsx", ".xls")


class DeclarationCreateRequest(BaseModel):
    #: Une des catégories de tax_calendar.CATEGORIES_DECLARATION ("TVA",
    #: "IS", "IR", "CNSS", "Taxes Locales") — validée côté route, pas ici,
    #: pour renvoyer un message qui liste les valeurs attendues.
    type_declaration: str
    #: Format "YYYY-MM", la même convention que reconciliation._periode_de.
    periode: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


def _declaration_to_dict(d: Declaration) -> dict:
    return {
        "id": str(d.id),
        "type_declaration": d.type_declaration,
        "periode": d.periode,
        "statut": d.statut,
    }


@router.get("/{dossier_id}/import/modele")
def telecharger_modele(
    dossier_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Modèle CSV commenté, à remplir par le cabinet.

    Servi par une route authentifiée et scopée au dossier plutôt qu'en fichier
    statique : ça garde une seule définition du format (la constante
    MODELE_CSV, à côté du parseur qui la lit), donc le modèle ne peut pas
    dériver de ce que le code accepte réellement.
    """
    get_dossier_or_404(db, dossier_id, user)
    return Response(
        content=MODELE_CSV,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modele_import_nisab.csv"'},
    )


@router.post("/{dossier_id}/import/fichier")
async def importer_fichier(
    dossier_id: uuid.UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Importe un export comptable CSV/Excel et le rend exploitable par l'audit.

    Niveau `admin` sur le dossier, comme la connexion Odoo : c'est une
    opération d'écriture, pas de lecture. Mais contrairement à la connexion
    Odoo, elle FUSIONNE plutôt qu'elle ne remplace (voir
    _fusionner_donnees_comptables dans routes_dossiers.py pour la raison) :
    les pièces déjà présentes dans le dossier et absentes de ce fichier
    restent intactes, seules celles au même n° de pièce sont mises à jour.

    Le fichier n'est jamais écrit sur le disque du serveur ; seul le résultat
    structuré est persisté (PieceComptable, snapshot). Limite assumée : on ne
    peut donc pas rejouer un import à l'identique après coup.
    """
    dossier = get_dossier_or_404(db, dossier_id, user, min_niveau="admin")

    nom = (file.filename or "import.csv").strip()
    if not nom.lower().endswith(EXTENSIONS_ACCEPTEES):
        raise HTTPException(
            status_code=400,
            detail=f"Format non pris en charge. Extensions acceptées : {', '.join(EXTENSIONS_ACCEPTEES)}.",
        )

    contenu = await file.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(contenu) > TAILLE_MAX_OCTETS:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux ({len(contenu) // 1024} Ko). Maximum : {TAILLE_MAX_OCTETS // 1024 // 1024} Mo.",
        )

    connecteur = FichierAccountingConnector(contenu=contenu, nom_fichier=nom)
    try:
        data = connecteur.fetch_accounting_data()
    except ConnectorError as exc:
        # 400 et non 500 : un fichier mal formé est une erreur de l'utilisateur,
        # avec un message qu'il peut lire et corriger lui-même.
        raise HTTPException(status_code=400, detail=str(exc))

    # Le nom de société lu depuis le fichier n'a pas d'autorité (c'est le nom du
    # fichier) : on garde la raison sociale déjà saisie sur le dossier.
    data["company"]["name"] = dossier.raison_sociale or data["company"]["name"]

    donnees_existantes = _get_active_accounting_data(db, dossier_id)
    ids_avant = {m["id"] for m in (donnees_existantes or {}).get("moves", [])}
    ids_ce_fichier = {m["id"] for m in data["moves"]}
    nb_moves_ajoutes = len(ids_ce_fichier - ids_avant)
    nb_moves_mis_a_jour = len(ids_ce_fichier & ids_avant)

    donnees_fusionnees = _fusionner_donnees_comptables(donnees_existantes, data)
    _persist_accounting_data(
        db, dossier_id, source="import_fichier", data=donnees_fusionnees, connexion_type=TypeConnexion.csv
    )

    return {
        "status": "ok",
        "company": donnees_fusionnees["company"]["name"],
        # Totaux dans le dossier APRÈS fusion, pas seulement ce fichier — pour
        # que l'utilisateur voie l'effet réel de son import, pas juste son contenu.
        "nb_moves": len(donnees_fusionnees["moves"]),
        "nb_moves_ajoutes": nb_moves_ajoutes,
        "nb_moves_mis_a_jour": nb_moves_mis_a_jour,
        "nb_partners": len(donnees_fusionnees["partners"]),
        "nb_lignes": len(data["lines"]),
        "nb_lignes_ignorees": connecteur.nb_lignes_ignorees,
        "warnings": connecteur.warnings,
    }


#: Une image de facture pèse quelques centaines de Ko à quelques Mo — plus
#: petit que le plafond CSV (TAILLE_MAX_OCTETS), pas de raison d'accepter
#: la même marge sur un format bien plus lourd par pixel.
TAILLE_MAX_OCTETS_OCR = 5 * 1024 * 1024


@router.post("/{dossier_id}/ocr/extraire")
async def extraire_ocr(
    dossier_id: uuid.UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Extrait quelques champs (date, montant TTC, ICE, n° de pièce) d'une image
    de facture, pour aider une saisie manuelle.

    Ne persiste RIEN et n'alimente jamais ai_auditor : voir la docstring
    d'app/ocr_extraction.py pour pourquoi une image ne peut pas produire une
    PieceComptable (elle ne donne jamais les comptes du plan CGNC à
    mouvementer, seulement des champs à vérifier par un humain).

    Niveau "lecture" (défaut de get_dossier_or_404) et non "admin" comme
    l'import de fichier : contrairement à celui-ci, aucune donnée du dossier
    n'est modifiée ici.
    """
    get_dossier_or_404(db, dossier_id, user)

    nom = (file.filename or "facture.png").strip()
    if not nom.lower().endswith(EXTENSIONS_OCR):
        raise HTTPException(
            status_code=400,
            detail=f"Format non pris en charge pour l'OCR. Extensions acceptées : {', '.join(EXTENSIONS_OCR)}.",
        )

    contenu = await file.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(contenu) > TAILLE_MAX_OCTETS_OCR:
        raise HTTPException(
            status_code=413,
            detail=f"Image trop volumineuse ({len(contenu) // 1024} Ko). Maximum : {TAILLE_MAX_OCTETS_OCR // 1024 // 1024} Mo.",
        )

    try:
        resultat = extraire_champs_facture(contenu, nom)
    except OcrError as exc:
        # 400 et non 500 : une image floue ou un format inattendu est une
        # situation normale côté utilisateur, pas un bug de Nisab.
        raise HTTPException(status_code=400, detail=str(exc))

    return resultat.to_dict()


@router.post("/{dossier_id}/sage/test")
def tester_sage(
    dossier_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    État du connecteur Sage.

    Répond honnêtement `ok: false, untested: true` : l'interface commune existe,
    l'implémentation ODBC n'a pas pu être écrite ni validée faute d'instance
    Sage. Voir connectors/sage_connecteur.py pour le détail.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="admin")
    return SageAccountingConnector().test_connection()


@router.get("/{dossier_id}/reconciliation/declaratif")
def reconciliation_declaratif(
    dossier_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Obligations déclaratives échues sans trace de dépôt ni de paiement.

    Lecture seule et recalculé à chaque appel : pas de table `rapprochement`,
    parce qu'il n'y a rien à mémoriser — le résultat est entièrement dérivé du
    calendrier légal et des écritures déjà persistées.

    La réponse porte `sourced: false` : voir reconciliation.py pour la raison.
    """
    dossier = get_dossier_or_404(db, dossier_id, user)
    data = _get_active_accounting_data(db, dossier_id)
    return rapprochement_declaratif(db, dossier_id, dossier, data)


@router.post("/{dossier_id}/reconciliation/declarations")
def declarer_obligation(
    dossier_id: uuid.UUID,
    req: DeclarationCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Marque à la main une obligation comme déposée.

    La table `declaration` existe depuis la Phase 1 pour exactement ce cas
    (reconciliation._declarations_deposees la lit déjà), mais aucune route ne
    l'écrivait : une déclaration réellement faite, dont l'écriture comptable
    n'a pas encore été importée ou dont le libellé ne contient aucun des
    mots-clés de tax_calendar._MOTS_CLES_PAIEMENT, restait signalée comme
    manquante indéfiniment. Cette route referme la boucle — c'est un
    complément déclaratif volontaire, pas une nouvelle détection : Nisab ne
    vérifie rien de plus qu'avant, il retient ce qu'on lui dit.

    Niveau "ecriture" et pas "admin" : au même titre que le classement d'une
    alerte (update_alerte_statut), c'est une annotation du dossier, pas une
    opération destructive ou de configuration.

    Upsert simple sur (dossier_id, type_declaration, periode) plutôt qu'un
    INSERT à chaque appel : cliquer deux fois par erreur ne doit pas créer
    deux lignes pour la même obligation. Pas de règle d'immutabilité façon
    AlerteRisque.cle_metier ici — cette table ne porte aucune décision
    humaine dont la perte serait grave (voir annuler_declaration ci-dessous).
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")

    if req.type_declaration not in CATEGORIES_DECLARATION:
        attendues = ", ".join(sorted(CATEGORIES_DECLARATION))
        raise HTTPException(
            status_code=422,
            detail=f"Catégorie invalide. Valeurs attendues : {attendues}.",
        )

    existante = db.execute(
        select(Declaration).where(
            Declaration.dossier_id == dossier_id,
            Declaration.type_declaration == req.type_declaration,
            Declaration.periode == req.periode,
        )
    ).scalar_one_or_none()

    if existante is not None:
        existante.statut = "deposee"
        declaration = existante
    else:
        declaration = Declaration(
            dossier_id=dossier_id,
            type_declaration=req.type_declaration,
            periode=req.periode,
            statut="deposee",
        )
        db.add(declaration)

    db.commit()
    db.refresh(declaration)
    return _declaration_to_dict(declaration)


@router.delete("/{dossier_id}/reconciliation/declarations/{declaration_id}", status_code=204)
def annuler_declaration(
    dossier_id: uuid.UUID,
    declaration_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Annule une déclaration saisie par erreur : la ligne redevient rouge au
    prochain calcul de rapprochement_declaratif.
    """
    get_dossier_or_404(db, dossier_id, user, min_niveau="ecriture")

    declaration = db.get(Declaration, declaration_id)
    if declaration is None or declaration.dossier_id != dossier_id:
        raise HTTPException(status_code=404, detail="Déclaration introuvable.")

    db.delete(declaration)
    db.commit()
