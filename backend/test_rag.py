from app.vectorstore import PgVectorStore

store = PgVectorStore()

# Requête proche du contenu réel de l'article 193 (paiement en espèces)
queries = [
    "paiement en espèces dépassant 20000 dirhams sanction amende",
    "règlement transaction espèces chèque virement bancaire",
    "FACT-2026-002 Caisse Fournisseur Al Baraka Marchandises Mode: cash",  # requête réaliste type _build_search_query
]

for q in queries:
    print(f"\n--- {q} ---")
    matches = store.search(q, top_k=15)  # recherche vectorielle PURE, pas hybride
    for m in matches:
        marker = " <-- ARTICLE 193 ICI" if m.reference == "Article 193" else ""
        print(f"  {m.reference:25s} | cosine={m.score:.4f} | {m.source_label}{marker}")