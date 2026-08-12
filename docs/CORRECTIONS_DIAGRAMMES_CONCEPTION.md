# Corrections à apporter aux diagrammes Merise/UML (Chapitre II)

> Comparaison entre `C:\Users\tatch\Desktop\PFA_IAAI_NISAB\Conception-Mersise-UML\Merise+UML.drawio\`
> (7 fichiers) et le code réel du dépôt (`backend/app/models.py`, migration
> RLS, `ai_auditor.py`, `control_simulator.py`, `llm_client.py`,
> `routes_dossiers.py`, `routes_invitations.py`, `admin.py`, `ocr_extraction.py`,
> `veille.py`). Classé par gravité : d'abord les erreurs factuelles
> (donneraient une réponse fausse en soutenance si le jury pose la question),
> puis les omissions (fonctionnalités réelles absentes du diagramme), puis
> les nuances de terminologie (peu risquées, à corriger si le temps le permet).

---

## 🔴 Priorité 1 — Erreurs factuelles (à corriger avant toute présentation)

### 1. Fournisseur LLM incorrect — `Nisab_UML_Sequence_Assistant.drawio`

Le lifeline est libellé **« LLM (API Anthropic) »** (cellule `n12`). C'est
factuellement faux : le projet utilise **Groq (Llama 3.3 70B) en primaire**,
avec **repli automatique sur OpenRouter** en cas d'indisponibilité — jamais
l'API Anthropic directement (`backend/app/llm_client.py`, docstring de tête
: *"Client LLM unifié avec fallback Groq → OpenRouter"*).

**Correction** : renommer la lifeline en « LLM (Groq — Llama 3.3 70B, repli
OpenRouter) », ou scinder en deux lifelines si le diagramme doit montrer le
mécanisme de fallback.

C'est la correction la plus visible/vérifiable pour un jury — à traiter en
premier.

### 2. Simulation de contrôle : pas de nouvelle recherche RAG — `Nisab_UML_Sequence_Controle.drawio`

Le diagramme fait passer la génération d'argumentaire par un
**« Orchestrateur RAG »** qui « génère un argumentaire sourcé pour chaque
risque (avec citations ArticleCorpus) » (cellules `n10`, `n18`) — ce qui
laisse croire qu'une **nouvelle recherche documentaire** a lieu au moment de
la simulation.

C'est l'inverse de ce qui est implémenté, et c'est une règle d'architecture
explicitement documentée dans le projet (`control_simulator.py`, docstring
de tête) : *« Ne relance AUCUNE recherche RAG : réutilise directement
`reference_cgi`/`rag_sources_json` déjà persistés sur chaque `AlerteRisque`
au moment de l'audit »*. La raison : garantir que l'audit et la simulation
ne citent jamais deux références différentes pour la même anomalie.

**Correction** : remplacer la lifeline « Orchestrateur RAG » par quelque
chose comme « Service Simulation » qui **relit** les citations déjà
stockées sur les `AlerteRisque` (interaction avec la base de données, pas
avec le moteur de recherche vectorielle), puis appelle le LLM uniquement
pour **rédiger l'argumentaire** à partir de ces citations déjà connues —
pas pour en chercher de nouvelles.

### 3. OCR : ne persiste rien et n'alimente pas la réconciliation — `Nisab_UML_UseCase.drawio`

Le cas d'utilisation « Importer des documents via OCR » (u1_3) est relié en
`«extends»` à « Réconcilier les pièces manquantes » (u1_4), ce qui laisse
entendre que les données extraites par OCR rejoignent le pipeline de
réconciliation comme les autres connecteurs.

Réel (`backend/app/ocr_extraction.py`, section dédiée dans la doc projet) :
l'OCR extrait 4 champs (date, montant TTC, ICE, n° de pièce) d'une image de
facture et les renvoie à l'utilisateur **pour vérification humaine** — *"ne
persiste rien"*, aucune `PieceComptable` créée, donc **rien à réconcilier**
automatiquement à partir de ce flux.

**Correction** : retirer le lien `«extends»` entre OCR et Réconciliation,
ou le remplacer par une note explicite du type « champs à ressaisir
manuellement, pas d'alimentation automatique du dossier ».

### 4. Endpoints d'API inexacts — `Nisab_UML_Sequence_Ingestion.drawio` et `Nisab_UML_Sequence_Assistant.drawio`

- Ingestion : le diagramme montre `POST /ingestion/importer`. Les routes
  réelles sont `POST /dossiers/{dossier_id}/odoo/connect`,
  `POST /dossiers/{dossier_id}/odoo/demo` (connexion Odoo / données de
  démonstration) et l'import fichier dans `routes_ingestion.py`.
- Assistant : le diagramme montre `POST /assistant/question`. La route
  réelle est `POST /dossiers/{dossier_id}/chat` (ou `/chat/general` en mode
  sans dossier actif).

**Correction** : renommer les endpoints dans les libellés des messages pour
qu'ils correspondent aux routes réelles — un jury technique peut vérifier
ça directement dans Swagger (`/docs`).

---

## 🟠 Priorité 2 — Fonctionnalités réelles absentes des diagrammes

### 5. Le rôle `admin_plateforme` est totalement absent — `Nisab_UML_UseCase.drawio` et `Nisab_UML_Classes.drawio`

Aucun acteur « Administrateur Plateforme » dans le diagramme de cas
d'utilisation (seulement Collaborateur Cabinet, Dirigeant PME, Système de
veille réglementaire, Administrateur Cabinet), et aucune sous-classe
`AdminPlateforme` dans le diagramme de classes (seulement `Collaborateur`,
`DirigeantPME`, `AdministrateurCabinet` sous `Utilisateur`).

C'est pourtant un des 4 rôles du projet, avec un shell frontend dédié
(`PlatformAdminShell`) et un module backend conséquent (`admin.py`, gestion
du corpus fiscal + supervision cross-tenant des organisations).

**Correction** :
- Cas d'utilisation : ajouter l'acteur « Administrateur Plateforme » avec
  un 8ᵉ bloc (ou l'ajouter au bloc 7 « Administration ») couvrant : valider/
  rejeter des articles du corpus, déclencher le pipeline d'extraction,
  superviser les organisations et utilisateurs de la plateforme.
- Diagramme de classes : ajouter `AdminPlateforme` comme 4ᵉ sous-classe de
  `Utilisateur` (héritage, comme les 3 autres).

### 6. La gestion des invitations n'apparaît dans aucun diagramme

Aucune entité `Invitation` dans le MCD/MLD/UML Classes, aucun cas
d'utilisation « Inviter un collaborateur ». C'est pourtant une
fonctionnalité réelle et substantielle (`backend/app/routes_invitations.py`,
~340 lignes) : un `admin_cabinet` invite un `collaborateur` ou un
`dirigeant_pme` par lien à jeton (pas d'email automatique à ce stade,
assumé), avec assignation optionnelle à un ou plusieurs dossiers.

**Correction** :
- MCD/MLD : ajouter l'entité `INVITATION` (attributs clés : `token`,
  `statut` (en_attente/acceptee/revoquee), `role` proposé, `dossier_id`
  optionnel, `expires_at`), reliée à `ORGANISATION` (`emet`) et
  optionnellement à `DOSSIER`.
- Cas d'utilisation : ajouter « Inviter un collaborateur / dirigeant » sous
  l'acteur Administrateur Cabinet (bloc 7 « Administration »).

### 7. `PIECE_COMPTABLE` modélise un état cible, pas l'implémentation actuelle

MCD/MLD/UML Classes montrent `PIECE_COMPTABLE` avec `montant`,
`statut_reconciliation` et une méthode `reconcilier()`, comme si chaque
pièce comptable était stockée individuellement avec un statut de
rapprochement propre.

L'implémentation actuelle est différente et volontairement plus simple à ce
stade : une **snapshot JSON unique par dossier** (`donnees_json`),
réévaluée à chaque nouvelle synchronisation Odoo/import, pas un modèle
relationnel détaillant chaque pièce. C'est documenté comme une limitation
assumée, reportée à une phase ultérieure (réconciliation pièce-à-pièce).

**Correction** : deux options, à choisir selon ce que le rapport doit
montrer :
- **Option A (recommandée pour rester honnête sur l'état actuel)** :
  garder ce diagramme comme modèle **cible / à venir**, et l'indiquer
  explicitement dans le rapport ("modèle cible, l'implémentation actuelle
  utilise un instantané JSON unique — voir Chapitre III") plutôt que de le
  présenter comme déjà réalisé.
- **Option B** : ajouter un second schéma (ou une note sur celui-ci)
  reflétant l'état actuel : `PIECE_COMPTABLE` avec `source`
  (odoo/csv/ocr), `type_piece`, `donnees_json`, sans `statut_reconciliation`
  individuel.

### 8. `ACCES` sans l'attribut `niveau_droit`

MCD et MLD modélisent `ACCES` comme une pure jonction (juste les deux clés
étrangères). Le champ réel le plus important de cette table,
`niveau_droit` (lecture / écriture / admin), qui permet à un cabinet de
restreindre l'accès de ses collaborateurs dossier par dossier, n'apparaît
nulle part.

**Correction** : ajouter `niveau_droit (enum: lecture | ecriture | admin)`
comme attribut de l'entité/association `ACCES` (ou de la relation
`ACCEDE`/`ACCÈS` selon le fichier).

### 9. `ALERTE_RISQUE` : deux mécanismes centraux du projet absents

MCD/MLD/UML Classes modélisent `ALERTE_RISQUE` avec `categorie`,
`montant_exposition`, `priorite`, `statut_traitement`. Deux éléments
manquent, qui sont pourtant des règles d'architecture explicitement
documentées et défendables à l'oral :
- **`cle_metier`** : identité stable de l'alerte (`"{pièce}|{article
  normalisé}"`), qui permet de retrouver la même alerte à travers
  plusieurs audits successifs.
- **`actif` (booléen)** : les alertes ne sont **jamais supprimées** — une
  anomalie disparue passe `actif=False` au lieu d'un `DELETE`, pour ne pas
  perdre une décision humaine déjà prise dessus (statut, correction
  validée).

**Correction** : ajouter ces deux attributs à `ALERTE_RISQUE` dans MCD, MLD
et UML Classes — c'est un point que le jury est susceptible de creuser
("comment gérez-vous la persistance d'une alerte d'un audit à l'autre ?"),
autant que le diagramme y réponde directement.

---

## 🟡 Priorité 3 — Nuances de terminologie / à vérifier (moins urgent)

### 10. `ORGANISATION.raisonSociale` et `DOSSIER.raisonSociale` inversés

Dans les 3 diagrammes, `ORGANISATION` porte l'attribut `raison_sociale`,
alors que dans le schéma réel c'est `Organisation.nom` (le nom du cabinet)
et **`Dossier.raison_sociale`** (le nom de la PME cliente) qui portent
cette information respectivement. Le champ semble avoir migré d'entité
sans que le diagramme soit mis à jour.

**Correction** : renommer `ORGANISATION.raison_sociale` → `nom` ; ajouter
`raison_sociale` à `DOSSIER` (déjà présent nulle part dans les 3
diagrammes, alors que c'est le champ qui identifie la PME cliente).

### 11. `plan_abonnement` sur `ORGANISATION` — fonctionnalité non implémentée

Aucune notion de plan d'abonnement/facturation n'existe dans le schéma réel
(`models.py`). Si cette idée reste dans le rapport, la présenter clairement
comme une **perspective d'évolution**, pas comme un champ déjà implémenté.

### 12. `DOSSIER.ice` et `DOSSIER.forme_juridique` — à vérifier

Ces deux champs n'apparaissent pas dans `backend/app/models.py::Dossier`
tel que lu (champs réels : `raison_sociale`, `secteur_activite`,
`regime_is`, `regime_tva`, `exercice_cloture_mois`). L'ICE apparaît dans le
projet côté **tiers/partenaire Odoo** (`partner.vat`, utilisé par l'audit),
pas comme un champ stocké sur `Dossier` lui-même. À vérifier avant de
garder ces deux champs : soit ils correspondent à une évolution du schéma
non encore vue dans cette revue, soit ils sont à retirer ou à déplacer.

### 13. `UTILISATEUR.actif` absent

Champ réel important (désactivation réversible d'un compte par un admin,
sans suppression), absent des 3 diagrammes. À ajouter à côté de `role`.

### 14. `REPONSE_ASSISTANT.modele_llm` et `score_confiance` — à vérifier

Le projet ne calcule pas de score de confiance continu : chaque analyse
retourne un statut discret (`anomalie` / `conforme` / `contexte_insuffisant`)
et une sévérité (`rouge`/`orange`/`vert`), pas un score numérique de
confiance. Si `score_confiance` ne correspond à aucun champ réellement
persisté, le retirer ou le requalifier clairement comme perspective
d'évolution plutôt que fonctionnalité existante.

### 15. `CONNEXION_COMPTABLE` : connecteur Sage à qualifier

Le cas d'utilisation « Se connecter à Odoo / Sage » et l'énumération
`typeConnecteur: enum (Sage, Odoo, Manuel, OCR)` présentent Sage comme un
connecteur équivalent à Odoo. Réel : le connecteur Sage est un **stub non
implémenté** (assumé et documenté ainsi — pas d'instance disponible pour
valider le mapping ODBC). Recommandé : garder Sage dans le diagramme
(cohérent avec le cahier des charges qui le cite comme cible), mais
ajouter une note ou un style visuel distinct signalant "non implémenté" —
pour ne pas laisser croire à une fonctionnalité équivalente à Odoo en
soutenance.

### 16. « Recevoir des rappels » (bloc 5, cas d'utilisation) — mécanisme à vérifier

Ce cas d'utilisation suppose un mécanisme de notification proactive
(push/email) des échéances. Le code exploré (`tax_calendar.py`) répond à la
demande (consultation) mais aucun mécanisme d'envoi proactif de rappel
(email, notification push) n'a été confirmé dans cette revue. À vérifier :
si ce mécanisme n'existe pas encore, le requalifier comme perspective
d'évolution plutôt que fonctionnalité livrée.

---

## Récapitulatif par fichier

| Fichier | Corrections prioritaires |
|---|---|
| `Nisab_UML_Sequence_Assistant.drawio` | #1 (Groq, pas Anthropic), #4 (endpoint) |
| `Nisab_UML_Sequence_Controle.drawio` | #2 (pas de nouvelle recherche RAG) |
| `Nisab_UML_Sequence_Ingestion.drawio` | #4 (endpoint), à vérifier vs. logique de fusion (`_fusionner_donnees_comptables`) plutôt que remplacement pur |
| `Nisab_UML_UseCase.drawio` | #3 (OCR), #5 (admin_plateforme), #6 (invitations), #15 (Sage), #16 (rappels) |
| `Nisab_UML_Classes.drawio` | #5 (AdminPlateforme), #6 (Invitation), #7 (PieceComptable), #9 (AlerteRisque), #13 (actif) |
| `Nisab_MCD.drawio` | #6, #7, #8, #9, #10, #11, #12, #13 |
| `Nisab_MLD.drawio` | mêmes corrections que le MCD, répercutées sur les clés étrangères |
