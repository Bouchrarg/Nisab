"""
correction_agent.py — Génération de propositions de correction sourcées.

## Ce que fait ce module, et ce qu'il ne fait pas

Il transforme une alerte **déjà détectée et déjà sourcée** en une proposition
d'action concrète. Il ne détecte rien, ne cherche rien, ne juge rien de neuf.

C'est une contrainte d'architecture, pas une limitation subie. La détection de
risques du produit est RAG-only (règle d'architecture) : si ce module allait chercher
ses propres articles, il pourrait fonder une correction sur un texte que
l'alerte ne citait pas, et le constat ne correspondrait plus au remède. On
reprend donc exactement les articles retenus par l'audit — même précédent que
control_simulator.py, qui rejoue les citations persistées sans nouvelle
recherche.

## La chaîne de garde-fous, du plus faible au plus fort

1. **Filtrage des références** — toute référence citée par le LLM qui ne
   correspond pas à une référence de l'alerte est écartée. Si après filtrage
   il n'en reste aucune, la génération est REJETÉE et rien n'est persisté.
   Zéro sortie IA sans citation vérifiable.

2. **Auto-critique** — un second appel, avec un modèle rapide, relit la
   proposition en regard des textes d'articles et répond « cohérent ou non ».
   Si non, une seule régénération avec la critique injectée, puis abandon.
   C'est ce qui rend le mot « agentique » exact : propose -> critique ->
   révise. À dire honnêtement : boucle contrainte à un tour, jamais autonome,
   validation humaine obligatoire ensuite.

3. **Équilibre en partie double** — vérification arithmétique, sans LLM. Une
   écriture dont la somme des débits diffère de la somme des crédits n'est pas
   persistée, quelle que soit la qualité du raisonnement qui l'accompagne.
   C'est le garde-fou le plus fort du module, précisément parce qu'il ne
   dépend d'aucun modèle : le LLM propose, la comptabilité arbitre.

## Le piège de conception à ne pas rouvrir

Beaucoup d'anomalies fiscales n'ont PAS de correction comptable. Un fournisseur
sans ICE, une facture sans mentions obligatoires, un règlement en espèces déjà
effectué : aucune écriture d'OD ne répare ça. Un prompt qui exigerait une
écriture dans tous les cas en obtiendrait une — inventée, plausible, et fausse.
D'où les quatre types de correction.
"""

from __future__ import annotations

import re
from datetime import date

from app.ai_auditor import _cle_article, _normalize_ref
from app.llm_client import GROQ_MODEL_DEFAULT, GROQ_MODEL_FAST, llm_call_json
from app.models import AlerteRisque, TypeCorrection

CORPUS_VERSION = "CGI 2026"

#: Tolérance sur l'équilibre débit/crédit. 1 centime : au-delà, ce n'est plus
#: un arrondi, c'est une erreur de raisonnement.
TOLERANCE_EQUILIBRE = 0.01

#: Budget de texte légal envoyé au LLM, réparti entre les articles cités.
#: Même ordre de grandeur que ai_auditor.AUDIT_LEGAL_CONTEXT_CHAR_BUDGET.
BUDGET_CONTEXTE_LEGAL = 6000

TYPES_AVEC_ECRITURE = {TypeCorrection.ecriture_od, TypeCorrection.regularisation_tva}


SYSTEM_PROMPT = """Tu es un expert-comptable marocain. On te donne UNE anomalie fiscale déjà détectée et déjà rattachée à des articles du Code Général des Impôts marocain, avec le texte intégral de ces articles.

Ta tâche : proposer la correction que le cabinet doit appliquer.

RÈGLES ABSOLUES
1. Tu ne cites QUE les articles fournis ci-dessous. Tu n'en inventes aucun, tu n'en évoques aucun autre de mémoire.
2. Beaucoup d'anomalies ne se corrigent PAS par une écriture comptable. Si c'est le cas, dis-le franchement au lieu d'inventer une écriture. Une écriture inventée pour un problème qu'elle ne résout pas est pire que pas de proposition.
3. Si tu proposes une écriture, elle doit être ÉQUILIBRÉE : somme des débits = somme des crédits, au centime près.
4. Utilise les codes du plan comptable marocain (CGNC) : 6142 transports, 4411 fournisseurs, 3455 TVA récupérable, 4455 TVA facturée, 3421 clients, 5161 caisse, 6167 impôts et taxes, 6586 pénalités et amendes. Codes à 4 chiffres suffisants.

TYPES DE CORRECTION (choisis-en exactement un)
- "ecriture_od" : une écriture d'opérations diverses corrige le problème (mauvaise imputation, charge à réintégrer, provision à constituer).
- "regularisation_tva" : le problème porte sur la TVA déduite ou collectée à tort.
- "piece_a_reclamer" : rien à écrire en comptabilité, il faut obtenir un document (facture conforme, ICE du fournisseur, justificatif).
- "aucune_ecriture" : le fait est acquis et irréversible (paiement en espèces déjà effectué, délai forclos). Seuls un provisionnement du risque ou une régularisation déclarative sont possibles.

Pour "piece_a_reclamer" et "aucune_ecriture", le tableau "lignes" DOIT être vide.

RÈGLES ABSOLUES (suite)
5. N'INVENTE AUCUN MONTANT. Les seuls chiffres que tu as le droit d'écrire dans les lignes sont :
   - les montants de l'écriture comptable qui t'est fournie (section ÉCRITURE CONCERNÉE), ou une somme/différence de ces montants ;
   - le montant d'exposition s'il t'est donné (il vient d'un calcul déterministe déjà fait) ;
   - un montant de TVA obtenu en appliquant un taux du CGI à l'un des montants ci-dessus.
   Tout autre chiffre est une invention : il ne correspondrait à aucune écriture réelle et serait indéfendable devant un contrôle.
6. Ne chiffre JAMAIS l'exposition, l'amende ou la pénalité dans ta justification : ce calcul est fait ailleurs, par une règle déterministe.
7. Si aucun montant ne t'est fourni et qu'aucun ne peut s'en déduire, ne fabrique pas une écriture à zéro : choisis "piece_a_reclamer" ou "aucune_ecriture" et explique dans "action" ce qu'il faut obtenir ou vérifier pour pouvoir chiffrer. Une écriture dont les lignes valent 0 n'est pas une écriture.

RÉPONDS UNIQUEMENT EN JSON :
{
  "type_correction": "ecriture_od" | "regularisation_tva" | "piece_a_reclamer" | "aucune_ecriture",
  "resume": "une phrase, 200 caractères maximum, ce qu'il faut faire",
  "justification": "3 à 5 phrases : pourquoi cette correction, en t'appuyant explicitement sur les articles fournis",
  "references": ["Article 106", "..."],
  "action": "si aucune écriture : l'action concrète à mener, sinon null",
  "lignes": [
    {"compte": "6142", "libelle": "...", "debit": 1200.00, "credit": 0},
    {"compte": "4411", "libelle": "...", "debit": 0, "credit": 1200.00}
  ]
}"""


CRITIQUE_SYSTEM_PROMPT = """Tu es un réviseur comptable. On te donne une anomalie fiscale, les articles du CGI marocain qui la fondent, et une proposition de correction produite par un autre expert.

Ta seule tâche : dire si la proposition est cohérente. Sois exigeant mais pas tatillon.

Réponds "coherent": false uniquement si l'un de ces problèmes est présent :
- les montants de l'écriture proposée ne se déduisent pas de l'écriture réelle fournie (ni repris tels quels, ni somme/différence, ni TVA appliquée à l'un d'eux) : c'est le défaut le plus grave, un montant inventé rend la correction indéfendable même si elle est équilibrée
- l'écriture proposée ne corrige pas l'anomalie décrite
- le type de correction est inadapté (une écriture pour un problème documentaire, ou l'inverse)
- les comptes utilisés sont manifestement faux au regard du plan comptable marocain
- la justification s'appuie sur un article qui ne dit pas ce qu'on lui fait dire
- des lignes d'écriture sont proposées alors que le type est "piece_a_reclamer" ou "aucune_ecriture"

RÉPONDS UNIQUEMENT EN JSON : {"coherent": true|false, "motif": "une phrase expliquant le problème, vide si cohérent"}"""


def _references_alerte(alerte: AlerteRisque) -> list[str]:
    """Toutes les références sur lesquelles l'alerte est fondée, dédoublonnées."""
    refs: list[str] = []
    vues: set[str] = set()
    for ref in [alerte.reference_cgi, *(alerte.rag_sources_json or [])]:
        if not ref:
            continue
        cle = _normalize_ref(ref)
        if cle not in vues:
            vues.add(cle)
            refs.append(ref)
    return refs


def _construire_contexte_legal(references: list[str], textes: dict[str, str]) -> str:
    """
    Bloc de texte légal envoyé au LLM, tronqué pour tenir dans la fenêtre.

    Budget réparti à parts égales : mieux vaut un extrait de chaque article
    cité qu'un seul article complet et les autres absents — le LLM doit pouvoir
    justifier à partir de n'importe lequel d'entre eux.
    """
    presents = [r for r in references if textes.get(r)]
    if not presents:
        return ""
    budget = max(500, BUDGET_CONTEXTE_LEGAL // len(presents))
    blocs = []
    for ref in presents:
        texte = textes[ref].strip()
        if len(texte) > budget:
            texte = texte[:budget] + " […]"
        blocs.append(f"--- {ref} ---\n{texte}")
    return "\n\n".join(blocs)


def _formater_compte(valeur) -> str:
    """
    Rend lisible un `account_id` du pivot Odoo : `[42, "614210 Transports"]`.

    Le pivot conserve les many2one Odoo sous forme `[id, libellé]` (cf.
    connectors/). On donne le libellé au LLM, pas l'id technique : c'est le
    code du plan CGNC qui l'intéresse pour construire une contrepartie.
    """
    if isinstance(valeur, list) and len(valeur) > 1:
        return str(valeur[1])
    return str(valeur) if valeur else "compte inconnu"


def _construire_contexte_ecriture(move: dict | None, lignes: list[dict] | None) -> str:
    """
    Rend l'écriture réellement concernée, lignes et montants compris.

    ## Pourquoi ce bloc existe

    Sans lui, le prompt ne contenait que le n° de pièce, le tiers et la date :
    on demandait au modèle de corriger une écriture qu'il n'avait jamais vue.
    Deux sorties possibles, toutes deux fausses, mesurées en production :
    inventer des montants qui s'équilibrent entre eux (une proposition à
    1 000 + 200 DH sur une écriture réelle de 2 500 DH — équilibrée, sourcée,
    et sans rapport avec la comptabilité), ou refuser d'inventer et rendre des
    lignes à zéro que `valider_equilibre` rejette.

    `valider_equilibre` ne pouvait pas rattraper le premier cas : elle vérifie
    que débit = crédit, pas que les montants correspondent à une écriture
    existante — elle ne la recevait pas non plus. C'est un contrôle de
    cohérence interne, et il le reste ; ce bloc s'attaque à l'autre moitié du
    problème, en amont.

    Retourne "" si l'écriture n'a pas pu être retrouvée (import CSV sans
    lignes détaillées, snapshot remplacé depuis l'audit) : le prompt le dit
    alors explicitement, et la règle 7 impose au modèle de ne pas chiffrer.
    """
    if not move:
        return ""
    entete = [
        f"Pièce : {move.get('name') or move.get('ref') or 'sans numéro'}",
        f"Date : {move.get('date') or 'inconnue'}",
    ]
    if move.get("amount_total") is not None:
        entete.append(f"Total de la pièce : {float(move['amount_total']):,.2f} DH")
    if move.get("move_type"):
        entete.append(f"Type : {move['move_type']}")

    if not lignes:
        return "\n".join(entete) + "\nLignes détaillées : non disponibles pour cette pièce."

    corps = ["", "Lignes comptables (montants réels, en DH) :"]
    total_debit = total_credit = 0.0
    for ligne in lignes:
        debit = float(ligne.get("debit") or 0)
        credit = float(ligne.get("credit") or 0)
        total_debit += debit
        total_credit += credit
        libelle = str(ligne.get("name") or "").strip()
        corps.append(
            f"  - {_formater_compte(ligne.get('account_id'))} | débit {debit:,.2f} | crédit {credit:,.2f}"
            + (f" | {libelle}" if libelle else "")
        )
    corps.append(f"  (total débit {total_debit:,.2f} — total crédit {total_credit:,.2f})")
    return "\n".join(entete + corps)


def _construire_prompt_utilisateur(alerte: AlerteRisque, contexte_legal: str, contexte_ecriture: str = "") -> str:
    # "Calculée", pas "estimée" : depuis le branchement d'app.regles_montant,
    # ce chiffre (s'il existe) vient d'une formule déterministe, pas d'une
    # estimation LLM. Donné en LECTURE SEULE au modèle pour qu'il puisse en
    # parler dans sa justification s'il le souhaite — jamais redemandé en
    # sortie structurée 
    if alerte.montant_exposition:
        montant = f"{float(alerte.montant_exposition):,.2f} DH (calculée par une règle déterministe, pas par toi)"
    else:
        montant = "non chiffrée (aucune règle de calcul applicable ou aucun montant à ce stade)"
    return f"""ANOMALIE DÉTECTÉE
Titre : {alerte.titre}
Description : {alerte.description}
Niveau de risque : {alerte.niveau_risque.value}
Exposition : {montant}

ÉCRITURE CONCERNÉE
Tiers : {alerte.partner_nom or "non identifié"}
{contexte_ecriture or (
    f"Pièce : {alerte.move_ref or 'non identifiée'}\n"
    f"Date : {alerte.date_piece.isoformat() if alerte.date_piece else 'non identifiée'}\n"
    "Lignes comptables : INDISPONIBLES. Tu ne disposes d'aucun montant réel : "
    "applique la règle 7 plutôt que de chiffrer une écriture."
)}

RECOMMANDATION DE L'AUDIT
{alerte.recommandation or "aucune"}

ARTICLES DU CGI APPLICABLES (seules sources autorisées)
{contexte_legal or "Aucun texte disponible."}"""


def valider_equilibre(lignes: list[dict]) -> tuple[bool, str]:
    """
    Vérifie qu'une écriture respecte la partie double.

    Garde-fou déterministe : aucun LLM n'intervient, donc aucun modèle ne peut
    le contourner en étant convaincant. C'est l'argument central du module —
    le LLM propose, la comptabilité arbitre, et l'arbitrage ne se discute pas.

    Utilisé à la génération ET à l'amendement : un humain qui édite le payload
    peut se tromper aussi, la règle ne lui est pas plus indulgente.
    """
    if not lignes:
        return False, "Aucune ligne d'écriture."
    if len(lignes) < 2:
        return False, "Une écriture comptable comporte au moins deux lignes."

    total_debit = 0.0
    total_credit = 0.0
    for i, ligne in enumerate(lignes, start=1):
        try:
            debit = round(float(ligne.get("debit") or 0), 2)
            credit = round(float(ligne.get("credit") or 0), 2)
        except (TypeError, ValueError):
            return False, f"Ligne {i} : montant illisible."
        if debit < 0 or credit < 0:
            return False, f"Ligne {i} : montant négatif. Inversez débit et crédit plutôt que d'utiliser un signe."
        if debit > 0 and credit > 0:
            return False, f"Ligne {i} : débit et crédit renseignés simultanément."
        if debit == 0 and credit == 0:
            return False, f"Ligne {i} : ligne à zéro."
        if not str(ligne.get("compte") or "").strip():
            return False, f"Ligne {i} : compte comptable manquant."
        total_debit += debit
        total_credit += credit

    ecart = round(total_debit - total_credit, 2)
    if abs(ecart) > TOLERANCE_EQUILIBRE:
        return False, (
            f"Écriture déséquilibrée : débit {total_debit:.2f} DH, crédit {total_credit:.2f} DH, "
            f"écart de {abs(ecart):.2f} DH."
        )
    return True, ""


def _filtrer_references(brutes, autorisees: list[str]) -> list[str]:
    """
    Ne garde que les références réellement fondées sur l'alerte.

    Même mécanique que le garde-fou anti-hallucination de ai_auditor : le LLM
    peut nommer un article de mémoire, on ne retient que ceux sur lesquels
    l'audit s'appuyait déjà.

    La comparaison passe par `_cle_article` (et non `_normalize_ref`) pour que
    « Article 106 », « Art. 106 » et « Article 106-IV » soient le même article.
    Mesuré : sur une alerte fondée sur « Article 11 », le modèle renvoyait
    « Article 11-II » — la subdivision effectivement applicable, puisqu'on lui
    a donné le texte intégral de l'article. La comparaison stricte vidait la
    liste et faisait échouer toute la génération.

    Ce que le garde-fou continue d'interdire : citer un ARTICLE que l'alerte
    n'a pas retenu. Une subdivision d'un article autorisé reste couverte par
    le texte fourni au modèle, et c'est de toute façon la référence officielle
    de l'alerte (`autorisees`) qui est persistée — jamais la chaîne du LLM.
    """
    if not isinstance(brutes, list):
        return []
    index: dict[str, str] = {}
    for r in autorisees:
        # setdefault : si l'alerte cite déjà « Article 11 » ET « Article 11-II »,
        # la première (la plus générale) reste la forme persistée.
        index.setdefault(_cle_article(r), r)
    retenues: list[str] = []
    for brute in brutes:
        if not isinstance(brute, str):
            continue
        officielle = index.get(_cle_article(brute))
        if officielle and officielle not in retenues:
            retenues.append(officielle)
    return retenues


def _nettoyer_lignes(brutes) -> list[dict]:
    """Normalise les lignes renvoyées par le LLM, sans rien corriger de fond."""
    if not isinstance(brutes, list):
        return []
    propres = []
    for ligne in brutes:
        if not isinstance(ligne, dict):
            continue
        compte = str(ligne.get("compte") or "").strip()
        # Le LLM écrit parfois « 6142 - Transports » : on ne garde que le code.
        code = re.match(r"^\d+", compte)
        propres.append({
            "compte": code.group(0) if code else compte,
            "libelle": str(ligne.get("libelle") or "").strip()[:200],
            "debit": round(float(ligne.get("debit") or 0), 2) if _est_nombre(ligne.get("debit")) else 0.0,
            "credit": round(float(ligne.get("credit") or 0), 2) if _est_nombre(ligne.get("credit")) else 0.0,
        })
    return propres


def _est_nombre(valeur) -> bool:
    try:
        float(valeur)
        return True
    except (TypeError, ValueError):
        return False


def _auto_critique(
    alerte: AlerteRisque, contexte_legal: str, proposition: dict, label: str,
    contexte_ecriture: str = "",
) -> dict:
    """
    Passe de relecture. Retourne {"coherent": bool, "motif": str}.

    Le relecteur reçoit la MÊME écriture réelle que le générateur : sans elle,
    il ne pouvait pas voir qu'une proposition à 1 000 DH corrigeait une pièce
    de 2 500 DH — il relisait un raisonnement, pas une comptabilité.

    En cas d'échec technique du LLM, on retourne « cohérent » : la critique est
    un bonus de qualité, pas un garde-fou de sécurité. La refuser par défaut
    ferait échouer des propositions correctes parce qu'un quota Groq est
    épuisé — les vrais garde-fous (citations, équilibre) sont ailleurs et ne
    dépendent d'aucun modèle.
    """
    prompt = f"""ANOMALIE
{alerte.titre}
{alerte.description}

ÉCRITURE RÉELLE CONCERNÉE
{contexte_ecriture or "non disponible"}

ARTICLES APPLICABLES
{contexte_legal}

PROPOSITION À RELIRE
Type : {proposition.get('type_correction')}
Résumé : {proposition.get('resume')}
Justification : {proposition.get('justification')}
Lignes : {proposition.get('lignes')}"""

    resultat = llm_call_json(CRITIQUE_SYSTEM_PROMPT, prompt, label=f"critique_{label}", model=GROQ_MODEL_FAST)
    if not isinstance(resultat, dict) or "coherent" not in resultat:
        return {"coherent": True, "motif": "", "indisponible": True}
    return {
        "coherent": bool(resultat.get("coherent")),
        "motif": str(resultat.get("motif") or "")[:500],
    }


def _interpreter(brut: dict, references_autorisees: list[str]) -> dict:
    """Transforme la sortie JSON du LLM en proposition normalisée, ou lève."""
    if not isinstance(brut, dict):
        raise RuntimeError("Le modèle n'a pas renvoyé de JSON exploitable.")

    try:
        type_correction = TypeCorrection(str(brut.get("type_correction") or "").strip())
    except ValueError:
        # Repli volontairement conservateur : en cas de type inconnu, on ne
        # suppose pas qu'une écriture est possible.
        type_correction = TypeCorrection.aucune_ecriture

    references = _filtrer_references(brut.get("references"), references_autorisees)
    if not references:
        raise RuntimeError(
            "La proposition ne cite aucun article vérifiable parmi ceux qui fondent l'alerte. "
            "Elle n'est pas enregistrée : une correction sans source n'a aucune valeur devant un contrôle."
        )

    lignes = _nettoyer_lignes(brut.get("lignes")) if type_correction in TYPES_AVEC_ECRITURE else []

    if type_correction in TYPES_AVEC_ECRITURE:
        ok, motif = valider_equilibre(lignes)
        if not ok:
            raise RuntimeError(f"Écriture proposée invalide — {motif}")

    resume = str(brut.get("resume") or "").strip()[:300]
    if not resume:
        raise RuntimeError("La proposition ne comporte aucun résumé exploitable.")

    # Pas de "montant_impact" ici : le LLM ne le produit plus (règle 5 du
    # prompt système). generer_proposition() le complète juste après, en le
    # copiant depuis l'alerte plutôt qu'en le lisant dans `brut`.
    return {
        "type_correction": type_correction,
        "resume": resume,
        "justification": str(brut.get("justification") or "").strip(),
        "references": references,
        "payload": {
            "lignes": lignes,
            "action": str(brut.get("action") or "").strip() or None,
            "date_ecriture": date.today().isoformat(),
            "journal": None,
        },
    }


def generer_proposition(
    alerte: AlerteRisque,
    textes_articles: dict[str, str],
    move: dict | None = None,
    lignes_move: list[dict] | None = None,
) -> dict:
    """
    Produit une proposition de correction pour une alerte.

    `textes_articles` vient de PgVectorStore.get_texts_by_references() appelé
    par la route sur les références DE L'ALERTE — aucune recherche RAG n'est
    déclenchée ici.

    `move` / `lignes_move` sont l'écriture réellement visée, extraite du
    snapshot comptable déjà persisté (aucun appel Odoo, aucune requête
    supplémentaire : la route les tire de `_get_active_accounting_data`). Ils
    sont optionnels pour que le module reste testable sans snapshot, mais leur
    absence n'est pas neutre — le modèle se voit alors interdire de chiffrer
    (règle 7), au lieu d'improviser des montants. Voir
    `_construire_contexte_ecriture` pour ce que leur absence a coûté.

    Lève RuntimeError si aucune proposition défendable ne peut être produite.
    L'appelant ne persiste rien dans ce cas : mieux vaut dire « je n'ai pas de
    proposition » que d'enregistrer une correction non sourcée ou déséquilibrée.
    """
    references_autorisees = _references_alerte(alerte)
    if not references_autorisees:
        raise RuntimeError(
            "Cette alerte ne cite aucun article du CGI : impossible de fonder une correction. "
            "Relancez l'audit pour la régénérer avec ses sources."
        )

    contexte_legal = _construire_contexte_legal(references_autorisees, textes_articles)
    contexte_ecriture = _construire_contexte_ecriture(move, lignes_move)
    prompt = _construire_prompt_utilisateur(alerte, contexte_legal, contexte_ecriture)
    label = (alerte.move_ref or str(alerte.id))[:40]

    brut = llm_call_json(SYSTEM_PROMPT, prompt, label=f"correction_{label}", model=GROQ_MODEL_DEFAULT)
    if brut is None:
        raise RuntimeError("Le modèle n'a pas répondu (quota ou indisponibilité). Réessayez dans un instant.")

    proposition = _interpreter(brut, references_autorisees)

    # ── Boucle agentique : propose -> critique -> révise, un seul tour ────
    critique = _auto_critique(alerte, contexte_legal, {
        **proposition, "lignes": proposition["payload"]["lignes"],
    }, label, contexte_ecriture)

    if not critique["coherent"]:
        prompt_revision = (
            f"{prompt}\n\n"
            f"PREMIÈRE PROPOSITION REJETÉE PAR LA RELECTURE\n"
            f"Proposition : {proposition['resume']}\n"
            f"Motif du rejet : {critique['motif']}\n\n"
            f"Produis une nouvelle proposition qui corrige ce point précis."
        )
        brut2 = llm_call_json(SYSTEM_PROMPT, prompt_revision, label=f"correction_rev_{label}", model=GROQ_MODEL_DEFAULT)
        if brut2 is not None:
            try:
                proposition = _interpreter(brut2, references_autorisees)
                proposition["critique"] = {"revisee": True, "motif_initial": critique["motif"]}
            except RuntimeError:
                # La révision est pire que l'original : on garde l'original, en
                # conservant la trace de la réserve émise. Abandonner ici
                # priverait l'utilisateur d'une proposition par ailleurs valide.
                proposition["critique"] = {"revisee": False, "reserve": critique["motif"]}
        else:
            proposition["critique"] = {"revisee": False, "reserve": critique["motif"]}
    else:
        proposition["critique"] = {"revisee": False, "reserve": None} if not critique.get("indisponible") else {
            "revisee": False, "reserve": None, "relecture_indisponible": True,
        }

    proposition["modele"] = GROQ_MODEL_DEFAULT

    # Montant copié TEL QUEL depuis l'alerte, jamais recalculé ni redemandé
    # au LLM — même principe que "aucune nouvelle recherche RAG" (docstring
    # du module), étendu au chiffre : la génération de correction ne refait
    # pas le travail de l'audit, elle le reprend.
    # Traçabilité : la proposition emporte l'écriture qu'elle prétend corriger.
    # Persisté dans payload_json, donc relisible bien après la génération —
    # sans ça, vérifier a posteriori qu'un montant proposé correspond à une
    # écriture réelle obligerait à retrouver le snapshot de l'époque, qu'une
    # resynchro Odoo a pu remplacer entre-temps.
    proposition["payload"]["ecriture_origine"] = {
        "piece": (move or {}).get("name") or alerte.move_ref,
        "total": float(move["amount_total"]) if move and move.get("amount_total") is not None else None,
        "lignes": [
            {
                "compte": _formater_compte(l.get("account_id")),
                "debit": round(float(l.get("debit") or 0), 2),
                "credit": round(float(l.get("credit") or 0), 2),
            }
            for l in (lignes_move or [])
        ],
    }

    proposition["montant_impact"] = float(alerte.montant_exposition) if alerte.montant_exposition is not None else None
    proposition["categorie_montant"] = alerte.categorie_montant
    proposition["montant_detail"] = alerte.montant_detail
    proposition["montant_hypothese"] = alerte.montant_hypothese

    return proposition
