"""
fichier_connecteur.py — Import d'un export comptable CSV / Excel.

C'est le connecteur qui prouve réellement la Phase 5 : un cabinet sans Odoo
alimente le même pipeline d'audit, sans qu'une seule ligne d'ai_auditor.py ait
été modifiée. La preuve que le schéma pivot (voir base.py) était le bon choix.

## Colonnes attendues

    date            2026-03-14        obligatoire
    piece           FACT-2026-002     obligatoire (regroupe les lignes en écriture)
    journal         ACH               optionnel  (défaut "DIVERS")
    compte          6142              obligatoire (plan comptable CGNC)
    libelle         Frais de mission  optionnel
    debit           1200.00           debit ou credit obligatoire
    credit          0
    tiers_nom       Fournisseur SARL  optionnel
    tiers_ice       001234567000045   optionnel — son absence est un risque fiscal
    montant_ttc     1440.00           optionnel (sinon déduit des lignes)
    mode_reglement  especes           optionnel — lu par ai_auditor (paiements en espèces)

Les en-têtes sont normalisées (minuscules, accents et espaces retirés), donc
« Débit », « DEBIT » et « debit » sont acceptés indifféremment. Quelques
synonymes courants des exports Sage/Ciel sont également reconnus.

## Deux points de conception qui ne sont pas des détails

**Les identifiants sont déterministes.** `move["id"]` est dérivé par hachage du
numéro de pièce, pas d'un compteur. Réimporter le même fichier produit donc les
mêmes identifiants — condition nécessaire pour que la clé métier des alertes
(voir AlerteRisque dans models.py) reste stable et qu'une correction validée
par un humain ne se détache pas de son anomalie au prochain import.

**Une ligne illisible ne fait pas échouer l'import.** Un export comptable réel
contient des lignes de total, des séparateurs, des dates au mauvais format. On
les collecte dans `warnings` et on importe le reste : un comptable qui a 800
lignes ne doit pas se voir refuser son fichier entier à cause de trois.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from datetime import date, datetime

from app.connectors.base import AccountingConnector, ConnectorError
from app.models import TypeConnexion

#: Colonnes sans lesquelles on ne peut rien construire.
COLONNES_OBLIGATOIRES = ("date", "piece", "compte")

#: Synonymes tolérés, normalisés -> nom canonique.
_ALIAS = {
    "dateecriture": "date", "datepiece": "date", "jour": "date",
    "numeropiece": "piece", "npiece": "piece", "numpiece": "piece", "reference": "piece",
    "journalcode": "journal", "codejournal": "journal",
    "comptenum": "compte", "numerocompte": "compte", "comptegeneral": "compte",
    "intitule": "libelle", "designation": "libelle", "libelleecriture": "libelle",
    "montantdebit": "debit", "montantcredit": "credit",
    "tiers": "tiers_nom", "nomtiers": "tiers_nom", "fournisseur": "tiers_nom", "client": "tiers_nom",
    "ice": "tiers_ice", "icetiers": "tiers_ice", "identifiantcommun": "tiers_ice",
    "ttc": "montant_ttc", "montantttc": "montant_ttc",
    "modereglement": "mode_reglement", "moderèglement": "mode_reglement", "reglement": "mode_reglement",
}

#: Préfixes du plan comptable marocain (CGNC) servant à deviner la nature de
#: l'écriture. 4411 = fournisseurs, 3421 = clients. C'est une heuristique, elle
#: est explicite ici plutôt que noyée dans le code.
_PREFIXE_FOURNISSEUR = "441"
_PREFIXE_CLIENT = "342"

#: Modèle proposé au téléchargement depuis l'interface.
MODELE_CSV = (
    "date,piece,journal,compte,libelle,debit,credit,tiers_nom,tiers_ice,montant_ttc,mode_reglement\n"
    "2026-03-14,FACT-2026-002,ACH,6142,Frais de mission,1200.00,0,Transport Atlas SARL,001234567000045,1440.00,especes\n"
    "2026-03-14,FACT-2026-002,ACH,34551,TVA récupérable,240.00,0,Transport Atlas SARL,001234567000045,1440.00,especes\n"
    "2026-03-14,FACT-2026-002,ACH,4411,Fournisseur,0,1440.00,Transport Atlas SARL,001234567000045,1440.00,especes\n"
)


def _normaliser_entete(nom: str) -> str:
    """« Montant Débit » -> « montantdebit », puis résolution des synonymes."""
    sans_accents = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode("ascii")
    compact = re.sub(r"[^a-z0-9_]", "", sans_accents.lower())
    return _ALIAS.get(compact, compact)


def _identifiant_stable(valeur: str) -> int:
    """
    Identifiant entier reproductible pour un libellé donné.

    Un compteur (1, 2, 3…) serait plus simple mais dépendrait de l'ordre des
    lignes du fichier : deux exports du même exercice triés différemment
    donneraient des identifiants différents pour la même pièce. Le hachage rend
    l'identité intrinsèque à la pièce, pas à la façon dont on l'a lue.

    Masqué sur 31 bits, pas 32 : l'INTEGER de Postgres est SIGNÉ, il plafonne à
    2 147 483 647. Prendre les 32 bits bruts du hachage produit une valeur trop
    grande une fois sur deux environ — et l'échec ne se serait vu qu'à
    l'écriture d'alerte_risque.move_id, sur certaines pièces seulement, donc
    de façon apparemment aléatoire. `or 1` écarte le 0, qui n'est pas un
    identifiant valide côté Odoo.
    """
    return (int(hashlib.sha1(valeur.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF) or 1


def _nombre(valeur) -> float:
    """Tolère « 1 200,50 », « 1.200,50 », les vides et les None."""
    if valeur is None:
        return 0.0
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).strip().replace(" ", "").replace(" ", "")
    if not texte or texte in {"-", "nan", "NaN"}:
        return 0.0
    # Si les deux séparateurs sont présents, le dernier est le décimal.
    if "," in texte and "." in texte:
        if texte.rfind(",") > texte.rfind("."):
            texte = texte.replace(".", "").replace(",", ".")
        else:
            texte = texte.replace(",", "")
    else:
        texte = texte.replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        raise ValueError(f"montant illisible : {valeur!r}")


def _date_iso(valeur) -> str:
    """Accepte ISO, JJ/MM/AAAA, JJ-MM-AAAA et les dates natives d'Excel."""
    if isinstance(valeur, datetime):
        return valeur.date().isoformat()
    if isinstance(valeur, date):
        return valeur.isoformat()
    texte = str(valeur).strip()
    if not texte:
        raise ValueError("date vide")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texte[:10], fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"date illisible : {valeur!r}")


def _deviner_move_type(comptes: list[str]) -> str:
    """
    Nature de l'écriture d'après les comptes mouvementés (plan CGNC).

    Retourne "entry" (opération diverse) si aucun compte de tiers n'apparaît —
    c'est le cas neutre, et ai_auditor audite aussi bien les "entry" que les
    "in_invoice" (voir run_ai_rag_audit), donc se tromper ici ne fait pas
    disparaître l'écriture de l'audit.
    """
    for compte in comptes:
        if compte.startswith(_PREFIXE_FOURNISSEUR):
            return "in_invoice"
    for compte in comptes:
        if compte.startswith(_PREFIXE_CLIENT):
            return "out_invoice"
    return "entry"


class FichierAccountingConnector(AccountingConnector):
    """
    Lit un CSV ou un Excel déjà chargé en mémoire.

    Prend les octets plutôt qu'un chemin : le fichier arrive par upload HTTP et
    n'est jamais écrit sur le disque du serveur. Seul le résultat structuré est
    persisté (PieceComptable), pas le fichier d'origine — limite assumée, à
    mentionner dans le rapport.
    """

    type_connexion = TypeConnexion.csv

    def __init__(self, contenu: bytes, nom_fichier: str):
        self.contenu = contenu
        self.nom_fichier = nom_fichier or "import"
        self.warnings: list[str] = []
        self.nb_lignes_ignorees = 0

    # ── lecture brute ────────────────────────────────────────────────────

    def _lire_lignes(self) -> list[dict]:
        """Renvoie les lignes du fichier sous forme de dicts à en-têtes normalisées."""
        import pandas as pd  # import local : le backend démarre même sans pandas

        nom = self.nom_fichier.lower()
        try:
            if nom.endswith((".xlsx", ".xls")):
                df = pd.read_excel(io.BytesIO(self.contenu), dtype=object)
            else:
                # sep=None + engine="python" laisse pandas détecter , ; ou tab :
                # les exports comptables français utilisent souvent le point-virgule.
                df = pd.read_csv(
                    io.BytesIO(self.contenu), dtype=object, sep=None, engine="python",
                    encoding="utf-8-sig", skip_blank_lines=True,
                )
        except Exception as exc:
            raise ConnectorError(f"Fichier illisible ({self.nom_fichier}) : {exc}") from exc

        df.columns = [_normaliser_entete(c) for c in df.columns]

        manquantes = [c for c in COLONNES_OBLIGATOIRES if c not in df.columns]
        if manquantes:
            raise ConnectorError(
                f"Colonnes obligatoires absentes : {', '.join(manquantes)}. "
                f"Colonnes trouvées : {', '.join(df.columns)}. "
                "Téléchargez le modèle depuis l'interface pour le format attendu."
            )

        return df.where(df.notna(), None).to_dict(orient="records")

    # ── contrat AccountingConnector ──────────────────────────────────────

    def test_connection(self) -> dict:
        try:
            lignes = self._lire_lignes()
        except ConnectorError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": f"{len(lignes)} ligne(s) lisible(s) dans {self.nom_fichier}."}

    def fetch_accounting_data(self) -> dict:
        lignes = self._lire_lignes()

        moves: dict[str, dict] = {}
        lines: list[dict] = []
        partners: dict[str, dict] = {}
        comptes_par_piece: dict[str, list[str]] = {}

        for numero, brut in enumerate(lignes, start=2):  # +2 : en-tête + index 1-based
            try:
                piece = str(brut.get("piece") or "").strip()
                compte = str(brut.get("compte") or "").strip()
                if not piece or not compte:
                    raise ValueError("pièce ou compte vide")
                date_piece = _date_iso(brut.get("date"))
                debit = _nombre(brut.get("debit"))
                credit = _nombre(brut.get("credit"))
            except ValueError as exc:
                self.nb_lignes_ignorees += 1
                if len(self.warnings) < 25:  # on ne noie pas l'utilisateur
                    self.warnings.append(f"Ligne {numero} ignorée — {exc}")
                continue

            move_id = _identifiant_stable(piece)
            journal = str(brut.get("journal") or "DIVERS").strip() or "DIVERS"
            libelle = str(brut.get("libelle") or "").strip()

            # ── tiers ────────────────────────────────────────────────────
            tiers_nom = str(brut.get("tiers_nom") or "").strip()
            partner_ref = None
            if tiers_nom:
                cle_tiers = _normaliser_entete(tiers_nom) or tiers_nom.lower()
                partenaire = partners.get(cle_tiers)
                if partenaire is None:
                    ice = str(brut.get("tiers_ice") or "").strip()
                    partenaire = {
                        "id": _identifiant_stable(f"tiers:{cle_tiers}"),
                        "name": tiers_nom,
                        # False plutôt que "" : c'est ce que renvoie Odoo pour un
                        # champ vide, et ai_auditor teste la valeur telle quelle
                        # pour signaler un ICE manquant (risque fiscal réel).
                        "vat": ice or False,
                        "supplier_rank": 0,
                        "customer_rank": 0,
                        "street": "",
                        "city": "",
                    }
                    partners[cle_tiers] = partenaire
                elif not partenaire["vat"]:
                    ice = str(brut.get("tiers_ice") or "").strip()
                    if ice:
                        partenaire["vat"] = ice
                partner_ref = [partenaire["id"], partenaire["name"]]

            # ── écriture ─────────────────────────────────────────────────
            move = moves.get(piece)
            if move is None:
                move = {
                    "id": move_id,
                    "name": piece,
                    "date": date_piece,
                    "journal_id": [_identifiant_stable(f"journal:{journal}"), journal],
                    "partner_id": partner_ref or False,
                    "move_type": "entry",  # recalculé une fois toutes les lignes vues
                    "amount_total": _nombre(brut.get("montant_ttc")),
                    "payment_state": "not_paid",
                    "ref": libelle,
                    "state": "posted",
                }
                moves[piece] = move
                comptes_par_piece[piece] = []
            elif partner_ref and not move["partner_id"]:
                move["partner_id"] = partner_ref

            comptes_par_piece[piece].append(compte)

            lines.append({
                "move_id": [move_id, piece],
                "account_id": [_identifiant_stable(f"compte:{compte}"), f"{compte} {libelle}".strip()],
                "name": libelle,
                "debit": debit,
                "credit": credit,
                "tax_ids": [],
                "tax_line_id": False,
                "partner_id": partner_ref or False,
                "date": date_piece,
                "amount_currency": 0.0,
                "payment_mode": str(brut.get("mode_reglement") or "").strip(),
            })

        if not moves:
            raise ConnectorError(
                "Aucune écriture exploitable dans le fichier. "
                + (" ".join(self.warnings[:3]) if self.warnings else "")
            )

        # ── finitions par écriture ───────────────────────────────────────
        for piece, move in moves.items():
            move["move_type"] = _deviner_move_type(comptes_par_piece[piece])
            if not move["amount_total"]:
                # Pas de colonne montant_ttc : en partie double, le total de
                # l'écriture est la somme des débits (= somme des crédits).
                move["amount_total"] = round(
                    sum(l["debit"] for l in lines if l["move_id"][1] == piece), 2
                )

            # Contrôle d'équilibre : on n'invente rien, on signale. Un déséquilibre
            # vient presque toujours d'une ligne écartée plus haut, et le comptable
            # est le seul à pouvoir dire laquelle.
            total_debit = sum(l["debit"] for l in lines if l["move_id"][1] == piece)
            total_credit = sum(l["credit"] for l in lines if l["move_id"][1] == piece)
            if abs(total_debit - total_credit) > 0.01 and len(self.warnings) < 25:
                self.warnings.append(
                    f"Pièce {piece} déséquilibrée : debit {total_debit:.2f} != credit {total_credit:.2f}"
                )

        moves_tries = sorted(moves.values(), key=lambda m: m["date"], reverse=True)

        return {
            "company": {"name": self.nom_fichier.rsplit(".", 1)[0], "vat": False},
            "partners": list(partners.values()),
            "moves": moves_tries,
            "lines": lines,
            "source": "import_fichier",
        }
