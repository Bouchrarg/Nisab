# Nisab — Copilote fiscal IA (Maroc)

Nisab est un copilote fiscal destiné aux cabinets comptables marocains et à
leurs clients PME. L'objectif : détecter les risques de non-conformité fiscale
dans les écritures comptables, répondre en langage naturel à des questions
fiscales, et le tout **toujours rattaché à une citation vérifiable** (article
du CGI, Bulletin Officiel) — zéro affirmation sans source.

## Stack technique

| Composant | Choix |
|---|---|
| Backend | FastAPI + SQLAlchemy + Alembic |
| Base de données | PostgreSQL (Supabase) + pgvector, Row-Level Security (RLS) |
| Frontend | React + Vite |
| LLM | Groq (Llama 3.3 70B) en primaire, OpenRouter en fallback |
| Embeddings | `intfloat/multilingual-e5-base` |
| Auth | JWT (access 30 min / refresh 14 jours), bcrypt |

## Fonctionnalités

- **Multi-tenant strict** : chaque cabinet (organisation) et ses dossiers
  clients sont isolés par Row-Level Security au niveau PostgreSQL.
- **4 rôles** : `collaborateur`, `dirigeant_pme` (accès lecture seule dédié),
  `admin_cabinet`, `admin_plateforme` (équipe Nisab, supervision globale du
  corpus et des cabinets).
- **Audit IA des écritures** (`ai_auditor.py`) : pipeline RAG en deux temps
  (retrieval large sur le corpus fiscal, puis filtrage de pertinence par LLM)
  qui détecte les risques de non-conformité et les rattache à une citation.
- **Assistant fiscal en langage naturel** (`rag_retrieval.py` /
  `generation.py`) : questions/réponses sourcées sur le corpus CGI + Bulletin
  Officiel.
- **Calendrier fiscal** (`tax_calendar.py`) : échéances TVA/IS, volontairement
  non-RAG (littéraux écrits à la main).
- **Simulation de contrôle fiscal** (`control_simulator.py`) : génère un
  argumentaire de défense à partir des alertes déjà détectées.
- **Connecteur Odoo** (`odoo_connector.py`) : import des écritures comptables
  via XML-RPC pour audit.
- **Invitations par token** pour l'onboarding des collaborateurs/dirigeants
  (envoi SMTP prévu en phase 6, non encore implémenté).

## Architecture

### Backend (`backend/app/`)

Un routeur par domaine, monté directement dans `main.py` (pas d'agrégateur
central) :

- `auth_router` → `/auth`
- `invitations_router` → `/invitations`
- `dossiers_router` → `/dossiers`
- `simulation_router` → pas de préfixe, chemins complets type
  `/dossiers/{id}/simulation/run`
- `api_router` → pas de préfixe (`/health`, `/search`, `/law/feed`)
- `admin_router` → `/admin` (gated `admin_plateforme`)

Autres modules clés :

- `db.py` / `db_session.py` — session SQLAlchemy standard (`get_db`) vs.
  `get_tenant_db()` qui décode le JWT, résout l'organisation et pose le
  contexte RLS (`set_config('app.current_org_id', ...)`). Toute route
  tenant-scoped **doit** utiliser `get_tenant_db`.
- `models.py` — schéma multitenant (14 tables) + enums (`RoleUtilisateur`,
  `TypeOrganisation`, ...).
- `compliance_checker.py` — **déprécié**, remplacé par la détection RAG-only
  (`ai_auditor.py`). Ne pas relancer.

### Frontend (`frontend/src/`)

Pas de react-router : routing manuel par `useState` + `localStorage`
(`App.jsx`), branché sur `user.role` :

- `admin_plateforme` → `PlatformAdminShell`
- `dirigeant_pme` → `DirigeantShell` (lecture seule)
- sinon (cabinet) → `AppShell` (dashboard, audit, simulation, calendrier,
  chat, Odoo, invitations, profil)

Pas d'axios : wrapper `fetch` maison (`config/api.js`, `apiFetch` /
`dossierFetch`). L'access token JWT vit en variable JS (pas de localStorage),
seul le refresh token y est stocké.

## Prérequis

- Python 3.11+
- Node.js 18+
- Une base PostgreSQL (Supabase) avec l'extension `pgvector`
- Un corpus fiscal indexé (pipeline séparé, hors de ce repo) exposant un
  fichier SQLite pointé par `CORPUS_DB_PATH`
- Clés API Groq et/ou OpenRouter

## Installation

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Variables d'environnement (`backend/.env`) :

```
DATABASE_URL=postgresql://...
CORPUS_DB_PATH=../corpus-pipeline/data/corpus.db
GROQ_API_KEY=...
OPENROUTER_KEY=...
JWT_SECRET=...
NISAB_ALLOWED_ORIGINS=http://localhost:5173
```

Créer le premier compte `admin_plateforme` (uniquement via script, jamais via
une route publique) :

```bash
python -m scripts.create_platform_admin
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Variable d'environnement (`frontend/.env`) :

```
VITE_API_URL=http://localhost:8000
```

## Déploiement

**Frontend sur Vercel.** Build Vite statique, `frontend/vercel.json` réécrit
toutes les routes vers `index.html` (le routing est manuel par `useState`
dans `App.jsx`, pas de react-router). Seule variable à poser côté Vercel :
`VITE_API_URL` = l'URL du backend déployé.

**Backend PAS sur Vercel.** Les fonctions serverless coupent à 60 s (300 s en
Pro) et un audit dépasse 5 min en conditions réelles sur un dossier avec
plusieurs dizaines d'écritures (voir le commentaire `AUDIT_TIMEOUT_MS` dans
`frontend/src/App.jsx`). Cible : un service à process long type Render ou
Railway (FastAPI + uvicorn), sur le tier gratuit. Variables d'environnement
identiques à la section Installation ci-dessus, plus `NISAB_ALLOWED_ORIGINS`
pointé sur l'origine Vercel du frontend (plusieurs origines séparées par une
virgule, espaces tolérés de part et d'autre).

**Limite assumée, à annoncer telle quelle** : le connecteur Odoo
(`odoo_connector.py`) est prévu pour joindre une instance sur le réseau du
poste qui appelle l'API — en local ça inclut `http://localhost:8069`. Depuis
un backend déployé sur Render/Railway, `localhost` désigne le conteneur du
backend, pas le poste de démo : la connexion Odoo réelle ne fonctionnera donc
que si l'instance Odoo est elle-même joignable publiquement (URL non-localhost
+ ouverture réseau), ce qui n'est pas la configuration de l'environnement de
test décrit plus haut. La démo cloud reste pleinement fonctionnelle sur les
3 scénarios de démonstration (`odoo_connector.get_demo_data`) et sur l'import
CSV/Excel — ce n'est pas contourné en silence, c'est une limite à énoncer
devant le jury si la question est posée.

## Commandes utiles

| Commande | Depuis | Effet |
|---|---|---|
| `uvicorn app.main:app --reload` | `backend/` | Lance l'API |
| `alembic upgrade head` | `backend/` | Applique les migrations |
| `alembic revision --autogenerate -m "..."` | `backend/` | Génère une migration |
| `python -m scripts.create_platform_admin` | `backend/` | Crée un admin plateforme |
| `python -m scripts.cleanup_test_orgs [--confirm]` | `backend/` | Nettoie les orgs de test (dry-run par défaut) |
| `npm run dev` | `frontend/` | Lance le serveur de dev Vite |
| `npm run build` | `frontend/` | Build de production |
| `npm run lint` | `frontend/` | Lint via oxlint |

## Tests

Aucune suite pytest/vitest pour l'instant. `backend/test_rag.py` est un
script manuel pour interroger le vectorstore directement (pas un test
automatisé).

## État du projet

Phases 0-3 terminées : setup Alembic, schéma DB multitenant + RLS, auth JWT
4 rôles, migration de l'état en mémoire vers des tables persistantes par
dossier. Corpus fiscal : 401 articles validés, 0 conflit non résolu.

En cours : constitution d'une base de test pour la soutenance (cas conformes
et non conformes connus), consolidation de `ai_auditor.py` et
`odoo_connector.py`.

À venir (phases 4-9) : bilingue AR/FR (phase 7), workflow agentique ERP en
mode proposition + validation humaine (jamais d'écriture comptable
automatique).
