# Nisab — Pipeline corpus fiscal (v0)

Pipeline minimal pour constituer et tenir à jour le corpus fiscal MVP
(CGI + Bulletin Officiel), sans étape manuelle bloquante.

## Installation

```bash
cd nisab-corpus
pip install -r requirements.txt --break-system-packages
```

> Nécessite un accès internet standard (finances.gov.ma, sgg.gov.ma).
> Si tu exécutes ça depuis un environnement au réseau restreint
> (sandbox, CI fermée...), les téléchargements échoueront — lance
> ces scripts depuis ta machine locale.

## Utilisation — première initialisation

Dans l'ordre, depuis le dossier `scripts/` :

```bash
cd scripts

# 1. Crée la base SQLite (data/corpus.db)
python init_db.py

# 2. Télécharge le CGI 2026 + le Bulletin Officiel n°7465 bis
python download_sources.py

# 3. Extrait le texte des PDF et découpe par article (statut = a_verifier)
python extract_corpus.py
```

Après l'étape 3, ouvre `data/exports/articles_a_verifier.csv` et
parcours-le rapidement (pas un retype — juste un scan visuel des
références et des débuts de texte pour repérer un découpage cassé).

```bash
# 4a. Si tout est propre : valide tout d'un coup
python validate_articles.py --all

# 4b. Ou valide seulement les IDs propres, laisse le reste de côté
python validate_articles.py --ids 1 2 3 5 8
```

Seuls les articles au statut `valide` doivent être utilisés par le
pipeline RAG.

## Utilisation — monitoring du Bulletin Officiel

```bash
python monitor_bo.py
```

Ce script teste les numéros de BO suivant le dernier connu
(`data/monitor_state.json`) sur le schéma d'URL prévisible de
sgg.gov.ma. Toute nouveauté est journalisée (`veille_log`),
téléchargée et enregistrée avec le statut `a_qualifier` — elle
n'entre pas automatiquement dans le corpus actif, elle attend un
passage par `extract_corpus.py` + relecture, comme les sources
initiales.

À automatiser via cron / tâche planifiée, par exemple une vérification
quotidienne :

```
0 8 * * * cd /chemin/vers/nisab-corpus/scripts && python monitor_bo.py >> ../data/monitor.log 2>&1
```

## Structure du projet

```
nisab-corpus/
├── requirements.txt
├── README.md
├── data/
│   ├── raw_pdfs/              # PDF téléchargés (CGI, BO)
│   ├── exports/                # CSV de relecture générés
│   ├── corpus.db               # base SQLite (créée par init_db.py)
│   └── monitor_state.json      # état du monitoring (dernier n° BO connu)
└── scripts/
    ├── config.py                # URLs sources + chemins centralisés
    ├── init_db.py                # création du schéma SQLite
    ├── download_sources.py       # téléchargement des PDF sources
    ├── extract_corpus.py         # extraction + découpage par article
    ├── validate_articles.py      # validation post-relecture
    └── monitor_bo.py             # surveillance du Bulletin Officiel
```

## Schéma de la base (SQLite)

- **documents** — un PDF source par ligne (CGI, BO), avec son statut
  (`telecharge` → `extrait`, ou `a_qualifier` pour une détection du
  monitoring pas encore traitée)
- **articles** — chaque article découpé, avec `statut` = `a_verifier`
  jusqu'à validation manuelle, puis `valide` — c'est ce que le RAG
  doit interroger
- **veille_log** — historique de chaque vérification du monitoring,
  trouvée ou non (utile pour prouver que le monitoring tourne, même
  les jours sans nouveauté)

## Limites connues (assumées pour le MVP)

- Le découpage par article repose sur une regex qui suppose un format
  d'en-tête `Article X.- Titre` en début de ligne. Sur un texte
  juridique dense (notes de bas de page, mise en page multi-colonnes),
  quelques articles peuvent être mal découpés — d'où l'étape de
  relecture avant validation, jamais une confiance aveugle dans le
  résultat brut.
- Le monitoring ne couvre que le Bulletin Officiel (URL prévisible).
  Les notes circulaires DGI (portail dynamique tax.gov.ma) restent
  hors périmètre du monitoring automatique pour ce MVP — cf. slide de
  décision sur le périmètre du corpus.
- CGI : le lien source change de nom de fichier chaque année
  budgétaire (`config.py` à mettre à jour une fois par an).
