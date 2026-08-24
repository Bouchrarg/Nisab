"""
Métriques chiffrées de la détection réglée (`app.detection_reglee`) et,
en option, du RAG (`app.ai_auditor.run_ai_rag_audit`) — pour la soutenance.

Contrairement à `test_detection_reglee.py` (assertions booléines sur des cas
précis, but : garde-fou de non-régression), ce script calcule une PRÉCISION
et un RAPPEL chiffrés sur l'ensemble des pièces des 3 scénarios de démo, en
comparant les findings produits à une vérité terrain écrite à la main à
partir de ce que `test_detection_reglee.py` vérifie déjà (mêmes scénarios,
mêmes pièces attendues — pas une nouvelle hypothèse, la formalisation en
métrique de ce qui était déjà vérifié en assertions).

Définitions (à reprendre telles quelles dans docs/PROJET_DOCUMENTATION.md) :
  - Vrai positif (TP)  : la pièce devait être signalée sur cet article, et l'a été.
  - Faux positif (FP)  : la pièce a été signalée alors qu'elle ne devait pas
                          l'être (ou signalée sur le mauvais article).
  - Faux négatif (FN)  : la pièce devait être signalée et ne l'a pas été (ou
                          signalée sur le mauvais article — compte dans les deux).
  - Précision = TP / (TP + FP)   — parmi ce qui est signalé, combien est juste.
  - Rappel    = TP / (TP + FN)   — parmi ce qui aurait dû être signalé, combien l'a été.

Étape déterministe (toujours exécutée, aucune clé API requise) : précision/
rappel de `detecter()` seul.

Étape optionnelle (nécessite GROQ_API_KEY ou OPENROUTER_KEY) : même mesure
sur `run_ai_rag_audit()`, plus le taux d'ACCORD entre RAG et règle déterministe
sur les cas où celle-ci sait trancher — c'est la métrique qui justifie
`detection_reglee.py` en complément du RAG (cf. CLAUDE.md, règle d'architecture
"détection = RAG + règle déterministe, strictement complémentaire").

"""

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath("."))

from app.detection_reglee import detecter
from app.odoo_connector import _demo_commerce, _demo_conforme, _demo_services
from app import metrics

metrics.reset()

# ── Vérité terrain (reprise de test_detection_reglee.py) ───────────────────
VERITE_TERRAIN = {
    "commerce": {
        "FACT-2026-002": "Article 11",
        "FACT-2026-004": "Article 11",
        "IMMO-2026-001": "Article 10",
    },
    "conforme": {},
    "services": {
        "FACT-2026-204": "Article 11",
    },
}

SCENARIOS = {
    "commerce": _demo_commerce,
    "conforme": _demo_conforme,
    "services": _demo_services,
}


def corpus_complet(references):
    return set(references)


def toutes_les_pieces(data: dict) -> set[str]:
    return {m.get("name") for m in data.get("moves", []) if m.get("name")}


def evaluer(nom_scenario: str, data_fn) -> dict:
    """Compare les findings de `detecter()` à la vérité terrain d'un scénario.
    Retourne les compteurs TP/FP/FN pour ce scénario."""
    data = data_fn()
    verite = VERITE_TERRAIN[nom_scenario]
    findings = detecter(data, verifier_references=corpus_complet)
    predit = {f["invoice"]: f["reference_cgi"] for f in findings}

    pieces = toutes_les_pieces(data) | set(verite)
    tp = fp = fn = tn = 0
    details = []
    for piece in sorted(pieces):
        attendu = verite.get(piece)
        obtenu = predit.get(piece)
        if attendu is not None and obtenu == attendu:
            tp += 1
        elif attendu is not None and obtenu != attendu:
            fn += 1
            details.append(f"    MANQUE  {piece} : attendu {attendu}, obtenu {obtenu or '(rien)'}")
        elif attendu is None and obtenu is not None:
            fp += 1
            details.append(f"    FAUX+   {piece} : signalé {obtenu} alors qu'attendu (rien)")
        else:
            tn += 1

    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "details": details}


print("=== Précision / rappel — détection réglée (deterministic, sans LLM) ===\n")

total = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
for nom, data_fn in SCENARIOS.items():
    r = evaluer(nom, data_fn)
    for k in ("tp", "fp", "fn", "tn"):
        total[k] += r[k]
    print(f"Scénario « {nom} » : TP={r['tp']} FP={r['fp']} FN={r['fn']} TN={r['tn']}")
    for d in r["details"]:
        print(d)

precision = total["tp"] / (total["tp"] + total["fp"]) if (total["tp"] + total["fp"]) else float("nan")
rappel = total["tp"] / (total["tp"] + total["fn"]) if (total["tp"] + total["fn"]) else float("nan")

print(f"\nGlobal (3 scénarios, {total['tp'] + total['fp'] + total['fn'] + total['tn']} pièces évaluées) :")
print(f"  Précision = {precision:.0%}  ({total['tp']}/{total['tp'] + total['fp']})")
print(f"  Rappel    = {rappel:.0%}  ({total['tp']}/{total['tp'] + total['fn']})")

ok = precision == 1.0 and rappel == 1.0
if not ok:
    print("\n⚠ Précision/rappel < 100% sur la détection déterministe : c'est une régression,"
          " pas une variance acceptable (contrairement au RAG, ce module n'a pas de marge d'erreur"
          " prévue — cf. detection_reglee.py, docstring de tête).")


# ── Étape optionnelle : RAG (nécessite une clé LLM) ─────────────────────────
GROQ_KEY = os.environ.get("GROQ_API_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

if not (GROQ_KEY or OPENROUTER_KEY):
    print("\n=== RAG : ignoré (aucune clé GROQ_API_KEY / OPENROUTER_KEY dans l'environnement) ===")
else:
    print("\n=== Précision / rappel — audit RAG (appels LLM réels, peut prendre plusieurs minutes) ===")
    from app.ai_auditor import run_ai_rag_audit

    rag_total = {"tp": 0, "fp": 0, "fn": 0}
    accords = desaccords = 0
    for nom, data_fn in SCENARIOS.items():
        data = data_fn()
        verite = VERITE_TERRAIN[nom]
        findings_rag, _echecs, _inconclusifs = run_ai_rag_audit(data)
        predit_rag = {f["invoice"]: f.get("reference_cgi") for f in findings_rag}

        pieces = toutes_les_pieces(data) | set(verite)
        for piece in pieces:
            attendu = verite.get(piece)
            obtenu = predit_rag.get(piece)
            if attendu is not None and obtenu == attendu:
                rag_total["tp"] += 1
            elif attendu is not None:
                rag_total["fn"] += 1
            elif obtenu is not None:
                rag_total["fp"] += 1

            # Taux d'accord RAG vs règle déterministe, uniquement sur les cas
            # où la règle déterministe sait trancher (attendu is not None) —
            # c'est la métrique qui justifie le module en complément du RAG.
            if attendu is not None:
                if obtenu == attendu:
                    accords += 1
                else:
                    desaccords += 1

    rag_precision = rag_total["tp"] / (rag_total["tp"] + rag_total["fp"]) if (rag_total["tp"] + rag_total["fp"]) else float("nan")
    rag_rappel = rag_total["tp"] / (rag_total["tp"] + rag_total["fn"]) if (rag_total["tp"] + rag_total["fn"]) else float("nan")
    print(f"  RAG seul : précision={rag_precision:.0%}  rappel={rag_rappel:.0%}")
    if accords + desaccords:
        print(f"  Accord RAG vs règle déterministe sur les cas chiffrables : "
              f"{accords}/{accords + desaccords} ({accords / (accords + desaccords):.0%})")

    metrics.afficher_resume("Temps d'exécution — audit RAG (LLM + embedding + retrieval)")

sys.exit(0 if ok else 1)
