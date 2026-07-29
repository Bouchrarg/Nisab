
un backend RAG minimal branché sur le corpus fiscal (`corpus-pipeline/`), et un frontend de chat pour l'interroger.


## Ce qui est fait

- **Backend** : `TfidfVectorStore` charge les 403 articles `valide` de `corpus-pipeline/data/corpus.db`, indexe en TF-IDF (bi-grammes,accents normalisés) et sert `/health`, `/search` (récupération pure)et `/chat` (RAG complet). Sans `API_KEY`, `/chat` retourne quand même les articles pertinents ("mode récupération seule") .
- **Frontend** : interface de chat ,affiche la réponse + les articles sources cités sous forme de cartes, indicateur d'état du backend en direct.

## Ce qui n'est pas fait


- **pgvector / PostgreSQL** : pas encore branché. `TfidfVectorStore`est un stub qui respecte l'interface `VectorStore` (`backend/app/vectorstore.py`) — le jour où Postgres est prêt,
  il suffit d'écrire une classe `PgVectorStore(VectorStore)` avec de  vrais embeddings (Claude/OpenAI) et de changer une ligne dans
  `get_vectorstore()` (`backend/app/main.py`). Aucun autre fichier
  à toucher.

## Lancer le backend

```bash
cd backend
pip install -r requirements.txt --break-system-packages
export CORPUS_DB_PATH=../corpus-pipeline/data/corpus.db

uvicorn app.main:app --reload --port 8000
```

Test rapide :
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query": "Quelles societes sont exclues du champ de l IS ?"}'
```

## Lancer le frontend

```bash
cd frontend
npm install
npm run dev
```
