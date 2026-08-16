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
  clients sont isolés par Row-Level Security au niveau PostgreSQL — isolation
  prouvée par un script automatisé (`test_rls_isolation.py`), pas seulement
  affirmée.
- **4 rôles** : `collaborateur`, `dirigeant_pme` (shell frontend dédié en
  lecture seule, + app mobile Expo), `admin_cabinet`, `admin_plateforme`
  (équipe Nisab, supervision globale du corpus et des cabinets).
- **Audit IA des écritures** (`ai_auditor.py`) : pipeline RAG en deux temps
  (retrieval large sur le corpus fiscal, puis filtrage de pertinence par LLM),
  complété par une détection réglée déterministe (`detection_reglee.py`) sur
  les articles au calcul chiffrable — le RAG découvre, la règle chiffre.
- **Assistant fiscal en langage naturel** (`rag_retrieval.py` /
  `generation.py`), bilingue français/arabe/darija latine (`langue.py`) :
  questions/réponses sourcées sur le corpus CGI + Bulletin Officiel, citations
  toujours en français même en réponse arabe.
- **Calendrier fiscal** (`tax_calendar.py`) : échéances TVA/IS/IR/CNSS,
  volontairement non-RAG (littéraux écrits à la main, `sourced: false`).
- **Simulation de contrôle fiscal** (`control_simulator.py`) : génère un
  argumentaire de défense à partir des alertes déjà détectées, sans nouvelle
  recherche RAG.
- **Workflow agentique de correction** (`correction_agent.py`) : proposition
  de correction sourcée → validation humaine → brouillon Odoo (`state=draft`,
  jamais `action_post`) — le dernier geste comptable reste au comptable.
- **Veille personnalisée** (`veille.py`) : diffusion ciblée par dossier, un
  article concerne un dossier si celui-ci l'a déjà cité.
- **Connecteurs comptables** : Odoo (XML-RPC, lecture ET écriture) et import
  CSV/Excel (fusion, pas remplacement) via une interface commune
  (`connectors/`). OCR de facture (PaddleOCR) en palier expérimental.
- **Journal des accès** (`journal_acces.py`) : traçabilité des accès aux
  données comptables/fiscales, exigence CNDP (loi 09-08).
- **Invitations par token** pour l'onboarding des collaborateurs/dirigeants
  (pas d'envoi SMTP automatique, lien à transmettre manuellement — choix de
  MVP assumé).

## Architecture

### Backend (`backend/app/`)

Un routeur par domaine, monté directement dans `main.py` (pas d'agrégateur
central), 85 routes au total :

- `auth_router` → `/auth`
- `invitations_router` → `/invitations`
- `dossiers_router` → `/dossiers`
- `ingestion_router` → `/dossiers` (import fichier, réconciliation)
- `corrections_router` → `/dossiers` (workflow agentique)
- `veille_router` → `/dossiers` (notifications)
- `simulation_router` → pas de préfixe, chemins complets type
  `/dossiers/{id}/simulation/run`
- `roi_router` → `/dossiers/{id}/roi`
- `api_router` → pas de préfixe (`/health`, `/search`, `/law/feed`)
- `admin_router` → `/admin` (gated `admin_plateforme`)

Autres modules clés :

- `db.py` / `db_session.py` — session SQLAlchemy standard (`get_db`) vs.
  `get_tenant_db()` qui décode le JWT, résout l'organisation et pose le
  contexte RLS (`set_config('app.current_org_id', ...)`). Toute route
  tenant-scoped **doit** utiliser `get_tenant_db`.
- `models.py` — schéma multitenant + enums (`RoleUtilisateur`,
  `TypeOrganisation`, ...), dont `JournalAcces` (traçabilité CNDP).
- `compliance_checker.py` — **déprécié**, remplacé par la détection RAG-only
  + réglée (`ai_auditor.py` / `detection_reglee.py`). Ne pas relancer.
- `metrics.py` — chronométrage léger (embedding/retrieval/LLM/audit), utilisé
  par les scripts `test_metriques_*.py` pour produire des chiffres cités en
  soutenance.

### Frontend (`frontend/src/`)

Pas de react-router : routing manuel par `useState` + `localStorage`
(`App.jsx`), branché sur `user.role` :

- `admin_plateforme` → `PlatformAdminShell`
- `dirigeant_pme` → `DirigeantShell` (lecture seule)
- sinon (cabinet) → `AppShell` (dashboard, audit, corrections, simulation,
  calendrier, chat, veille, Odoo, invitations, profil)

Pas d'axios : wrapper `fetch` maison (`config/api.js`, `apiFetch` /
`dossierFetch`). L'access token JWT vit en variable JS (pas de localStorage),
seul le refresh token y est stocké.

### Mobile (`nisab-mobile/`)

App Expo (React Native) réservée au rôle `dirigeant_pme` : 3 écrans en
lecture seule (feux tricolores de conformité, échéances, alertes critiques),
même contrat API que `DirigeantShell.jsx`. Routing manuel par `useState`
comme le web (pas de react-navigation).

## Prérequis

- Python 3.11+
- Node.js 18+
- Une base PostgreSQL (Supabase) avec l'extension `pgvector`
- Le corpus fiscal indexé : `corpus-pipeline/` (suivi par ce repo, pas un
  pipeline externe) produit un fichier SQLite pointé par `CORPUS_DB_PATH`
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

**Backend .**. Cible : un service à process long type Render ou
Railway (FastAPI + uvicorn), sur le tier gratuit. Variables d'environnement
identiques à la section Installation ci-dessus, plus `NISAB_ALLOWED_ORIGINS`
pointé sur l'origine Vercel du frontend (plusieurs origines séparées par une
virgule, espaces tolérés de part et d'autre).

**Limite assumée** : le connecteur Odoo
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

Aucune suite pytest/vitest — convention du projet : des scripts manuels
`backend/test_*.py` (`python test_xxx.py`, exit code 0/1), pas de framework.
Points d'entrée notables :

- `test_rls_isolation.py` — preuve automatisée de l'isolation multi-tenant (2 organisations, lecture ET écriture croisées).
- `test_metriques_detection.py` / `test_metriques_hallucination.py` — précision/rappel de la détection, taux de citation/hallucination du chat, chiffrés.
- `test_journal_acces.py`, `test_cle_metier.py`, `test_correction.py`, `test_push_odoo.py`, `test_veille.py`, `test_langue.py`, `test_ocr.py`, `test_regles_montant.py`, `test_detection_reglee.py`, `test_audit_lecture.py`, `test_circulaires.py`, `test_intention.py`, `test_qualification_bo.py`, `test_roi.py`.
- `test_rag.py` — script manuel d'interrogation directe du vectorstore.
