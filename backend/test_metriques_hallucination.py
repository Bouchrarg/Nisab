"""
Métriques de couverture par citation / hallucination — assistant chat
(`app.rag_retrieval` + `app.generation`), pour la soutenance.

Nécessite GROQ_API_KEY ou OPENROUTER_KEY (appels LLM réels — reformulation +
filtrage + génération par question, donc ~3 appels x ~18 questions). À NE PAS
relancer en boucle de debug (quota Groq gratuit serré, cf. llm_client.py) : un
run suffit, le résultat est destiné à être cité tel quel dans
docs/PROJET_DOCUMENTATION.md (section 10, Chat) et le rapport de stage.

## Définition retenue pour "hallucination" (à réutiliser mot pour mot ailleurs)

Ce n'est PAS un jugement de qualité de la réponse (trop flou, non mesurable
sans juge humain ou LLM tiers — hors budget de ce projet). C'est un fait
vérifiable automatiquement : la réponse cite-t-elle une référence d'article
("Article \\d+") alors qu'AUCUNE citation n'a été retenue par le filtrage RAG
(`retrieve_sourced_articles`) ? Si oui, c'est une hallucination avérée — le
modèle affirme une base légale qu'aucune source vérifiée ne soutient. C'est le
SEUL cas qui compte comme un échec ; une réponse sans citation qui reconnaît
son incertitude est le comportement voulu, pas un défaut.

Trois catégories de résultat par question :
  - SOURCÉE   : >=1 citation retenue par le filtre RAG.
  - REFUS     : 0 citation retenue, et la réponse ne cite aucun article —
                comportement voulu (le produit dit "je ne sais pas" plutôt que
                d'improviser).
  - HALLUCINÉ : 0 citation retenue, MAIS la réponse cite un article quand
                même. Cet indicateur doit rester à 0 — ce n'est pas une marge
                de tolérance, contrairement à d'autres métriques du produit.

Ne tourne jamais sur un dossier réel — questions génériques uniquement,
cohérent avec la démo (`odoo_connector.py`).
"""
import io
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath("."))

# Chargé explicitement ICI : les modules app.* ne sont importés qu'après la
# vérification de clé ci-dessous (pour ne rien importer d'inutile si le
# script s'arrête tout de suite), donc leur load_dotenv() interne n'aurait
# pas encore tourné au moment de ce test.
from dotenv import load_dotenv
load_dotenv()

GROQ_KEY = os.environ.get("GROQ_API_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
if not (GROQ_KEY or OPENROUTER_KEY):
    print("Aucune clé GROQ_API_KEY / OPENROUTER_KEY dans l'environnement — script ignoré.")
    sys.exit(0)

from app.api import get_vectorstore
from app.generation import generate_answer
from app.intention import choisir_format_reponse
from app.langue import detecter_langue
from app.rag_retrieval import retrieve_sourced_articles
from app.text_cleaning import clean_article_text
from app import metrics

metrics.reset()

DELAI_ENTRE_QUESTIONS_S = 2.0  # ménage le quota Groq (tier gratuit)

# ── Banc de questions ────────────────────────────────────────────────────
# "sujet" documente l'intention (pas une vérité terrain stricte : on MESURE
# le comportement réel, on ne le présuppose pas). Mélange volontaire :
# - fiscal marocain, sujets couverts par le corpus CGI/BO -> attendu SOURCÉE ;
# - hors sujet fiscal, ou fiscalité étrangère -> attendu REFUS (ou SOURCÉE si
#   le filtre RAG laisse passer un faux positif thématique, ce qui serait
#   justement une donnée intéressante à voir sortir du script) ;
# - 4 questions en arabe/darija, dont 2 hors sujet, pour vérifier que le
#   comportement de refus tient aussi cross-lingue (cf. langue.py, 53% de
#   rappel mesuré contre 13% sans reformulation).
QUESTIONS = [
    ("fiscal_in_scope", "Quel est le taux normal de TVA au Maroc ?"),
    ("fiscal_in_scope", "Dans quelle limite une charge réglée en espèces reste-t-elle déductible ?"),
    ("fiscal_in_scope", "Quel est le plafond d'amortissement déductible pour un véhicule de tourisme ?"),
    ("fiscal_in_scope", "Quelles dépenses sont exclues du droit à déduction de la TVA ?"),
    ("fiscal_in_scope", "Quelles sont les obligations de déclaration de la TVA pour une PME ?"),
    ("fiscal_in_scope", "Comment est calculé l'IS pour une société soumise au régime de droit commun ?"),
    ("fiscal_in_scope", "Quelles sont les sanctions en cas de règlement en espèces au-delà du seuil légal ?"),
    ("fiscal_in_scope", "Quelles charges sont visées par l'article 10 du CGI ?"),
    ("fiscal_hors_scope", "Quel est le taux de TVA applicable en France pour la restauration ?"),
    ("hors_sujet", "Quelle est la météo prévue à Casablanca ce week-end ?"),
    ("hors_sujet", "Peux-tu me donner une recette de tajine aux pruneaux ?"),
    ("hors_sujet", "Comment configurer un serveur Nginx en reverse proxy ?"),
    ("fiscal_in_scope_ar", "ما هي النسبة العادية للضريبة على القيمة المضافة في المغرب؟"),
    ("fiscal_in_scope_darija", "chhal howa lplafond dyal deduction dyal charge li mkhalssa b cash?"),
    ("hors_sujet_ar", "شنو الطقس ف الدار البيضاء هاد الويكاند؟"),
    ("hors_sujet_darija", "3tini recette dyal tajine bel barkouk."),
]


def classifier(reponse: str, nb_citations: int) -> str:
    if nb_citations > 0:
        return "SOURCEE"
    cite_un_article = bool(re.search(r"[Aa]rticle\s+\d+", reponse or ""))
    return "HALLUCINE" if cite_un_article else "REFUS"


store = get_vectorstore()
resultats = []

print(f"=== Banc de {len(QUESTIONS)} questions — chat sourcé (RAG + génération) ===\n")

for i, (sujet, question) in enumerate(QUESTIONS):
    langue = detecter_langue(question)
    matches = retrieve_sourced_articles(store, question, label=f"metriques_{i}", langue=langue)
    sources = [
        {
            "id": m.id, "reference": m.reference, "source_label": m.source_label,
            "score": round(m.score, 4), "extrait": clean_article_text(m.texte)[:280],
            "texte_complet": clean_article_text(m.texte), "type": m.type,
        }
        for m in matches
    ]

    if not sources:
        reponse = "Aucun article pertinent trouvé."
    else:
        try:
            reponse = generate_answer(
                question, sources, langue=langue,
                format_reponse=choisir_format_reponse(sources),
            )
        except Exception as exc:
            reponse = f"[ERREUR TECHNIQUE : {exc}]"

    categorie = classifier(reponse, len(sources))
    resultats.append({"sujet": sujet, "question": question, "langue": langue,
                       "nb_citations": len(sources), "categorie": categorie})

    print(f"[{i+1:2d}/{len(QUESTIONS)}] ({sujet}, {langue}) \"{question[:60]}\"")
    print(f"        -> {len(sources)} citation(s) -> {categorie}")

    time.sleep(DELAI_ENTRE_QUESTIONS_S)

# ── Synthèse ─────────────────────────────────────────────────────────────
print("\n=== Synthèse ===")
n = len(resultats)
n_sourcee = sum(1 for r in resultats if r["categorie"] == "SOURCEE")
n_refus = sum(1 for r in resultats if r["categorie"] == "REFUS")
n_hallucine = sum(1 for r in resultats if r["categorie"] == "HALLUCINE")

print(f"  Sourcée   : {n_sourcee}/{n} ({n_sourcee / n:.0%})")
print(f"  Refus     : {n_refus}/{n} ({n_refus / n:.0%})")
print(f"  Halluciné : {n_hallucine}/{n} ({n_hallucine / n:.0%})  <- doit être 0")

if n_hallucine:
    print("\n⚠ Cas hallucinés détectés :")
    for r in resultats:
        if r["categorie"] == "HALLUCINE":
            print(f"    - \"{r['question']}\" ({r['sujet']}, {r['langue']})")

metrics.afficher_resume("Temps d'exécution — chat (embedding + retrieval + LLM, par étape)")

sys.exit(0 if n_hallucine == 0 else 1)
