"""
metrics.py — Instrumentation légère des temps d'exécution, pour produire des
métriques chiffrées défendables en soutenance (cahier des charges L57 :
"anti-hallucination = cœur produit" — un claim qui doit pouvoir se chiffrer,
pas seulement s'affirmer).

Volontairement minimal : pas de dépendance externe (pas de Prometheus/OpenTelemetry),
pas de persistance en base. Ce n'est PAS un outil d'observabilité de production,
c'est un instrument de mesure pour les scripts `test_metriques_*.py` — on
chronomètre un run contrôlé (scénarios de démo), on imprime un résumé, on cite
les chiffres dans docs/PROJET_DOCUMENTATION.md et le rapport de stage.

Catégories utilisées dans le projet :
  - "embedding"     : calcul du vecteur de la requête (app/embeddings.py::embed_query)
  - "retrieval_sql" : requête pgvector (app/vectorstore.py::PgVectorStore.search)
  - "llm"           : tout appel LLM (app/llm_client.py::_call_provider — couvre
                       audit, chat, corrections, reformulation, filtrage : un seul
                       point d'entrée pour tous les appels du produit)
  - "audit_total"   : durée complète d'un audit RAG (app/ai_auditor.py::run_ai_rag_audit)

État module-level en mémoire : suffisant ici, ces scripts tournent en process
unique (pas de usage concurrent à mesurer), et `reset()` isole un run du suivant.
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager

_mesures: dict[str, list[float]] = defaultdict(list)


def reset() -> None:
    """Vide les mesures accumulées. À appeler en tête de chaque script de
    métriques, pour ne pas mélanger les durées d'un run précédent."""
    _mesures.clear()


@contextmanager
def mesurer(categorie: str, label: str = ""):
    """
    Chronomètre le bloc englobé et range la durée (secondes) sous `categorie`.

    `label` n'entre pas dans l'agrégation (la clé reste `categorie` seule) —
    il existe pour permettre un `print` de debug ponctuel si besoin, sans
    complexifier `resume()` avec une dimension supplémentaire dont ce projet
    n'a pas l'usage (pas besoin de comparer "llm/chat" vs "llm/audit" séparément,
    juste "combien de temps le LLM prend au total").
    """
    debut = time.perf_counter()
    try:
        yield
    finally:
        _mesures[categorie].append(time.perf_counter() - debut)


def resume() -> dict:
    """
    Agrégats par catégorie : nombre d'appels, temps total, moyenne, p95.
    p95 plutôt que max seul : une mesure isolée de rate-limit/backoff LLM
    fausserait un max, le p95 reste représentatif du cas courant tout en
    signalant la présence d'appels lents.
    """
    out = {}
    for categorie, durees in _mesures.items():
        if not durees:
            continue
        s = sorted(durees)
        n = len(s)
        p95_index = min(n - 1, int(round(0.95 * (n - 1))))
        out[categorie] = {
            "count": n,
            "total_s": round(sum(s), 3),
            "moyenne_s": round(sum(s) / n, 3),
            "p95_s": round(s[p95_index], 3),
        }
    return out


def afficher_resume(titre: str = "Métriques") -> None:
    """Impression tabulaire simple, pour la fin des scripts test_metriques_*.py."""
    r = resume()
    print(f"\n=== {titre} ===")
    if not r:
        print("(aucune mesure enregistrée)")
        return
    for categorie, agg in r.items():
        print(
            f"  {categorie:16s} n={agg['count']:4d}  total={agg['total_s']:8.3f}s  "
            f"moyenne={agg['moyenne_s']:7.3f}s  p95={agg['p95_s']:7.3f}s"
        )
