# Démo — veille personnalisée avec détection réelle de changement

Déroulé reproductible pour prouver, en conditions réelles (vrais PDF CGI,
vrai audit RAG, vraie diffusion), que la veille détecte un changement
**légal réel** — pas juste une réextraction du corpus — et cible le bon
dossier via ses citations existantes. Contexte et justification technique :
voir `backend/app/veille.py` (détection) et le plan
`je-veux-une-vrai-validated-barto` (design).

## Prérequis

- Backend et corpus déjà fonctionnels (CGI 2026 présent et validé).
- `backend/.env` avec `DATABASE_URL`, `GROQ_API_KEY` (ou `OPENROUTER_KEY`),
  `ADMIN_DATABASE_URL`.
- Compte `admin_plateforme` pour déclencher `/admin/veille/diffuser`.

## 1. Backfill réel du corpus (2024, 2025)

Depuis `corpus-pipeline/`, **sauvegarder d'abord** le corpus courant
(mutation réelle, réversible mais autant partir prudent) :

```bash
cp data/corpus.db "data/corpus.db.backup-$(date +%Y%m%d%H%M%S)"
```

Puis, depuis `corpus-pipeline/scripts/` :

```bash
python monitor_cgi.py --year 2024
python monitor_cgi.py --year 2025
```

**Piège rencontré en le faisant réellement** : le pattern d'URL standard
(`.../dgi/{année-1}/CGI-{année}-FR.pdf`) a fonctionné pour 2025 mais pas pour
2024 — le fichier 2024 est en fait à
`https://www.finances.gov.ma/Publication/dgi/2024/CG-2024-fr.pdf` (dossier =
même année, pas année-1 ; nom de fichier "CG" pas "CGI", "fr" pas "FR"). Le
README du pipeline prévenait déjà que le nom change chaque année ; `--year`
échoue proprement avec un message explicite quand ça arrive, à corriger à la
main (via `download_and_register()` avec l'URL réelle) plutôt que de rester
bloqué.

Puis extraction + revue + validation + synchronisation, comme pour un ajout
normal :

```bash
python extract_corpus.py
# Revoir data/exports/articles_conflits_a_verifier.csv si besoin
python validate_articles.py --all
python ../../backend/scripts/ingest_to_supabase.py
```

**Attention** : `extract_corpus.py` réextrait TOUS les documents ayant un PDF
local, y compris ceux déjà validés (2026 y compris) — tout repasse par
`statut='a_verifier'` en SQLite le temps de la revalidation. Sans effet sur
l'app en production tant que `ingest_to_supabase.py` (qui lit uniquement les
lignes `valide`) n'a pas tourné : Postgres garde l'ancienne version valide
jusque-là.

`ingest_to_supabase.py` compare par hash et ne réembedde que ce qui a changé
— sur ce backfill (2024 + 2025 neufs + 2026 réextrait à l'identique) :
366 articles inchangés (pas réembeddés), 752 (ré)embeddés.

**Deux pièges réels rencontrés en le faisant, corrigés dans `veille.py`** (pas
juste théoriques — trouvés en testant contre ce backfill précis, avec de
vraies notifications erronées créées puis nettoyées) :

- **Backfill traité comme un changement.** Ajouter 2024 après que 2025/2026
  sont déjà validés faisait ressortir ses articles comme "première
  apparition" (rien de plus ANCIEN à comparer) — donc "changé", alors que
  2025/2026, déjà connus, sont plus récents. `filtrer_changements_reels`
  vérifie maintenant explicitement qu'aucune version plus récente n'existe
  déjà avant de proposer un changement (`nb_articles_deja_depasses`).
- **BO comparé au CGI par coïncidence de numéro.** Vérifié sur le vrai
  corpus : le "Article 2" du Bulletin Officiel est un article de la LOI DE
  FINANCES elle-même (ses propres dispositions budgétaires), pas l'article 2
  du CGI — deux textes sans rapport qui partagent juste un numéro. La
  comparaison de contenu est maintenant bornée au même type de document
  (CGI compare à CGI, jamais à un BO).

## 2. Audit réellement sourcé sur 2024

Dans l'app (page **Audit**) :

1. Choisir/créer un dossier, charger un scénario Odoo démo
   (`POST /dossiers/{id}/odoo/demo?scenario=commerce`).
2. Dans le nouveau sélecteur **Source du corpus** (au-dessus du bouton
   "Relancer l'analyse"), choisir l'entrée `cgi_2024`.
3. Lancer l'audit. Le RAG (`vectorstore.search(document_id="cgi_2024")`) ne
   peut retrouver que du texte 2024 — les alertes générées citent
   réellement cette version, et `version_corpus` sur la citation l'affiche
   correctement (dérivé de `PgVectorStore.get_document_label`, plus le
   littéral figé "CGI 2026" d'avant).

## 3. Déclencher la veille

Toujours en `admin_plateforme`, `POST /admin/veille/diffuser` :

```json
{ "dry_run": true }
```

Vérifier l'aperçu (`apercu`), puis relancer avec `"dry_run": false`.

Ce qui doit se passer : pour la/les référence(s) citée(s) par l'audit 2024,
`filtrer_changements_reels` compare leur texte à la version légalement la
plus récente déjà dans le corpus (2025 ou 2026, selon ce qui diffère
réellement) — pas à une simple republication. Si le texte a effectivement
changé entre 2024 et 2025/2026 (généralement le cas, une loi de finances
modifie le CGI chaque année), une notification est créée avec un message
explicite : *"Article X a changé depuis Code Général des Impôts 2024
(version 2024-01-01) vers Code Général des Impôts 2026 (version
2026-01-01)..."*.

## 4. Vérifier le résultat

Page **Veille** du dossier : la notification apparaît, non lue, avec le
message ci-dessus et le motif ("Cité dans N alerte(s) de risque sur ce
dossier"). C'est la preuve de bout en bout : corpus réel multi-année → audit
réellement contraint à un millésime → détection réelle de changement de
texte → ciblage par citation existante → notification vérifiable.

## Régression rapide (sans backend ni LLM)

`cd backend && python test_veille.py` — section 6 ("Vraie veille :
republication identique VS changement réel") rejoue le même principe sur une
copie temporaire du corpus, en quelques secondes : une republication à texte
identique ne déclenche rien, une republication avec texte modifié
déclenche. Utile pour vérifier après coup que rien n'a régressé, mais ne
remplace pas le déroulé ci-dessus pour la soutenance (celui-là seul montre
un vrai audit LLM et une vraie diffusion sur données réelles).
