# Nisab — Plan d'implémentation

*Feuille de route détaillée, phase par phase. Chaque phase précise : objectif, prérequis, ce qu'on touche en DB, en backend, en frontend, et le critère qui dit "cette phase est terminée". On avance phase par phase, dans cet ordre — je t'accompagne sur chacune quand tu es prêt.*

---

## Principe général

On ne réécrit rien de ce qui marche (RAG, audit, calendrier, veille-corpus). On construit **autour** : une fondation multi-tenant qui manque aujourd'hui, puis on reconnecte les modules existants dessus, puis on comble les modules absents (simulation de contrôle), puis on élargit (ingestion, veille personnalisée), puis on sécurise/déploie.

Stack confirmée (déjà en place, on ne change pas) : FastAPI + Supabase Postgres (pgvector) + React/Vite + Groq/OpenRouter.
Stack qu'on ajoute : SQLAlchemy + Alembic (ORM + migrations), JWT (auth), Row-Level Security Postgres.

---

## Vue d'ensemble des phases

| Phase | Contenu | Bloque quoi si absent |
|---|---|---|
| 0 | Setup projet (dépendances, structure) | Rien ne peut commencer proprement sans ça |
| 1 | Base de données multi-tenant (schéma + RLS) | Toutes les phases suivantes |
| 2 | Authentification & rôles | Phases 3 à 9 (rien n'est "par utilisateur" sans ça) |
| 3 | Migration de l'état en mémoire vers la DB | Persistance réelle par dossier |
| 4 | Simulation de contrôle (Module 4) | Couverture complète du cahier des charges |
| 5 | Ingestion élargie (CSV, OCR, Sage) | Onboarding de dossiers réels |
| 6 | Veille personnalisée liée aux dossiers (Module 6) | Alertes proactives par dossier |
| 7 | Bilingue FR/AR — corpus, assistant, interface | Conformité au cahier des charges (langues v1) |
| 8 | Sécurité, conformité, déploiement | Démo/soutenance "prod-like" |
| 9 | Mobile & notifications (optionnel) | Canal dirigeant PME |

---

## Phase 0 — Setup projet

**Objectif** : préparer le terrain technique avant d'écrire la moindre table.

**Backend**
- Ajouter à `backend/requirements.txt` : `sqlalchemy`, `alembic`, `python-jose[cryptography]`, `passlib[bcrypt]`, `python-multipart` (upload de fichiers, utile dès la phase 5).
- Créer `backend/app/db.py` : moteur SQLAlchemy (`create_engine` sur `DATABASE_URL`, déjà présent dans `.env`), `SessionLocal`, `get_db()` dependency FastAPI.
- Initialiser Alembic (`alembic init migrations`) à la racine de `backend/`, configurer `alembic.ini` et `env.py` pour pointer vers `DATABASE_URL` et vers les futurs modèles SQLAlchemy.

**DB**
- Vérifier l'accès admin à l'instance Supabase déjà utilisée pour pgvector (mêmes identifiants `DATABASE_URL`) — on va y ajouter un schéma applicatif à côté du schéma corpus, pas créer une nouvelle base.

**Frontend**
- Rien à ce stade.

**Critère de fin de phase** : `alembic revision` fonctionne et se connecte à la base sans erreur.

---

## Phase 1 — Base de données multi-tenant

**Objectif** : faire exister `organisation`, `utilisateur`, `dossier` et le reste du MCD, avec isolation stricte par ligne (RLS).

### DB — schéma complet (modèles SQLAlchemy dans `backend/app/models/`)

Tables, dans l'ordre de dépendance :

1. **`organisation`** : `id (uuid pk)`, `nom`, `type_organisation (enum: cabinet | pme)`, `created_at`.
2. **`utilisateur`** : `id (uuid pk)`, `organisation_id (fk)`, `email (unique)`, `password_hash`, `role (enum: collaborateur | dirigeant_pme | admin_cabinet)`, `created_at`.
3. **`dossier`** : `id (uuid pk)`, `organisation_id (fk)`, `raison_sociale`, `secteur_activite`, `regime_is`, `regime_tva`, `exercice_cloture_mois`, `created_at`.
4. **`acces`** : `utilisateur_id (fk)`, `dossier_id (fk)`, `niveau_droit` — table de jonction pour gérer qui, dans un cabinet, a accès à quel dossier.
5. **`connexion_comptable`** : `id`, `dossier_id (fk)`, `type (enum: odoo | sage | csv | ocr)`, `identifiants_chiffres`, `derniere_sync`.
6. **`piece_comptable`** : `id`, `dossier_id (fk)`, `source (odoo/csv/ocr)`, `type_piece`, `donnees_json`, `date_piece`, `created_at`.
7. **`declaration`** : `id`, `dossier_id (fk)`, `type_declaration`, `periode`, `statut`, `date_echeance`.
8. **`alerte_risque`** : `id`, `dossier_id (fk)`, `titre`, `description`, `niveau_risque`, `montant_exposition`, `statut (ouverte/traitee)`, `created_at`.
9. **`simulation_controle`** : `id`, `dossier_id (fk)`, `rapport_json`, `plan_remediation_json`, `created_at`.
10. **`echeance`** : `id`, `dossier_id (fk)`, `type`, `date_limite`, `statut`.
11. **`notification_veille`** : `id`, `dossier_id (fk)`, `article_corpus_reference`, `message`, `lu (bool)`, `created_at`.
12. **`citation`**, **`citation_risque`**, **`citation_simulation`** : `id`, `{reponse_id | alerte_id | simulation_id} (fk)`, `article_reference`, `version_corpus`, `created_at` — traçabilité horodatée exigée par ton propre MCD.

Chaque table (sauf `organisation`) porte, directement ou via jointure, un `organisation_id` ou `dossier_id`.

### DB — Row-Level Security

Pour chaque table métier :
```sql
ALTER TABLE dossier ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON dossier
  USING (organisation_id = current_setting('app.current_org_id')::uuid);
```
Pour les tables liées à `dossier_id` plutôt qu'à `organisation_id` directement (ex. `alerte_risque`), la policy passe par un sous-select sur `dossier`.

### Backend
- Un fichier de modèles par entité dans `backend/app/models/` (ou un seul `models.py` si tu préfères rester simple au début).
- Une migration Alembic unique `0001_initial_schema` qui crée toutes ces tables + les policies RLS.
- Un fichier `backend/app/db_session.py` : fonction `set_tenant_context(db_session, organisation_id)` qui exécute `SET LOCAL app.current_org_id = '...'` au début de chaque requête — on la branchera au middleware d'auth en Phase 2, mais on l'écrit maintenant.

### Frontend
- Rien à ce stade — cette phase est invisible depuis l'UI.

**Critère de fin de phase** : on peut créer à la main (via un script ou `psql`) deux organisations avec un dossier chacune, et vérifier qu'une requête avec `app.current_org_id` réglé sur l'organisation A ne retourne jamais les lignes de l'organisation B.

---

## Phase 2 — Authentification & rôles

**Objectif** : chaque requête sait "qui" (utilisateur), "pour quelle organisation", "avec quel rôle".

### Backend
- `backend/app/auth.py` :
  - `hash_password` / `verify_password` (passlib bcrypt)
  - `create_access_token(user_id, organisation_id, role)` (jose JWT, expiration courte + refresh token)
  - `get_current_user` (FastAPI dependency qui décode le JWT depuis le header `Authorization: Bearer ...`)
- Nouveau router `backend/app/routes_auth.py` :
  - `POST /auth/register` (crée `organisation` + premier `utilisateur admin_cabinet`, ou rattache un utilisateur à une organisation existante sur invitation)
  - `POST /auth/login` → retourne `access_token` + `refresh_token`
  - `POST /auth/refresh`
  - `GET /auth/me`
- Middleware / dependency `require_role(*roles)` réutilisable sur les endpoints sensibles (ex. seul `admin_cabinet` peut gérer les accès).
- Brancher `get_current_user` sur **tous** les routers existants (`api.py`, `admin.py`) : chaque endpoint qui touche à un dossier reçoit maintenant `dossier_id` en paramètre et vérifie via `acces` que l'utilisateur y a droit, puis appelle `set_tenant_context`.
- Corriger `CORSMiddleware` : remplacer `allow_origins=['*']` par la liste réelle des origines (localhost:5173 en dev, domaine de prod ensuite).

### Frontend
- Page `LoginPage.jsx` + (si besoin d'onboarding) `RegisterPage.jsx`.
- `frontend/src/context/AuthContext.jsx` : stocke `access_token` en mémoire (pas en `localStorage` en clair), `refresh_token` en cookie httpOnly si le backend le permet, sinon en `localStorage` en dernier recours documenté.
- `frontend/src/config/api.js` : intercepteur qui ajoute le header `Authorization` à chaque appel.
- Garde de route (`ProtectedRoute`) qui redirige vers `LoginPage` si pas de token valide, et qui adapte l'affichage de `Sidebar.jsx` selon le rôle (ex. `AdminPage` visible seulement pour `admin_cabinet`).
- Sélecteur de dossier actif (si l'utilisateur a accès à plusieurs dossiers) — nouveau composant `DossierSwitcher` dans `Topbar.jsx`.

**Critère de fin de phase** : impossible d'appeler `/audit/run` ou `/chat` sans être authentifié ; deux utilisateurs de deux organisations différentes, connectés en parallèle, ne voient jamais les données l'un de l'autre.

---

## Phase 3 — Migration de l'état en mémoire vers la DB

**Objectif** : supprimer les variables globales et fichiers cache, tout devient lié à un `dossier_id` en base.

### Backend
- `odoo_connector.py` / `api.py` : remplacer `_odoo_session`, `_odoo_data`, `CACHE_FILE` par une lecture/écriture dans `connexion_comptable` + `piece_comptable`, filtrée par `dossier_id` du contexte de requête.
- `_audit_cache` (variable globale) → chaque exécution d'audit écrit ses résultats dans `alerte_risque` (upsert par dossier), avec la clé de hash déjà présente (`_hash_data`) réutilisée comme colonne `hash_donnees` pour savoir si on doit relancer.
- Chat / `generation.py` : chaque réponse produite écrit une ligne dans `citation` (une par article cité), horodatée avec la version courante du corpus (utiliser `documents.version` ou équivalent déjà dans `corpus.db`).
- Ajouter des endpoints de lecture d'historique : `GET /dossiers/{id}/alertes`, `GET /dossiers/{id}/historique-chat`.

### Frontend
- `AuditPage.jsx` et `ChatPage.jsx` : au chargement, aller chercher l'historique persistant du dossier actif plutôt que de repartir de zéro à chaque session.
- `DashboardPage.jsx` : le résumé devient "résumé du dossier actif" au lieu de "résumé de la dernière session".

**Critère de fin de phase** : redémarrer le serveur backend ne fait plus rien perdre ; se reconnecter avec un autre compte du même cabinet montre les mêmes dossiers et alertes.

---

## Phase 4 — Simulation de contrôle (Module 4, à construire entièrement)

**Objectif** : combler le module absent du cahier des charges.

### Backend
- Nouveau fichier `backend/app/control_simulator.py` :
  - Fonction `run_simulation(dossier_id, db)` : récupère les `alerte_risque` ouvertes du dossier, les regroupe par thème de contrôle (TVA déductible, charges non déductibles, cotisation minimale, etc.), et pour chaque thème appelle le LLM (réutiliser `llm_client.py`) avec un prompt dédié pour produire : argumentaire de défense sourcé + plan de remédiation.
  - Réutilise la logique de citation systématique déjà présente dans `generation.py` (même exigence anti-hallucination).
- Nouveau router `backend/app/routes_simulation.py` : `POST /dossiers/{id}/simulation/run`, `GET /dossiers/{id}/simulations` (historique), `GET /simulations/{id}` (détail).
- Persistance dans `simulation_controle` + `citation_simulation`.
- Option export PDF du rapport (skill `pdf`, à activer quand on y sera) pour un livrable imprimable au cabinet.

### Frontend
- Nouvelle page `SimulationPage.jsx` : bouton "Lancer la simulation de contrôle", affichage du rapport par thème (reprendre le style de `FindingCard.jsx` pour cohérence visuelle), bouton export.
- Ajout de l'entrée dans `Sidebar.jsx` / `navigation.js`.
- Rappel visible dans l'UI : "Usage interne uniquement — rien n'est transmis à la DGI" (exigence explicite du cahier des charges).

**Critère de fin de phase** : à partir d'un dossier avec des alertes actives, on obtient un rapport de simulation persisté, sourcé, et consultable plus tard.

---

## Phase 5 — Ingestion élargie (Module 1)

**Objectif** : sortir de la dépendance exclusive à Odoo.

### Backend
- Introduire une interface commune `backend/app/connectors/base.py` : classe abstraite `AccountingConnector` avec méthodes `fetch_invoices()`, `fetch_journal_entries()`, etc. `OdooConnector` existant est adapté pour l'implémenter.
- **Import CSV/Excel** : `backend/app/connectors/csv_connector.py`, utilise `pandas`, mappe les colonnes vers le schéma pivot commun (même format que ce que produit `OdooConnector`), endpoint `POST /dossiers/{id}/import/csv` (upload de fichier).
- **Réconciliation** : `backend/app/reconciliation.py` — compare les pièces importées aux échéances attendues (`tax_calendar.py`) et aux déclarations (`declaration`), produit une liste de pièces manquantes par dossier, endpoint `GET /dossiers/{id}/reconciliation`.
- **OCR (PaddleOCR)** : service séparé si le volume le justifie, sinon fonction synchrone au début — `backend/app/ocr_service.py`, extrait HT/TVA/TTC/ICE d'une facture scannée (PDF/image), convertit vers le schéma pivot, endpoint `POST /dossiers/{id}/import/ocr`.
- **Connecteur Sage** : `backend/app/connectors/sage_connector.py`, même interface que Odoo.

### Frontend
- Nouvelle page ou section `IngestionPage.jsx` : zone de dépôt de fichier (CSV/Excel/scan), sélection du connecteur (Odoo/Sage/import manuel), liste des pièces manquantes détectées par la réconciliation.
- `OdooPage.jsx` devient un onglet parmi plusieurs sources plutôt que la seule voie d'entrée.

**Critère de fin de phase** : un dossier sans Odoo peut être alimenté par CSV, avec une liste de pièces manquantes affichée.

---

## Phase 6 — Veille personnalisée liée aux dossiers (Module 6)

**Objectif** : relier chaque nouvel article/mesure détecté par la veille corpus aux dossiers concernés.

### Backend
- `backend/app/veille_dispatch.py` : job déclenché après chaque `pipeline/run` ou `monitor/run` réussi (voir `admin.py`), qui pour chaque nouvel article `statut = 'valide'` :
  - détermine les secteurs/thèmes concernés (mots-clés simples au départ, classification LLM légère ensuite comme dans `ai_auditor.py`)
  - matche avec `dossier.secteur_activite`
  - crée une ligne `notification_veille`
- Endpoint `GET /dossiers/{id}/veille` (liste), `POST /notifications/{id}/marquer-lu`.
- Canal de poussée initial : e-mail simple (SMTP ou service tiers) déclenché à la création d'une `notification_veille`.
- Scheduler : `APScheduler` en interne, ou tâche cron externe qui appelle l'endpoint admin existant.

### Frontend
- Composant `VeilleFeed.jsx` sur le dashboard du dossier : liste des alertes de veille datées et sourcées (reprendre le scénario auto-liquidation TVA du rapport comme cas de démo).
- Badge de notification non lue dans `Topbar.jsx`.

**Critère de fin de phase** : publier un nouvel article de test dans le corpus déclenche une notification visible sur les dossiers du bon secteur, et sur eux seulement.

---

## Phase 8 — Sécurité, conformité, déploiement

**Objectif** : rendre la plateforme démontrable en conditions proches du réel et défendable devant l'encadrant sur les exigences non-fonctionnelles du cahier des charges.

### Backend / infra
- Vérifier que `.env` est dans `.gitignore`, sortir les secrets vers un gestionnaire dédié si le dépôt est partagé.
- Middleware de journalisation (`backend/app/audit_log.py`) : log `utilisateur_id`, `organisation_id`, endpoint, horodatage dans une table `journal_acces` — exigence CNDP citée dans le cahier des charges.
- `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` (backend + frontend + Postgres local pour dev).
- CI minimale : GitHub Actions (`lint` + tests + build Docker à chaque push).
- Tests d'intégration prioritaires : **isolation multi-tenant** (un utilisateur de l'organisation A ne peut jamais lire un dossier de l'organisation B, même en forçant l'ID dans l'URL) — c'est le test le plus important de toute la plateforme.

### Frontend
- Build de production (`vite build`), variables d'environnement séparées dev/prod.

**Critère de fin de phase** : `docker-compose up` lance toute la stack en local depuis zéro ; les tests d'isolation passent en CI.

---

## Phase 8 — Mobile & notifications (optionnel, selon temps restant)

**Objectif** : canal dirigeant PME simplifié, comme prévu dans le cahier des charges et la stack retenue.

### Frontend mobile
- React Native, réutilisation des composants partageables (comme prévu dans le rapport), vue simplifiée "feux tricolores" consommant les mêmes endpoints REST (`/dossiers/{id}/alertes`, `/dossiers/{id}/echeances`, `/dossiers/{id}/veille`).
- Notifications push (Firebase Cloud Messaging) déclenchées par les mêmes événements que `notification_veille` et `echeance`.

**Si le temps manque** : documenter explicitement ce report en Lot 2 dans le rapport — cohérent avec ce que le rapport fait déjà pour d'autres points, donc défendable devant l'encadrant sans que ce soit vécu comme un manque.

---

## Comment on procède à partir de maintenant

On avance une phase à la fois. Pour chaque phase :
1. Je te donne le code exact à créer/modifier (fichiers complets ou diffs).
2. Tu l'appliques (ou je peux le faire directement si tu me donnes accès au dossier du projet).
3. On vérifie ensemble le critère de fin de phase avant de passer à la suivante.

Dis-moi quand tu es prêt à démarrer la **Phase 0 + Phase 1** (setup + schéma DB/RLS) et on commence.
