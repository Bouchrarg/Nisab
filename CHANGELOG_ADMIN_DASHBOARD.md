# Dashboard admin_plateforme enrichi — fichiers modifiés/ajoutés

Ce zip contient uniquement les fichiers touchés, avec les mêmes chemins que
ton repo (`nisab-app/...`). Copie-les par-dessus les tiens (ou fais un diff
avant si tu as retouché ces fichiers depuis le screenshot).

## Comment appliquer

Depuis la racine de ton repo local :
```
cp -r nisab-app/backend/app/admin.py backend\app\admin.py
cp -r nisab-app/frontend/src/App.css <ton-repo>/frontend/src/App.css
cp -r nisab-app/frontend/src/pages/AdminPage.jsx <ton-repo>/frontend/src/pages/AdminPage.jsx
cp -r nisab-app/frontend/src/pages/PlatformAdminShell.jsx frontend/src/pages/PlatformAdminShell.jsx
cp -r nisab-app/frontend/src/components/layout/PlatformSidebar.jsx frontend/src/components/layout/PlatformSidebar.jsx
cp -r nisab-app/frontend/src/pages/platform <ton-repo>/frontend/src/pages/platform
```
Rien à installer côté npm/pip — que du code réutilisant tes libs existantes
(lucide-react, sqlalchemy).

## Bug corrigé : le scroll qui ne marchait pas

`html, body, #root { overflow: hidden }` (index.css) + `.platform-admin-shell`
qui n'avait que `min-height: 100vh` = contenu rogné, pas juste compact.
Corrigé en donnant à `.platform-admin-shell` la même architecture flex
`height: 100vh` + colonne `overflow-y: auto` que ton shell cabinet
(`.shell` / `.page`) utilise déjà — même pattern, pas de nouveauté à
apprendre.

## Ce qui a changé

**Frontend — nouveau shell multi-pages pour admin_plateforme :**
- `PlatformAdminShell.jsx` (réécrit) : sidebar + 4 pages au lieu d'une seule
  vue corpus.
- `components/layout/PlatformSidebar.jsx` (nouveau) : nav Vue d'ensemble /
  Organisations / Utilisateurs / Corpus & Veille.
- `pages/platform/PlatformOverviewPage.jsx` (nouveau) : KPIs globaux (orgs,
  users par rôle, dossiers, alertes par niveau, exposition financière MAD,
  échéances, simulations, corpus) + activité récente.
- `pages/platform/OrganisationsPage.jsx` (nouveau) : liste paginée +
  recherche + filtre cabinet/PME, panneau détail (users + dossiers de
  l'organisation).
- `pages/platform/UsersPage.jsx` (nouveau) : liste paginée cross-tenant,
  recherche nom/email, filtre par rôle.
- `pages/AdminPage.jsx` : juste le titre de section modifié (évite de
  dupliquer le nouveau header de page "Administration du corpus").
- `App.css` : CSS du shell platform-admin refaite (sidebar + colonne
  scrollable), voir bug ci-dessus.

**Backend — 4 nouveaux endpoints dans `admin.py`** (même router, déjà
protégé par `require_role("admin_plateforme")`) :
- `GET /admin/platform/overview`
- `GET /admin/platform/organisations` (`q`, `type_organisation`, `page`, `limit`)
- `GET /admin/platform/organisations/{id}`
- `GET /admin/platform/users` (`q`, `role`, `organisation_id`, `page`, `limit`)

## ⚠️ Point à garder en tête : RLS

Ces requêtes lisent volontairement cross-tenant (pas de
`set_tenant_context`) — c'est le but d'un back-office plateforme. Ça marche
tant que ta connexion Supabase actuelle bypass la RLS (comportement par
défaut du rôle `postgres`, déjà noté dans ta migration initiale). Si tu
passes un jour à un rôle applicatif dédié sans `BYPASSRLS`, il faudra soit
garder un rôle séparé pour ces routes admin, soit ajouter une policy
explicite "admin_plateforme voit tout". Pas fait ici pour ne pas
complexifier le MVP à ce stade — mais à ne pas oublier avant la mise en
prod réelle.

## Vérifications faites

- `python3 -m ast` sur `admin.py` → syntaxe OK.
- Chaque fichier JSX passé dans esbuild individuellement → OK.
- Bundle esbuild complet depuis `main.jsx` (résolution de tous les imports,
  y compris les nouveaux fichiers) → OK.
- Pas pu faire un `vite build` complet ici (binding natif rolldown manquant
  dans ce sandbox, sans rapport avec le code) — à tester en local avant de
  commit, comme d'habitude.
