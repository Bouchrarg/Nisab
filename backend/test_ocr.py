"""
Verifie l'extraction de champs OCR sur une facture synthetique (app/ocr_extraction.py).

Palier 1 du "petit peu d'OCR" : ce script ne teste PAS un connecteur
comptable (aucune ecriture generee, voir la docstring d'ocr_extraction.py
pour pourquoi). Il verifie seulement que PaddleOCR + les regex de parsing
retrouvent les bons champs sur une image generee a la volee -- pas besoin
d'un vrai scan de facture pour lancer ce test, donc pas de fichier binaire
a versionner dans le depot.

Lancer depuis backend/ :  python test_ocr.py
(paddleocr telecharge ses modeles au premier lancement -- ~250 Mo, prevoir
une connexion. Sans paddleocr installe, le test est ignore proprement.)
"""
import io
import sys

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


def _generer_facture_demo() -> bytes:
    """
    Dessine une fausse facture en memoire (PIL) : aucun fichier a versionner,
    et le test reste reproductible sur n'importe quelle machine.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (700, 500), "white")
    d = ImageDraw.Draw(img)
    lignes = [
        "FACTURE N FACT-2026-045",
        "Date : 12/07/2026",
        "",
        "Fournisseur : Atlas Negoce SARL",
        "ICE : 001234567000089",
        "",
        "Marchandises diverses   8500.00 DH",
        "TVA 20%                 1700.00 DH",
        "Total TTC               10200.00 DH",
        "",
        "Mode de reglement : Especes",
    ]
    y = 20
    for ligne in lignes:
        d.text((20, y), ligne, fill="black")
        y += 35
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


print("\n-- 1. Extraction de champs sur une facture synthetique ----------")
try:
    from app.ocr_extraction import extraire_champs_facture

    contenu = _generer_facture_demo()
    resultat = extraire_champs_facture(contenu, "facture_demo.png")

    print(f"  {len(resultat.texte_brut)} ligne(s) reconnue(s), "
          f"confiance moyenne {resultat.confiance_moyenne:.0%}")
    for ligne in resultat.texte_brut:
        print(f"    [{ligne.confiance:.0%}] {ligne.texte}")

    c = resultat.champs
    check("date extraite", c.date == "2026-07-12", f"obtenu {c.date}")
    check("ICE extrait", c.ice == "001234567000089", f"obtenu {c.ice}")
    check("montant TTC extrait", c.montant_ttc == 10200.0, f"obtenu {c.montant_ttc}")
    check("numero de piece extrait", c.numero_piece is not None and "2026-045" in c.numero_piece,
          f"obtenu {c.numero_piece}")
    check("avertissement present (pas de faux sentiment de fiabilite)",
          "écriture" in resultat.avertissement.lower() and "vérifi" in resultat.avertissement.lower())

except ImportError as exc:
    print(f"  [i]  paddleocr non installe, test ignore ({exc})")
except Exception as exc:
    check(f"extraction sans exception ({type(exc).__name__}: {str(exc)[:120]})", False)

print("\n-- 2. Formats rejetes proprement ---------------------------------")
try:
    from app.ocr_extraction import OcrError, extraire_champs_facture

    leve = False
    try:
        extraire_champs_facture(b"peu importe", "grand_livre.csv")
    except OcrError:
        leve = True
    check("un .csv est rejete avant tout appel OCR (pas de cout inutile)", leve)
except ImportError:
    print("  [i]  paddleocr non installe, test ignore")

print("\n" + ("=> TOUT PASSE" if ok else "=> DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
