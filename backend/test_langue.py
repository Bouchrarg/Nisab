"""
Verifie la detection de langue et mesure le rappel cross-lingue du retrieval.

## Le chiffre a retenir pour la soutenance

multilingual-e5-base est annonce cross-lingue. Mesure sur CE corpus : une
question posee en arabe et la meme posee en francais ne remontent que ~13 %
d'articles communs sur le top-5. Le modele ne "casse" pas — il retrouve
d'autres articles, plausibles, mais pas les bons. C'est pire qu'un echec
visible : la reponse serait sourcee et fausse.

D'ou la traduction de la requete vers le francais avant la recherche, portee
par l'etape de reformulation qui tournait deja (rag_retrieval.py). Le test
mesure le gain.

Lancer depuis backend/ :  python test_langue.py
(la partie retrieval necessite la base vectorielle ; sans elle, seule la
detection de langue est testee)
"""
import sys

from app.langue import detecter_langue, est_arabe

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


print("\n-- 1. Detection de langue --------------------------------------")
CAS = [
    # (etiquette lisible, texte, langue attendue)
    ("francais simple", "Quelles charges sont deductibles ?", "fr"),
    ("francais avec chiffres", "Le seuil de 5000 DH est-il applicable en 2026 ?", "fr"),
    ("arabe standard", "ما هي شروط خصم الضريبة على القيمة المضافة؟", "ar"),
    ("arabe + terme FR", "ما هي شروط خصم TVA على المشتريات؟", "ar"),
    ("darija latine", "chhal ghadi nkhalles f TVA had chher ?", "ar_latin"),
    ("darija latine 2", "wach khassni ndir declaration daba ?", "ar_latin"),
    ("darija latine 3", "kifach nhesseb cotisation minimale dyal charika ?", "ar_latin"),
    ("chaine vide", "", "fr"),
    ("espaces seuls", "   ", "fr"),
]
for etiquette, texte, attendu in CAS:
    obtenu = detecter_langue(texte)
    # On n'imprime pas le texte arabe : la console Windows est en cp1252 et
    # planterait sur les caracteres non representables.
    check(f"{etiquette:<24} -> {obtenu}", obtenu == attendu, f"attendu {attendu}")

print("\n-- 2. Faux positifs de darija ----------------------------------")
# Un mot isole ne doit pas suffire : MIN_MARQUEURS_DARIJA = 2.
PIEGES = [
    ("nom propre 'Safi'", "La societe Safi Industries est-elle concernee ?"),
    ("mot 'hna' isole", "Le magasin hna est-il assujetti ?"),
    ("francais technique", "Quelle est la base de calcul de la cotisation minimale ?"),
]
for etiquette, texte in PIEGES:
    obtenu = detecter_langue(texte)
    check(f"{etiquette:<24} reste 'fr'", obtenu == "fr", obtenu)

print("\n-- 3. Helper est_arabe -----------------------------------------")
check("'ar' est arabe", est_arabe("ar"))
check("'ar_latin' est arabe", est_arabe("ar_latin"))
check("'fr' ne l'est pas", not est_arabe("fr"))
check("None ne l'est pas", not est_arabe(None))

print("\n-- 4. Rappel cross-lingue du retrieval -------------------------")
try:
    from app.api import get_vectorstore
    from app.rag_retrieval import _reformulate_question

    store = get_vectorstore()
    # Chaque theme : question de reference (FR), une SECONDE formulation
    # francaise (temoin), et la traduction arabe.
    #
    # Le temoin est indispensable pour interpreter le chiffre. Deux
    # formulations differentes d'une meme question ne remontent jamais
    # exactement le meme top-5, meme dans la meme langue : il existe un
    # plancher de bruit. Comparer l'arabe a 100 % n'aurait aucun sens ; il
    # faut le comparer a ce que fait le francais contre lui-meme.
    PAIRES = [
        ("TVA deductible",
         "Quelles sont les conditions de deduction de la TVA sur les achats ?",
         "A quelles conditions peut-on recuperer la TVA payee sur les achats ?",
         "ما هي شروط خصم الضريبة على القيمة المضافة على المشتريات؟"),
        ("Charges non deductibles",
         "Quelles charges ne sont pas deductibles du resultat fiscal ?",
         "Quelles depenses sont exclues du droit a deduction fiscale ?",
         "ما هي التكاليف غير القابلة للخصم من النتيجة الجبائية؟"),
        ("Paiement en especes",
         "Quel est le plafond de paiement en especes pour une charge deductible ?",
         "A partir de quel montant un reglement en liquide n'est-il plus deductible ?",
         "ما هو الحد الأقصى للأداء نقدا بالنسبة لتكلفة قابلة للخصم؟"),
    ]
    TOP_K = 5
    temoin_total = brut_total = traduit_total = 0.0

    print(f"  {'Theme':<26} {'FR temoin':<11} {'AR brut':<10} {'AR traduit':<12} reference FR (top 3)")
    for theme, q_fr, q_fr2, q_ar in PAIRES:
        ref_fr = [m.reference for m in store.search(q_fr, top_k=TOP_K)]

        temoin = [m.reference for m in store.search(q_fr2, top_k=TOP_K)]
        r_temoin = len(set(ref_fr) & set(temoin)) / TOP_K

        brut = [m.reference for m in store.search(q_ar, top_k=TOP_K)]
        r_brut = len(set(ref_fr) & set(brut)) / TOP_K

        # Ce que fait reellement le pipeline : reformulation qui traduit.
        q_traduite = _reformulate_question(q_ar, "test_langue") or q_ar
        traduit = [m.reference for m in store.search(q_traduite, top_k=TOP_K)]
        r_traduit = len(set(ref_fr) & set(traduit)) / TOP_K

        temoin_total += r_temoin
        brut_total += r_brut
        traduit_total += r_traduit
        print(f"  {theme:<26} {r_temoin:>7.0%}     {r_brut:>6.0%}     {r_traduit:>6.0%}       {', '.join(ref_fr[:3])}")

    m_temoin = temoin_total / len(PAIRES)
    m_brut = brut_total / len(PAIRES)
    m_traduit = traduit_total / len(PAIRES)
    print(f"\n  Plancher de bruit (FR reformule en FR) : {m_temoin:.0%}")
    print(f"  Arabe sans traduction                  : {m_brut:.0%}")
    print(f"  Arabe avec traduction (pipeline reel)  : {m_traduit:.0%}")

    check("la traduction ameliore le rappel", m_traduit > m_brut, f"{m_brut:.0%} -> {m_traduit:.0%}")
    # Le vrai critere : l'arabe traduit doit atteindre le meme niveau qu'une
    # reformulation francaise. Au-dela, on mesurerait du bruit de reformulation,
    # pas un probleme de langue. Marge de 10 points pour la variabilite du LLM.
    check("l'arabe traduit atteint le plancher de bruit du francais",
          m_traduit >= m_temoin - 0.10, f"traduit {m_traduit:.0%} vs temoin FR {m_temoin:.0%}")
except Exception as exc:
    print(f"  [i]  Partie retrieval ignoree ({type(exc).__name__}: {str(exc)[:70]})")

print("\n" + ("=> TOUT PASSE" if ok else "=> DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
