"""
detection_reglee.py — Détection d'anomalies dont les conditions d'application
se lisent entièrement dans les données comptables, sans jugement sémantique.

## Le problème que ce module règle

L'audit RAG désigne UN article par écriture. Mesuré sur les données réelles :
sur 8 alertes de 3 dossiers, `rag_sources_json` ne contenait jamais plus d'un
article, et sur deux factures réglées en espèces le filtre de pertinence avait
retenu l'Art. 146 (mentions de facture, `non_calculable` par construction)
plutôt que la règle chiffrable. Conséquence : `regles_montant.py` — 6 règles
testées, dont 3 qui produisent un montant — ne se déclenchait jamais, et
l'écran d'audit affichait « Exposition chiffrable : 0 DH » sur des dossiers
qui en avaient une.

Ce n'était pas un défaut du moteur de calcul (ses tests passent), mais du
chemin qui y mène : le montant dépendait d'un choix d'article fait par un
LLM, avec la variance que ça implique d'un run à l'autre.

## Le principe : séparer ce qui se juge de ce qui se constate

Certaines conditions d'application sont sémantiques — « cette facture
est-elle une charge d'exploitation ? », « ce tiers relève-t-il d'un régime de
retenue à la source ? ». Un LLM a du sens pour les trancher, une fonction
Python n'en a aucun.

D'autres sont purement factuelles — « ce règlement dépasse-t-il 5 000 DH pour
ce fournisseur ce jour-là ? ». Les faire dépendre d'un jugement LLM n'ajoute
aucune information : ça n'ajoute que de l'incertitude. Ce module détecte
CELLES-LÀ, et uniquement celles-là : `REFERENCES_AUTO_DETECTABLES`
(regles_montant.py) est volontairement fermé à 3 articles, avec la raison
d'exclusion écrite pour chacun des autres.

## Ce qui le distingue du `compliance_checker` retiré

Le fallback `compliance_checker.run_audit()` a été supprimé (voir
routes_dossiers.py, commentaire « CORRECTIF (architecture) ») pour une raison
précise : ses findings portaient des `reference_cgi` jamais confrontés au
corpus versionné et aucun `rag_sources`, donc aucune `CitationRisque` n'était
créée pour eux. Des alertes « sourcées » qui ne l'étaient pas, à l'endroit
exact du produit où l'anti-hallucination n'est pas négociable.

Ce module ne rejoue pas ça, et c'est la condition pour qu'il ait le droit
d'exister :

  1. il ne détecte QUE des articles pour lesquels une règle de calcul existe
     et est testée (`REFERENCES_AUTO_DETECTABLES`) ;
  2. il vérifie la référence dans le corpus versionné AVANT d'émettre quoi
     que ce soit — si l'article n'y est pas, aucune alerte n'est produite,
     parce qu'on ne pourrait pas la citer ;
  3. il renseigne `rag_sources`, donc `_reecrire_citations` crée bien la
     `CitationRisque` et l'utilisateur peut lire le texte de l'article ;
  4. il ne rédige aucune affirmation juridique libre : le champ décisif
     (`montant_detail`) est le calcul en toutes lettres produit par
     `regles_montant`, vérifiable de tête.

Le RAG reste donc la seule voie pour DÉCOUVRIR un risque nouveau. Ce module
ne découvre rien : il applique des règles déjà écrites, à des données déjà là.

## Ce qu'il NE fait PAS

Il ne remplace pas l'audit RAG et ne tourne pas à sa place : les deux séries
de findings sont fusionnées par `_execute_audit`. Une même écriture peut
porter une alerte RAG (Art. 146, qualitative) et une alerte réglée (Art. 11,
chiffrée) — ce sont deux anomalies distinctes, `cle_metier` vaut
`"{pièce}|{article}"` et les distingue nativement, sans migration.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.ai_auditor import calculer_montant_regle
from app.regles_montant import (
    REFERENCES_AUTO_DETECTABLES,
    CategorieMontant,
    ChargeEspeces,
    ResultatMontant,
    categorie_art106,
    repartir_deductible_especes_art11,
)

#: Libellés des règles auto-détectables. Écrits à la main, comme
#: `tax_calendar.py` — mais contrairement à lui, ces alertes SONT sourcées :
#: la référence est vérifiée dans le corpus et le calcul est joint. Le texte
#: ici ne fait que nommer l'anomalie, il n'affirme rien que l'article et le
#: calcul ne portent déjà.
LIBELLES: dict[str, dict[str, str]] = {
    "Article 11": {
        "title": "Charge réglée en espèces au-delà de la limite déductible",
        "description": (
            "Cette charge a été réglée autrement que par un moyen de paiement traçable. "
            "L'article 11-II du CGI ne la rend déductible du résultat fiscal que dans la "
            "limite de 5 000 DH par jour et par fournisseur, sans dépasser 50 000 DH par "
            "mois et par fournisseur. La fraction excédentaire doit être réintégrée."
        ),
        "recommendation": (
            "Réintégrer la fraction non déductible au résultat fiscal de l'exercice. "
            "Pour l'avenir, régler ce fournisseur par chèque barré non endossable, effet "
            "de commerce, virement ou procédé électronique afin de préserver la "
            "déductibilité intégrale de la charge."
        ),
    },
    "Article 10": {
        "title": "Amortissement de véhicule de tourisme au-delà du plafond déductible",
        "description": (
            "La dotation aux amortissements porte sur un véhicule de tourisme dont le prix "
            "d'acquisition dépasse le plafond de 400 000 DH TTC fixé par l'article 10 "
            "(I-F-1°-b) du CGI. La part de dotation correspondant au dépassement n'est pas "
            "déductible."
        ),
        "recommendation": (
            "Réintégrer la part de dotation excédentaire au résultat fiscal, et vérifier le "
            "prix d'acquisition TTC réel du véhicule sur la facture d'origine : il est ici "
            "extrait du libellé comptable, pas d'un champ dédié."
        ),
    },
    "Article 106": {
        "title": "TVA déduite sur une dépense exclue du droit à déduction",
        "description": (
            "La TVA a été déduite sur une dépense qui figure parmi les catégories que "
            "l'article 106-I du CGI exclut explicitement du droit à déduction. Le montant "
            "déduit doit être réintégré."
        ),
        "recommendation": (
            "Annuler la déduction de TVA sur cette dépense et régulariser la déclaration de "
            "TVA de la période concernée."
        ),
    },
}

#: Modes de règlement, en clair, qui valent « non traçable » au sens de
#: l'Art. 11-II. Volontairement limité aux libellés sans ambiguïté : tout le
#: reste (virement, chèque, effet, carte) est traçable, et un libellé inconnu
#: ne doit JAMAIS être présumé « espèces » — ce serait fabriquer une
#: réintégration à partir d'un champ mal rempli.
_MODES_ESPECES = ("cash", "especes", "espèces", "espece", "espèce", "caisse")

#: Préfixe des comptes de caisse au plan comptable marocain (CGNC) : 5161
#: « Caisses ». Utilisé comme signal de repli quand aucun mode de règlement
#: explicite n'est disponible — une écriture qui mouvemente un compte de
#: caisse a été réglée en espèces, c'est le sens même du compte.
_PREFIXE_COMPTE_CAISSE_CGNC = "516"


def _lignes_du_move(move: dict, lignes: Iterable[dict]) -> list[dict]:
    move_id = move.get("id")
    return [
        l for l in lignes
        if isinstance(l.get("move_id"), list) and l["move_id"] and l["move_id"][0] == move_id
    ]


def est_regle_en_especes(move: dict, lignes_move: list[dict]) -> tuple[bool, str]:
    """
    Le règlement de cette écriture est-il non traçable au sens de l'Art. 11-II ?

    Retourne `(oui_non, origine_du_signal)` — la seconde valeur est reprise
    telle quelle dans l'hypothèse affichée à l'utilisateur, parce que « d'où
    sait-on que c'était des espèces ? » est la première question qu'un
    contrôleur posera, et qu'elle ne doit pas rester dans le code.

    Trois signaux, du plus explicite au plus indirect. Aucun n'est deviné :
    en l'absence des trois, la réponse est NON — on ne réintègre pas une
    charge sur un soupçon.

    Pourquoi trois : `payment_mode` n'existe PAS dans `account.move.line`
    (ce n'est pas un champ Odoo standard), il n'est présent que dans les
    scénarios de démo d'`odoo_connector.py`. Sur une base Odoo réelle, seuls
    les signaux 2 et 3 peuvent répondre — d'où leur présence, sans quoi cette
    règle ne fonctionnerait qu'en démonstration.
    """
    for l in lignes_move:
        mode = (l.get("payment_mode") or "").strip().lower()
        if mode in _MODES_ESPECES:
            return True, "le mode de règlement porté par les lignes comptables"

    if (move.get("journal_type") or "").strip().lower() == "cash":
        journal = move.get("journal_id")
        nom = journal[1] if isinstance(journal, list) and len(journal) > 1 else "caisse"
        return True, f"le type du journal comptable ({nom} — journal de caisse)"

    for l in lignes_move:
        compte = l.get("account_id")
        libelle_compte = compte[1] if isinstance(compte, list) and len(compte) > 1 else ""
        code = str(libelle_compte).strip().split(" ")[0]
        if code.startswith(_PREFIXE_COMPTE_CAISSE_CGNC) and code.replace(".", "").isdigit():
            return True, f"la contrepartie sur un compte de caisse ({libelle_compte})"

    return False, ""


def _charge_ht(lignes_move: list[dict]) -> float:
    """
    Montant de la charge, hors TVA.

    L'Art. 11-II limite la déductibilité des « dépenses afférentes aux charges
    visées à l'article 10 (I-A, B et E) » : c'est la CHARGE qui est plafonnée,
    pas le décaissement. La TVA n'est pas une charge (elle se récupère par la
    déclaration, ou se traite sous l'Art. 106) — la retenir dans l'assiette
    gonflerait la réintégration d'environ 20 % sans fondement dans le texte.
    `tax_line_id` renseigné = ligne de TVA, convention Odoo.
    """
    return round(sum(
        float(l.get("debit") or 0) for l in lignes_move if not l.get("tax_line_id")
    ), 2)


def _severite(resultat: ResultatMontant) -> str:
    """
    La gravité suit la CERTITUDE de l'exposition, pas son montant.

    `calculable` = formule exacte sur des données garanties, l'exposition est
    acquise -> rouge. `calculable_hypothese` = le calcul est exact mais une
    entrée est déduite (prix lu dans un libellé, mode de règlement inféré) ->
    orange, parce qu'une hypothèse peut tomber à la vérification humaine.
    Un montant plus élevé mais hypothétique reste donc moins grave qu'un
    montant certain : c'est l'inverse d'un tri par DH, et c'est voulu.
    """
    return "rouge" if resultat.categorie == CategorieMontant.calculable else "orange"


def _odoo_path(move: dict) -> dict:
    move_type = move.get("move_type", "entry")
    sections = {
        "in_invoice": "Comptabilité > Fournisseurs > Factures",
        "out_invoice": "Comptabilité > Clients > Factures",
        "in_refund": "Comptabilité > Fournisseurs > Avoirs",
        "out_refund": "Comptabilité > Clients > Avoirs",
    }
    return {
        "section": sections.get(move_type, "Comptabilité > Écritures Comptables > Pièces"),
        "record_name": move.get("name"),
        "move_id": move.get("id"),
        "move_type": move_type,
    }


def _finding(reference: str, move: dict, partner: dict | None, resultat: ResultatMontant) -> dict:
    libelles = LIBELLES[reference]
    return {
        # Préfixe distinct des findings RAG (`ai_rag_...`) : en base comme en
        # log, on doit pouvoir dire d'où vient une alerte sans la relire.
        "rule": f"regle_{reference.lower().replace(' ', '_')}_{move.get('id')}",
        "status": "anomalie",
        "severity": _severite(resultat),
        "reference_cgi": reference,
        "title": libelles["title"],
        "description": libelles["description"],
        "amount_risk": resultat.montant,
        "categorie_montant": resultat.categorie.value,
        "montant_detail": resultat.detail,
        "montant_hypothese": resultat.hypothese,
        "invoice": move.get("name"),
        "partner": partner.get("name") if partner else "Inconnu",
        "date": move.get("date"),
        "recommendation": libelles["recommendation"],
        # Nom hérité du chemin RAG, conservé parce que c'est ce que lisent
        # `_reecrire_citations` et `CitationPills`. Ici il ne s'agit pas de
        # sources retrouvées par recherche mais de l'article que la règle
        # applique — vérifié dans le corpus juste avant l'émission.
        "rag_sources": [reference],
        "odoo_path": _odoo_path(move),
    }


def _verifier_dans_corpus(references: list[str]) -> set[str]:
    """
    Ne garde que les références réellement présentes dans le corpus versionné.

    Import différé : `vectorstore` ouvre une connexion Postgres à
    l'instanciation, et ce module doit rester importable (et testable) sans
    base — les tests injectent leur propre vérificateur.
    """
    from app.api import get_vectorstore

    textes = get_vectorstore().get_texts_by_references(references)
    return {ref for ref, texte in textes.items() if texte}


def detecter(
    data: dict,
    verifier_references: Callable[[list[str]], set[str]] | None = None,
) -> list[dict]:
    """
    Applique les règles auto-détectables au pivot comptable.

    `data` est le schéma pivot (`{company, partners, moves, lines}`), le même
    que consomme `ai_auditor` — donc cette détection fonctionne aussi bien sur
    Odoo que sur un import CSV, sans code spécifique.

    `verifier_references` permet aux tests de tourner sans Postgres. En
    production, c'est le corpus versionné qui tranche, et un article absent
    du corpus fait disparaître l'alerte plutôt que de produire une affirmation
    incitable.
    """
    moves: list[dict] = data.get("moves") or []
    lignes: list[dict] = data.get("lines") or []
    partners = {p["id"]: p for p in (data.get("partners") or []) if "id" in p}

    verifier = verifier_references or _verifier_dans_corpus
    disponibles = verifier(sorted(LIBELLES))
    findings: list[dict] = []

    def partner_de(move: dict) -> dict | None:
        pid = move.get("partner_id")
        return partners.get(pid[0]) if isinstance(pid, list) and pid else None

    # ── Art. 11-II : agrégé par fournisseur, jour et mois ─────────────────
    if "Article 11" in disponibles and "article 11" in REFERENCES_AUTO_DETECTABLES:
        # Regroupement par fournisseur AVANT tout calcul : les limites de
        # l'Art. 11-II sont « par jour et par fournisseur », donc deux
        # factures du même jour mais de fournisseurs différents ont chacune
        # leur enveloppe de 5 000 DH — les mélanger inventerait une
        # réintégration.
        par_fournisseur: dict[int, list[ChargeEspeces]] = {}
        moves_par_piece: dict[str, dict] = {}
        signal_par_piece: dict[str, str] = {}

        for move in moves:
            # Achats uniquement : l'Art. 11-II limite la déduction d'une
            # CHARGE. Une vente encaissée en espèces relève de l'Art. 193
            # (amende chez le vendeur), pas d'ici.
            if move.get("move_type") not in ("in_invoice", "in_refund"):
                continue
            pid = move.get("partner_id")
            if not (isinstance(pid, list) and pid):
                # Sans fournisseur identifié, la limite « par fournisseur »
                # n'a pas de sens : on ne peut pas la calculer, donc on ne
                # l'affirme pas.
                continue

            lignes_move = _lignes_du_move(move, lignes)
            especes, origine = est_regle_en_especes(move, lignes_move)
            if not especes:
                continue

            montant = _charge_ht(lignes_move)
            if montant <= 0:
                continue

            piece = move.get("name") or f"move_{move.get('id')}"
            par_fournisseur.setdefault(pid[0], []).append(
                ChargeEspeces(piece=piece, date_piece=str(move.get("date") or ""), montant_ht=montant)
            )
            moves_par_piece[piece] = move
            signal_par_piece[piece] = origine

        for charges in par_fournisseur.values():
            origine = signal_par_piece.get(charges[0].piece, "les données comptables")
            for piece, resultat in repartir_deductible_especes_art11(charges, origine).items():
                if resultat.montant and resultat.montant > 0:
                    move = moves_par_piece[piece]
                    findings.append(_finding("Article 11", move, partner_de(move), resultat))

    # ── Art. 10 et 106 : écriture par écriture ────────────────────────────
    # Le dispatch d'extraction est celui d'`ai_auditor`, réutilisé tel quel
    # plutôt que réécrit : c'est lui qui décide, par exemple, que la
    # catégorie Art. 106 se lit sur le compte et le libellé de la ligne mais
    # JAMAIS sur le nom du tiers (sans quoi « Fournisseur Carburants Sud »
    # ferait passer un repas d'affaires pour du carburant). Dupliquer cette
    # logique ici, c'était la voir diverger.
    for reference in ("Article 10", "Article 106"):
        if reference not in disponibles:
            continue
        for move in moves:
            lignes_move = _lignes_du_move(move, lignes)

            # GARDE-FOU propre à l'auto-détection. Sur le chemin RAG, si
            # l'Art. 10 est cité c'est qu'un LLM a lu l'écriture et jugé
            # qu'elle concernait un amortissement de véhicule de tourisme :
            # `extraire_prix_vehicule` peut alors chercher un prix en
            # confiance. Ici personne n'a rien confirmé, et la fonction
            # d'extraction se contente d'un nombre de 6-7 chiffres — une
            # référence de pièce du genre « FACT-450000 » suffirait donc à
            # fabriquer une réintégration sur une écriture qui n'a jamais
            # vu de véhicule. On exige donc que le libellé mentionne
            # explicitement un véhicule de tourisme, via le détecteur par
            # mots-clés déjà testé (`categorie_art106`), avant de laisser la
            # règle 2 s'appliquer. L'Art. 106, lui, est déjà protégé : sa
            # règle exige la même catégorisation pour produire un montant.
            if reference == "Article 10":
                textes = " ".join(filter(None, [
                    move.get("ref"), move.get("name"),
                    *(str(l.get("name") or "") for l in lignes_move),
                ]))
                if categorie_art106(textes) != "vehicule_tourisme":
                    continue

            resultat = calculer_montant_regle(reference, move, lignes)
            if resultat.categorie == CategorieMontant.non_calculable:
                continue
            if not resultat.montant or resultat.montant <= 0:
                continue
            findings.append(_finding(reference, move, partner_de(move), resultat))

    return findings
