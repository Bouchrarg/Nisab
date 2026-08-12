"""
test_circulaires.py — Notes circulaires DGI : jamais citées seules.

Script manuel (pas pytest), même convention que test_langue.py.
Lancer depuis backend/ :  python test_circulaires.py

## Ce qu'on vérifie

1. `rag_retrieval._filtrer_circulaires_isolees` écarte toute NOTE_CIRCULAIRE
   dont aucun article CGI commenté n'est présent dans le même lot de
   résultats — la règle d'autorité centrale de cette fonctionnalité (une
   circulaire engage l'administration, pas le contribuable, jamais citée
   seule).
2. Elle GARDE une circulaire accompagnée de son article CGI compagnon.
3. `generate_answer` (generation.py) ajoute le bloc "SOURCES DE NATURE
   DIFFÉRENTE" au prompt système dès qu'une circulaire figure dans les
   sources, et ne l'ajoute jamais sinon — vérifié en substituant `llm_call`
   pour capturer le prompt système envoyé, sans appel réseau réel.
4. `vectorstore.ArticleMatch` reste construisible sans `type`/
   `articles_cgi_commentes` (défauts None) — hybrid_search() ne les
   renseigne pas, une régression de compatibilité y casserait silencieusement.

Aucune clé LLM ni base Postgres n'est nécessaire.
"""
import sys

from app import generation
from app.rag_retrieval import _filtrer_circulaires_isolees
from app.vectorstore import ArticleMatch

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


def match(reference, type_=None, articles_cgi_commentes=None, score=0.8):
    return ArticleMatch(
        id=hash(reference) % 10_000, reference=reference, source_label=type_ or "CGI",
        document_id="doc", texte=f"texte de {reference}", score=score,
        type=type_, articles_cgi_commentes=articles_cgi_commentes,
    )


print("\n-- 1. Circulaire isolée (aucun article CGI compagnon) -> écartée --")
lot = [
    match("Article 106", type_="CGI"),
    match("Note circulaire n° 728", type_="NOTE_CIRCULAIRE", articles_cgi_commentes="Article 145 | Article 146"),
]
retenus = _filtrer_circulaires_isolees(lot)
check("l'article CGI reste", any(m.reference == "Article 106" for m in retenus))
check("la circulaire isolée est écartée", not any(m.type == "NOTE_CIRCULAIRE" for m in retenus), str([m.reference for m in retenus]))

print("\n-- 2. Circulaire accompagnée de son article CGI -> gardée --")
lot = [
    match("Article 145", type_="CGI"),
    match("Note circulaire n° 728", type_="NOTE_CIRCULAIRE", articles_cgi_commentes="Article 145 | Article 146"),
]
retenus = _filtrer_circulaires_isolees(lot)
check("les deux résultats sont gardés", len(retenus) == 2, str(len(retenus)))
check("la circulaire est bien présente", any(m.type == "NOTE_CIRCULAIRE" for m in retenus))

print("\n-- 3. Plusieurs circulaires, une seule accompagnée --")
lot = [
    match("Article 11", type_="CGI"),
    match("NC-A", type_="NOTE_CIRCULAIRE", articles_cgi_commentes="Article 11"),
    match("NC-B", type_="NOTE_CIRCULAIRE", articles_cgi_commentes="Article 999"),
]
retenus = _filtrer_circulaires_isolees(lot)
refs = {m.reference for m in retenus}
check("NC-A (accompagnée) gardée", "NC-A" in refs, str(refs))
check("NC-B (isolée) écartée", "NC-B" not in refs, str(refs))

print("\n-- 4. Circulaire sans articles_cgi_commentes (None) -> toujours isolée --")
lot = [match("Article 1", type_="CGI"), match("NC-C", type_="NOTE_CIRCULAIRE", articles_cgi_commentes=None)]
retenus = _filtrer_circulaires_isolees(lot)
check("NC-C écartée (pas de rattachement)", not any(m.reference == "NC-C" for m in retenus))

print("\n-- 5. Aucune circulaire dans le lot -> rien ne change --")
lot = [match("Article 1", type_="CGI"), match("Article 2", type_="BULLETIN_OFFICIEL")]
retenus = _filtrer_circulaires_isolees(lot)
check("les deux passent inchangés", len(retenus) == 2)

print("\n-- 6. ArticleMatch reste constructible sans type/articles_cgi_commentes (hybrid_search) --")
m = ArticleMatch(id=1, reference="Article 1", source_label="CGI", document_id="cgi_2026", texte="x", score=0.9)
check("type par défaut = None", m.type is None)
check("articles_cgi_commentes par défaut = None", m.articles_cgi_commentes is None)

print("\n-- 7. generate_answer ajoute le bloc de distinction CGI/DGI seulement si besoin --")
captured = {}


def fake_llm_call(system_prompt, user_prompt, label="llm", max_tokens=None):
    captured["system_prompt"] = system_prompt
    return "réponse factice"


generation.llm_call = fake_llm_call

sources_sans_circulaire = [{"reference": "Article 106", "source_label": "CGI", "texte_complet": "texte", "type": "CGI"}]
generation.generate_answer("question", sources_sans_circulaire)
check("pas de bloc si aucune circulaire", "SOURCES DE NATURE DIFFÉRENTE" not in captured["system_prompt"])

sources_avec_circulaire = [
    {"reference": "Article 106", "source_label": "CGI", "texte_complet": "texte", "type": "CGI"},
    {"reference": "NC-728", "source_label": "DGI", "texte_complet": "texte", "type": "NOTE_CIRCULAIRE"},
]
generation.generate_answer("question", sources_avec_circulaire)
check("bloc présent dès qu'une circulaire figure dans les sources", "SOURCES DE NATURE DIFFÉRENTE" in captured["system_prompt"])
check("bloc distingue explicitement CGI et DGI", "le CGI dispose" in captured["system_prompt"] and "la DGI précise" in captured["system_prompt"])

print("\n" + ("TOUT EST VERT" if ok else "DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
