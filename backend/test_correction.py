"""
Verifie les garde-fous du workflow de correction (bloc 2), sans appeler le LLM.

Ce qui est teste ici est ce qui doit tenir meme quand le modele delire :
  - une ecriture desequilibree n'est jamais acceptee
  - une reference que l'alerte ne citait pas est ecartee
  - une proposition sans aucune reference verifiable est refusee
  - une anomalie sans correction comptable ne produit pas d'ecriture inventee

Lancer depuis backend/ :  python test_correction.py
"""
import sys
import unicodedata

from app.correction_agent import _filtrer_references, _interpreter, _nettoyer_lignes, valider_equilibre
from app.models import TypeCorrection
from app.secrets_store import chiffrer, cle_disponible, dechiffrer

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


def sans_accents(t: str) -> str:
    """Les messages d'erreur sont accentues, les motifs attendus non."""
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()


def refuse(label, brut, refs, attendu_dans_message=""):
    """_interpreter doit lever RuntimeError, avec un message qui explique quoi."""
    try:
        _interpreter(brut, refs)
    except RuntimeError as exc:
        detail = str(exc)[:70]
        trouve = sans_accents(attendu_dans_message) in sans_accents(str(exc)) if attendu_dans_message else True
        check(label, trouve, detail)
        return
    check(label, False, "aucune erreur levee")


EQ = [{"compte": "6142", "libelle": "Charge", "debit": 1200.0, "credit": 0},
      {"compte": "4411", "libelle": "Fournisseur", "debit": 0, "credit": 1200.0}]

print("\n-- 1. Equilibre en partie double (garde-fou sans LLM) -----------")
check("ecriture equilibree acceptee", valider_equilibre(EQ)[0])
check("desequilibre refuse", not valider_equilibre(
    [{"compte": "6142", "debit": 1200.0, "credit": 0}, {"compte": "4411", "debit": 0, "credit": 1000.0}])[0])
check("ecart chiffre dans le message", "200.00" in valider_equilibre(
    [{"compte": "6142", "debit": 1200.0, "credit": 0}, {"compte": "4411", "debit": 0, "credit": 1000.0}])[1])
check("ligne unique refusee", not valider_equilibre([{"compte": "6142", "debit": 100, "credit": 0}])[0])
check("aucune ligne refusee", not valider_equilibre([])[0])
check("montant negatif refuse", not valider_equilibre(
    [{"compte": "6142", "debit": -100, "credit": 0}, {"compte": "4411", "debit": 0, "credit": -100}])[0])
check("debit ET credit sur une ligne refuse", not valider_equilibre(
    [{"compte": "6142", "debit": 100, "credit": 100}, {"compte": "4411", "debit": 0, "credit": 0}])[0])
check("compte manquant refuse", not valider_equilibre(
    [{"compte": "", "debit": 100, "credit": 0}, {"compte": "4411", "debit": 0, "credit": 100}])[0])
check("arrondi au centime tolere", valider_equilibre(
    [{"compte": "6142", "debit": 1200.004, "credit": 0}, {"compte": "4411", "debit": 0, "credit": 1200.0}])[0])

print("\n-- 2. Filtrage des references (anti-hallucination) --------------")
autorisees = ["Article 106", "Article 146"]
check("reference legitime conservee", _filtrer_references(["Article 106"], autorisees) == ["Article 106"])
check("casse et abreviation normalisees", _filtrer_references(["article 106"], autorisees) == ["Article 106"])
check("reference inventee ecartee", _filtrer_references(["Article 999"], autorisees) == [])
check("melange : seule la legitime survit",
      _filtrer_references(["Article 999", "Article 146"], autorisees) == ["Article 146"])
check("doublons supprimes", _filtrer_references(["Article 106", "article 106"], autorisees) == ["Article 106"])
check("entree non-liste ignoree", _filtrer_references("Article 106", autorisees) == [])

print("\n-- 3. Nettoyage des lignes produites par le LLM -----------------")
lignes = _nettoyer_lignes([{"compte": "6142 - Transports", "libelle": "x", "debit": "1200", "credit": None}])
check("code extrait de '6142 - Transports'", lignes[0]["compte"] == "6142", lignes[0]["compte"])
check("montant texte converti", lignes[0]["debit"] == 1200.0)
check("credit None -> 0.0", lignes[0]["credit"] == 0.0)

print("\n-- 4. Interpretation d'une sortie LLM ---------------------------")
valide = {"type_correction": "ecriture_od", "resume": "Reintegrer la charge",
          "justification": "Parce que.", "references": ["Article 106"],
          "montant_impact": 1200.0, "lignes": EQ}
p = _interpreter(valide, autorisees)
check("proposition valide acceptee", p["type_correction"] == TypeCorrection.ecriture_od)
check("references filtrees conservees", p["references"] == ["Article 106"])
check("lignes presentes", len(p["payload"]["lignes"]) == 2)

refuse("aucune reference verifiable -> refus",
       {**valide, "references": ["Article 999"]}, autorisees, "source")
refuse("references vides -> refus", {**valide, "references": []}, autorisees, "source")
refuse("ecriture desequilibree -> refus",
       {**valide, "lignes": [{"compte": "6142", "debit": 1200, "credit": 0},
                             {"compte": "4411", "debit": 0, "credit": 999}]}, autorisees, "desequilibr")
refuse("resume vide -> refus", {**valide, "resume": ""}, autorisees, "resume")

print("\n-- 5. Anomalie sans correction comptable ------------------------")
sans_ecriture = {"type_correction": "piece_a_reclamer", "resume": "Reclamer l'ICE du fournisseur",
                 "justification": "Mention obligatoire.", "references": ["Article 146"],
                 "action": "Demander l'ICE", "lignes": EQ}
p2 = _interpreter(sans_ecriture, autorisees)
check("type documentaire conserve", p2["type_correction"] == TypeCorrection.piece_a_reclamer)
check("lignes d'ecriture ecartees malgre le LLM", p2["payload"]["lignes"] == [],
      "le LLM en proposait 2, elles sont retirees")
check("action conservee", p2["payload"]["action"] == "Demander l'ICE")

inconnu = _interpreter({**valide, "type_correction": "n_importe_quoi"}, autorisees)
check("type inconnu -> repli sans ecriture", inconnu["type_correction"] == TypeCorrection.aucune_ecriture)

print("\n-- 6. Chiffrement des identifiants ------------------------------")
check("NISAB_SECRET_KEY configuree", cle_disponible())
if cle_disponible():
    secret = {"url": "http://localhost:8069", "db": "Nisab_demo", "username": "compta@client.ma", "password": "Motdepasse-Odoo-2026!"}
    jeton = chiffrer(secret)
    check("aller-retour chiffrement", dechiffrer(jeton) == secret)
    check("mot de passe absent du texte chiffre", secret["password"] not in jeton)
    check("deux chiffrements different (IV aleatoire)", chiffrer(secret) != jeton)
    try:
        dechiffrer(jeton[:-6] + "AAAAAA")
        check("jeton altere rejete", False, "accepte alors qu'il est corrompu")
    except RuntimeError:
        check("jeton altere rejete", True)

print("\n" + ("=> TOUT PASSE" if ok else "=> DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
