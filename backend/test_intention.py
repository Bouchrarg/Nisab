"""
test_intention.py — Routage d'intention de l'assistant, avant tout appel RAG.

Script manuel (pas pytest), même convention que test_langue.py.
Lancer depuis backend/ :  python test_intention.py

## Ce qu'on vérifie

1. Une question d'échéance ("quand est ma prochaine déclaration de TVA ?")
   est reconnue par REGEX, sans appel LLM — on le prouve en substituant
   `llm_call_json` par une fonction qui lève : si le classifieur regex
   n'avait pas tranché, le test échouerait au lieu de juste rater le cas.
2. Une question de fond ("la TVA à 20% s'applique-t-elle aux médicaments ?")
   n'est PAS classée "echeance" par erreur — sinon le calcul de calendrier
   répondrait à une question qui portait sur le taux, pas la date.
3. `repondre_echeance` construit une phrase à partir d'événements déjà
   calculés, cible bien la catégorie demandée dans la question, et marque
   toujours `sourced: False` — jamais de RAG, jamais de citation inventée.
4. `choisir_format_reponse` bascule sur "bref" seulement à un article.

Aucune clé LLM n'est nécessaire : les cas testés se tranchent tous par regex.
"""
import sys

from app import intention as it

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


def interdit_llm(*_a, **_k):
    raise AssertionError("le LLM a été appelé alors que la regex devait trancher seule")


print("\n-- 1. Classification déterministe (regex, LLM interdit) --------")
it.llm_call_json = interdit_llm  # si un cas retombe sur le LLM, l'assertion lève

CAS_ECHEANCE = [
    "Quand est ma prochaine déclaration de TVA ?",
    "C'est pour quand la déclaration IS cette année ?",
    "Quelle est la date limite de dépôt pour la taxe professionnelle ?",
    "Il me reste combien de temps pour la déclaration IR ?",
]
for q in CAS_ECHEANCE:
    check(f"'{q}' -> echeance", it.classifier_intention(q, "fr") == "echeance")

CAS_NON_ECHEANCE = [
    ("La TVA à 20% s'applique-t-elle aux médicaments ?", "fr"),
    ("Une charge réglée en espèces est-elle déductible ?", "fr"),
    ("Bonjour", "fr"),
]
for q, langue in CAS_NON_ECHEANCE:
    # Ces cas retombent sur le repli LLM (aucune regex temporelle+obligation
    # ne matche) — on ne peut PAS interdire l'appel ici, seulement vérifier
    # que le résultat n'est jamais "echeance" à tort. On restaure un faux LLM
    # qui répond "legale" pour rester déterministe sans dépendre d'un vrai
    # provider.
    it.llm_call_json = lambda *a, **k: {"categorie": "legale"}
    resultat = it.classifier_intention(q, langue)
    check(f"'{q}' -> pas 'echeance'", resultat != "echeance", resultat)

print("\n-- 2. repondre_echeance — cible la bonne catégorie, jamais sourcée --")
EVENTS = [
    {"date": "2026-09-20", "title": "TVA mensuelle — Déclaration août 2026", "category": "TVA",
     "penalty": "Majoration de 10%"},
    {"date": "2026-10-31", "title": "Acompte IS — 3e trimestre 2026", "category": "IS", "penalty": None},
    {"date": "2027-01-31", "title": "Taxe professionnelle 2027", "category": "Taxes Locales", "penalty": None},
]

r = it.repondre_echeance("Quand est ma prochaine déclaration de TVA ?", EVENTS)
check("cible la catégorie TVA", r["category"] == "TVA", r["category"])
check("reprend la bonne échéance", "TVA mensuelle" in r["answer"], r["answer"][:60])
check("toujours sourced=False", r["sourced"] is False)

r = it.repondre_echeance("C'est quand la taxe professionnelle ?", EVENTS)
check("cible Taxes Locales sans être trompé par 'IS' contenu ailleurs", r["category"] == "Taxes Locales", r["category"])

r = it.repondre_echeance("Quand est ma prochaine échéance ?", EVENTS)
check("sans catégorie explicite -> la plus proche toutes catégories", r["event"]["category"] == "TVA", r["event"])

r = it.repondre_echeance("Quand est la déclaration CNSS ?", EVENTS)
check("catégorie sans événement -> réponse honnête, pas d'improvisation", r["event"] is None and "Aucune" in r["answer"])

print("\n-- 3. choisir_format_reponse --------------------------------------")
check("1 source -> bref", it.choisir_format_reponse([{"reference": "Article 1"}]) == "bref")
check("0 source -> bref", it.choisir_format_reponse([]) == "bref")
check("3 sources -> complet", it.choisir_format_reponse([{}, {}, {}]) == "complet")

print("\n" + ("TOUT EST VERT" if ok else "DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
