# Nisab — Documentation projet (pour soutenance / rapport / PPT)

> Document vivant, construit au fur et à mesure qu'on couvre chaque flux du
> projet ensemble. Chaque section suit un plan fixe en 10 points : vue
> d'ensemble, localisation exacte dans le code, explication ligne par ligne,
> flux de données (schéma ASCII), lien avec le frontend (tableau), choix
> d'architecture (comparé aux alternatives écartées), lien avec le cahier des
> charges, résumé à noter, questions probables du jury, étapes de test dans
> l'interface.

## Sommaire

Ordre de présentation retenu (celui d'une démo réelle de l'appli, pas l'ordre
des fichiers du repo) :

1. [Architecture globale — multi-tenant, RLS, rôles](#1-architecture-globale--multi-tenant-rls-rôles) — ✅ fait
2. [Authentification & session](#2-authentification--session) — ✅ fait
3. Gestion des dossiers (`DossierContext`, `DossierSwitcher`, `CabinetOverviewPage`) — *à venir*
4. Intégration Odoo & ingestion comptable (`odoo_connector.py`, `OdooPage`) — *à venir*
5. Corpus fiscal & fondations RAG (CGI vs BO, `extract_corpus.py`, `vectorstore.py`) — *à venir*
6. [Pipeline d'audit IA — détection de risques RAG-only](#6-pipeline-daudit-ia--détection-de-risques-rag-only) — ✅ fait
7. Dashboard (agrégation résumé + findings) — *à venir*
8. Simulation de contrôle fiscal (`control_simulator.py`, `simulation_pdf.py`) — *à venir*
9. Calendrier fiscal (`tax_calendar.py`) — *à venir*
10. Chat copilot IA (`GlobalCopilot`, `ChatPage`) — *à venir*
11. Invitations & collaborateurs (`routes_invitations.py`) — *à venir*
12. Espace admin_plateforme (`admin.py`, `PlatformAdminShell`) — *à venir*
13. Espace dirigeant_pme (`DirigeantShell`) — *à venir*

Flux ajoutés lors de la seconde vague de développement (phases 5 à 7 du plan
d'implémentation + le workflow agentique) :

14. [Identité stable des alertes — clé métier et cycle de vie](#14-identité-stable-des-alertes--clé-métier-et-cycle-de-vie) — ✅ fait
15. [Ingestion élargie — connecteurs, import CSV, réconciliation](#15-ingestion-élargie--connecteurs-import-csv-réconciliation) — ✅ fait
16. [Workflow agentique de correction avec validation humaine](#16-workflow-agentique-de-correction-avec-validation-humaine) — ✅ fait
17. [Veille personnalisée par citations](#17-veille-personnalisée-par-citations) — ✅ fait
18. [Assistant bilingue français / arabe-darija](#18-assistant-bilingue-français--arabe-darija) — ✅ fait

> **Note de lecture.** Les flux 14 à 18 sont documentés par la personne qui les
> a écrits, immédiatement après les avoir testés. Chaque bug mentionné y a
> réellement été trouvé par un test, et les chiffres cités (13 %, 33 %, 53 %,
> 1 600 requêtes…) sont des mesures, pas des estimations. C'est ce qui rend ces
> sections utilisables telles quelles à l'oral : un jury qui demande « comment
> le savez-vous ? » a la réponse dans le texte.

---

## 1. Architecture globale — multi-tenant, RLS, rôles

### 1. Vue d'ensemble

Nisab est un produit **B2B2C** : les clients directs sont des **cabinets
comptables**, qui eux-mêmes gèrent des **PME clientes**. Chaque cabinet est
un tenant. Contrainte n°1, non négociable pour un produit qui manipule des
données comptables et fiscales : **un cabinet ne doit jamais, sous aucune
circonstance, pouvoir lire les données d'un autre cabinet.**

Ce flux existe pour répondre à une seule question, mais critique : *quand
une requête arrive sur le backend, qui a le droit de voir quoi ?* Il résout
ce problème en deux temps :

1. **Modéliser** la hiérarchie réelle du métier
   (`Organisation → Utilisateur / Dossier → Acces → données métier`), avec 4
   rôles qui reflètent 4 réalités métier différentes (cabinet, collaborateur,
   client final, équipe Nisab).
2. **Faire respecter** cette hiérarchie à **deux niveaux indépendants** :
   le JWT (qui porte l'identité) côté applicatif, et Row-Level Security
   (RLS) côté Postgres. Si l'un des deux a un bug, l'autre bloque quand même
   la fuite. C'est le seul flux du projet qui n'est pas une fonctionnalité
   visible, mais une garantie transversale que tous les autres flux
   utilisent silencieusement.

Sans ce flux, chaque route métier (audit, simulation, calendrier...) devrait
elle-même réimplémenter sa propre vérification d'appartenance — un oubli
dans une seule route suffirait à faire fuiter les données d'un cabinet vers
un autre.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Lignes | Rôle |
|---|---|---|---|
| `backend/app/models.py` | `enum TypeOrganisation` | 37-40 | Type de tenant : `cabinet`, `pme`, `interne` |
| `backend/app/models.py` | `enum RoleUtilisateur` | 43-47 | Les 4 rôles applicatifs |
| `backend/app/models.py` | `class Organisation` | 85-96 | Le tenant (cabinet ou PME) |
| `backend/app/models.py` | `class Utilisateur` | 99-116 | Compte, rattaché à une organisation, porte un rôle |
| `backend/app/models.py` | `class Dossier` | 119-132 | Une PME cliente gérée par un cabinet |
| `backend/app/models.py` | `class Acces` | 135-144 | Jonction utilisateur↔dossier avec niveau de droit |
| `backend/migrations/versions/834f91da7e7e_initial_schema_multitenant.py` | commentaire + policies RLS | 203-289 | Active RLS et définit les policies `tenant_isolation` |
| `backend/app/db_session.py` | `get_tenant_db`, `set_tenant_context`, `clear_tenant_context` | 23-65 | Pose le contexte tenant (`app.current_org_id`) sur la session Postgres |
| `backend/app/db.py` | `get_db`, `engine`, `SessionLocal` | 20-47 | Session SQLAlchemy brute, sans contexte RLS |
| `backend/app/auth.py` | `create_access_token` / `create_refresh_token` | 69-80 | Embarque `organisation_id` + `role` dans le JWT |
| `backend/app/auth.py` | `get_current_user` | 103-105 | Décode le JWT → objet `CurrentUser` utilisé partout |
| `backend/app/routes_dossiers.py` | routes utilisant `Depends(get_tenant_db)` | ex. 117, 140, 160, 183, 389, 409 | Chaque route tenant-scoped pose le contexte RLS avant de toucher la DB |
| `frontend/src/App.jsx` | sélection du shell par `user.role` | 359-371 | Le rôle pilote **l'affichage**, jamais les données |
| `frontend/src/config/api.js` | `dossierFetch` | 56-63 | N'envoie jamais `organisation_id`, seulement `dossier_id` dans l'URL |

---

### 3. Explication détaillée du code

#### a) Les rôles — `backend/app/models.py:43-47`

```python
class RoleUtilisateur(str, enum.Enum):
    collaborateur = "collaborateur"
    dirigeant_pme = "dirigeant_pme"
    admin_cabinet = "admin_cabinet"          # admin d'UN cabinet client (son organisation, ses dossiers)
    admin_plateforme = "admin_plateforme"    # équipe Nisab/IAAI : corpus fiscal, veille, supervision globale
```

- `class RoleUtilisateur(str, enum.Enum)` : hériter à la fois de `str` et de
  `enum.Enum` permet à SQLAlchemy/Pydantic de sérialiser directement la
  valeur (`"admin_cabinet"`) en JSON, sans passer par `.value` partout dans
  le code. Si on enlevait `str,` de l'héritage, chaque sérialisation JSON
  (réponse FastAPI, payload JWT) planterait ou renverrait
  `RoleUtilisateur.admin_cabinet` au lieu de la chaîne attendue.
- Chaque membre est une **chaîne littérale**, pas un entier auto-incrémenté :
  volontaire, pour que la valeur reste lisible en base et dans un JWT décodé
  à la main (debug), plutôt que d'avoir à retenir "le rôle 3 = quoi déjà ?".
- Les 4 valeurs sont exhaustives par construction : `RoleUtilisateur(role_str)`
  lève une `ValueError` si la chaîne ne correspond à aucun membre — donc un
  rôle invalide en base (faute de frappe, migration ratée) casse au chargement
  plutôt que de silencieusement passer un `if` mal écrit ailleurs dans le code.

#### b) Le type d'organisation — `backend/app/models.py:37-40`

```python
class TypeOrganisation(str, enum.Enum):
    cabinet = "cabinet"
    pme = "pme"
    interne = "interne"
```

- `interne` existe uniquement pour rattacher les comptes `admin_plateforme` à
  une organisation technique (contrainte du schéma : `Utilisateur.organisation_id`
  est `nullable=False`, donc même l'équipe Nisab a besoin d'une `Organisation`
  ligne en base). Si on la supprimait, on serait obligé de rattacher
  `admin_plateforme` à une fausse `Organisation` de type `cabinet`, ce qui
  fausserait tous les compteurs "nombre de cabinets clients" affichés côté
  `PlatformAdminShell`.

#### c) `Organisation` — `backend/app/models.py:85-96`

```python
class Organisation(Base):
    __tablename__ = "organisation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    type_organisation: Mapped[TypeOrganisation] = mapped_column(
        Enum(TypeOrganisation, name="type_organisation"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    utilisateurs: Mapped[list["Utilisateur"]] = relationship(back_populates="organisation")
    dossiers: Mapped[list["Dossier"]] = relationship(back_populates="organisation")
```

- `id: Mapped[uuid.UUID] = _uuid_pk()` : clé primaire UUID générée côté
  Python (`default=uuid.uuid4`, voir `_uuid_pk()` ligne 29-30), pas un
  entier auto-incrémenté Postgres. Nécessaire parce qu'un `organisation_id`
  séquentiel (1, 2, 3...) serait devinable — un attaquant pourrait énumérer
  les tenants existants (`/dossiers?org=4`). Un UUID rend cette énumération
  impraticable.
- `type_organisation` : colonne `Enum` Postgres native (pas juste une
  `String` avec une contrainte applicative) — Postgres refuse d'insérer une
  valeur hors énum au niveau du **type de colonne lui-même**, avant même
  qu'une policy RLS ou une validation Pydantic n'entre en jeu.
- `relationship(back_populates=...)` : ces deux lignes ne créent **aucune**
  colonne en base — c'est du sucre syntaxique SQLAlchemy pour naviguer
  `organisation.utilisateurs` ou `organisation.dossiers` en Python sans
  écrire de jointure à la main. Si on les supprimait, le code fonctionnerait
  toujours (les `ForeignKey` suffisent pour l'intégrité en base), mais on
  perdrait cette navigation objet pratique.

#### d) `Utilisateur` — `backend/app/models.py:99-116`

```python
class Utilisateur(Base):
    __tablename__ = "utilisateur"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisation.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nom_complet: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[RoleUtilisateur] = mapped_column(Enum(RoleUtilisateur, name="role_utilisateur"), nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

- `organisation_id ... nullable=False` : un utilisateur **doit** appartenir à
  une organisation dès sa création — il n'existe pas d'utilisateur "flottant"
  sans tenant. C'est ce qui rend possible tout le reste : sans cette colonne,
  RLS n'aurait rien à filtrer.
- `email ... unique=True, index=True` : `unique` est une contrainte
  d'intégrité (empêche deux comptes avec le même email, tous cabinets
  confondus — l'email est le point d'entrée du login, avant même de
  connaître le tenant). `index=True` accélère le `SELECT ... WHERE email = X`
  fait à chaque login (voir `routes_auth.py:110`). Sans l'index, ce lookup
  ferait un scan séquentiel de toute la table à chaque tentative de connexion.
- `password_hash` : jamais le mot de passe en clair — voir flow 2
  (Authentification) pour le détail du hachage bcrypt.
- `actif: ... default=True` : désactivation **réversible** (un admin peut
  couper l'accès d'un collaborateur sans supprimer son compte ni son
  historique). Le commentaire du code (lignes 108-111) précise que ce champ
  n'est vérifié qu'au login/refresh, pas à chaque requête — compromis
  volontaire pour rester cohérent avec le design **stateless** de
  `get_current_user` (voir flow 2) : vérifier `actif` à chaque requête
  demanderait une requête DB par appel API, alors que le JWT est justement
  fait pour éviter ça. Conséquence assumée : désactiver un compte met jusqu'à
  30 minutes (durée de vie de l'access token) à devenir effectif si
  l'utilisateur ne refait pas de refresh entre-temps.

#### e) `Dossier` — `backend/app/models.py:119-132`

```python
class Dossier(Base):
    __tablename__ = "dossier"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisation.id"), nullable=False, index=True)
```

- C'est **cette colonne précise** (`organisation_id` sur `dossier`) qui est
  la racine de toute la RLS du projet : toutes les autres tables métier
  (`piece_comptable`, `alerte_risque`, `simulation_controle`...) ne portent
  pas directement `organisation_id`, mais `dossier_id`, et remontent à
  `organisation_id` via une sous-requête sur `dossier` (voir section 3g).
  Si cette colonne était nullable ou absente, aucune policy RLS ne pourrait
  filtrer une seule ligne de la table `dossier` elle-même.
- `index=True` : chaque policy RLS fait `WHERE organisation_id = ...` sur
  cette table à chaque requête tenant-scoped (potentiellement plusieurs fois
  par requête HTTP, une fois par table dépendante) — sans index, ce filtre
  dégraderait linéairement avec le nombre total de dossiers, tous cabinets
  confondus.

#### f) `Acces` — `backend/app/models.py:135-144`

```python
class Acces(Base):
    __tablename__ = "acces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateur.id"), nullable=False)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), nullable=False)
    niveau_droit: Mapped[NiveauDroit] = mapped_column(Enum(NiveauDroit, name="niveau_droit"), default=NiveauDroit.lecture)
```

- Cette table de jonction est ce qui rend l'accès **granulaire par
  utilisateur**, pas seulement par organisation. Un `collaborateur` peut
  avoir un `Acces` sur 3 des 10 dossiers de son cabinet, chacun avec un
  `niveau_droit` différent (`lecture`/`ecriture`/`admin`). Sans cette table,
  la seule granularité possible serait "appartient à l'organisation" —
  n'importe quel collaborateur verrait tous les dossiers du cabinet, ce qui
  ne correspond pas à la réalité métier (un cabinet peut vouloir restreindre
  qui voit quel client, ex. confidentialité entre associés).
- **Mise à jour (bug trouvé et corrigé le 02/08/2026)** : cette remarque
  était initialement une réserve honnête ("modélisé mais pas vérifié si
  c'est appliqué") — en testant l'appli, on a confirmé que ce n'était
  **pas** un détail à creuser mais un vrai trou de sécurité : `Acces`
  était peuplée à l'acceptation d'une invitation
  ([`routes_invitations.py:180-187`](../backend/app/routes_invitations.py#L180-L187))
  mais **jamais consultée** pour filtrer quoi que ce soit. `list_dossiers`
  et toutes les routes dossier-scopées ne faisaient confiance qu'à la RLS
  (filtrage par organisation), donc un `collaborateur`/`dirigeant_pme`
  voyait TOUS les dossiers du cabinet, jamais seulement les siens.
  Corrigé en ajoutant une vérification `Acces` explicite dans
  `_get_dossier_or_404` ([`routes_dossiers.py:69-84`](../backend/app/routes_dossiers.py#L69-L84),
  répliquée dans [`routes_simulation.py`](../backend/app/routes_simulation.py))
  et dans `list_dossiers` ([`routes_dossiers.py:139-150`](../backend/app/routes_dossiers.py#L139-L150)) :
  pour tout rôle autre que `admin_cabinet`/`admin_plateforme`, il faut
  désormais une ligne `Acces` correspondante, sinon 404 — RLS reste la
  garantie d'isolation *entre cabinets*, `Acces` est la garantie
  d'isolation *à l'intérieur* d'un même cabinet, entre ses membres.
- **Leçon à retenir pour l'oral** : le schéma de données modélisait la
  bonne intention depuis le début, mais une colonne ou une table qui
  existe en base ne garantit rien tant qu'aucune route ne la lit — la
  garantie doit être appliquée au niveau requête, pas seulement au niveau
  schéma. C'est exactement le genre de nuance qu'un jury apprécie de
  t'entendre expliquer honnêtement plutôt que de prétendre que tout était
  parfait dès le départ.

#### g) Activation de RLS — migration `834f91da7e7e`, lignes 219-224

```python
op.execute("ALTER TABLE dossier ENABLE ROW LEVEL SECURITY")
op.execute("""
    CREATE POLICY tenant_isolation ON dossier
    USING (organisation_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (organisation_id = current_setting('app.current_org_id', true)::uuid)
""")
```

- `ALTER TABLE dossier ENABLE ROW LEVEL SECURITY` : sans cette ligne,
  **aucune** policy créée ensuite n'aurait d'effet — RLS est désactivée par
  défaut sur toute table Postgres, même si des policies existent. C'est
  l'interrupteur maître.
- `CREATE POLICY tenant_isolation ON dossier` : crée une règle nommée
  `tenant_isolation`, appliquée à **toute** requête sur `dossier` (sauf pour
  le rôle Postgres `superuser`/`BYPASSRLS`, qu'on n'utilise pas ici).
- `USING (...)` : la clause qui filtre les lignes **lues** (`SELECT`,
  `UPDATE`, `DELETE`) — une ligne n'est visible que si son
  `organisation_id` correspond au tenant courant.
- `WITH CHECK (...)` : la clause qui valide les lignes **écrites**
  (`INSERT`, `UPDATE`). Sans elle, un utilisateur pourrait lire uniquement
  ses propres dossiers (grâce à `USING`) mais **insérer** une ligne avec
  l'`organisation_id` d'un autre cabinet — `WITH CHECK` ferme ce trou.
- `current_setting('app.current_org_id', true)` : lit une variable de
  session Postgres. Le 2e argument `true` (`missing_ok`) fait que si la
  variable n'a jamais été positionnée, la fonction renvoie `NULL` au lieu de
  lever une erreur — donc `organisation_id = NULL` → aucune ligne ne
  matche (comparaison NULL toujours fausse en SQL). Résultat : une session
  qui n'a jamais posé son contexte tenant voit une table **vide**, jamais
  une erreur ni (pire) toutes les lignes.
- `::uuid` : cast explicite, parce que `current_setting` renvoie toujours du
  texte, alors que `organisation_id` est typé `uuid` en base.

#### h) Policies sur les tables dépendantes — migration, lignes 226-252

```python
via_dossier_tables = [
    "connexion_comptable", "piece_comptable", "declaration",
    "alerte_risque", "simulation_controle", "echeance",
    "notification_veille", "citation",
]
for table in via_dossier_tables:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (
            dossier_id IN (
                SELECT id FROM dossier
                WHERE organisation_id = current_setting('app.current_org_id', true)::uuid
            )
        )
        ...
    """)
```

- Ces 8 tables ne portent pas `organisation_id` directement — seulement
  `dossier_id`. La policy remonte donc via une sous-requête : "quels
  `dossier.id` appartiennent à mon organisation ?", puis filtre la table sur
  `dossier_id IN (...)`. Deux niveaux de tables (`citation_risque`,
  `citation_simulation`, lignes 254-278) remontent même sur **deux** sauts
  (`alerte_id → alerte_risque.dossier_id → dossier.organisation_id`).
- La boucle Python (`for table in via_dossier_tables`) est une simple
  factorisation de migration — le SQL généré est identique à 8 policies
  écrites à la main. Aucun impact runtime, seulement moins de duplication
  dans le fichier de migration.
- Si une nouvelle table métier oublie d'être ajoutée à cette liste (ou
  d'avoir sa propre policy), elle reste **sans RLS** — visible par n'importe
  quelle session, tous tenants confondus. C'est le risque principal de ce
  design : la RLS est solide table par table, mais rien ne force
  automatiquement une nouvelle table à en hériter. Une nouvelle table métier
  doit explicitement recevoir sa policy dans une nouvelle migration.

#### i) `db_session.py` — le pont entre JWT et RLS

```python
def get_tenant_db(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Session:
    set_tenant_context(db, user.organisation_id)
    return db


def set_tenant_context(db: Session, organisation_id: str) -> None:
    db.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(organisation_id)},
    )
```

- `get_tenant_db` est une **dependency FastAPI composée** : elle dépend
  elle-même de `get_db` (ouvre une session) et de `get_current_user`
  (décode le JWT). FastAPI résout cette chaîne automatiquement. Objet
  retourné : la même `Session` SQLAlchemy que `get_db`, mais avec le
  contexte tenant déjà posé dessus — une route qui déclare
  `db: Session = Depends(get_tenant_db)` n'a rien d'autre à faire, chaque
  requête faite avec `db` sera automatiquement filtrée par RLS.
- `set_tenant_context` exécute `SELECT set_config(...)`, pas
  `SET LOCAL app.current_org_id = ...`. Raison donnée dans le commentaire du
  code : Postgres interdit les **bind parameters** après `SET`/`SET LOCAL`
  (erreur `syntax error at or near "$1"`) — on serait obligé de faire de
  l'interpolation de chaîne (`f"SET LOCAL app.current_org_id = '{org_id}'"`),
  ce qui est une porte ouverte à l'injection SQL si jamais `org_id` n'était
  pas garanti être un UUID interne. `set_config()` est une **fonction SQL
  normale**, donc paramétrable comme n'importe quel `SELECT`.
- Le 3e argument `true` de `set_config` reproduit le comportement `LOCAL` :
  le paramètre ne vit que pour la transaction en cours, pas pour toute la
  session/connexion. Important avec un pool de connexions (voir point
  suivant) : sans ce `true`, le paramètre resterait posé sur la connexion
  physique bien après la fin de la requête HTTP.
- Paramètre `organisation_id: str` : notez le typage — mais `user.organisation_id`
  (objet `CurrentUser`) est en réalité une chaîne décodée du JWT, pas un
  `uuid.UUID` Python. `str(organisation_id)` est donc redondant mais
  défensif si jamais un appelant passait un `uuid.UUID`.
- Exception : `db.execute` peut lever une exception SQLAlchemy si la
  connexion est fermée/invalide, mais aucune gestion d'erreur spécifique
  n'est faite ici — elle remonte telle quelle et FastAPI la transforme en
  500. Volontaire : une erreur DB à cette étape doit casser la requête, pas
  être avalée silencieusement (ce qui laisserait passer une requête sans
  contexte tenant posé).

```python
def clear_tenant_context(db: Session) -> None:
    db.execute(text("SELECT set_config('app.current_org_id', '', true)"))
```

- Utilisé pour les routes admin globales (`admin_plateforme`, qui doit voir
  **tous** les tenants). Le commentaire du code explique pourquoi
  `set_config('', true)` plutôt que `RESET app.current_org_id` : `RESET` est
  scope **session**, alors qu'avec le pooler Supabase en mode transaction
  (PgBouncer), une connexion physique est partagée entre plusieurs requêtes
  HTTP différentes dans le temps. Un `RESET` laisserait la connexion dans un
  état "sans contexte" qui pourrait fuiter vers la **prochaine** requête
  utilisant cette même connexion physique — potentiellement une requête
  d'un tenant qui, elle, aurait dû avoir son contexte posé. `set_config(...,
  true)` reste scope transaction, donc chaque nouvelle transaction (chaque
  requête, avec ce pooler) repart de zéro, jamais d'un état laissé par la
  requête précédente.

#### j) `get_db` — la session "nue", sans RLS — `backend/app/db.py:41-47`

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- `yield db` (et non `return db`) : c'est ce qui permet à FastAPI de garder
  le `finally` en attente jusqu'à la fin du traitement de la requête — la
  session reste ouverte pendant tout le handler, puis se ferme
  automatiquement, même si le handler lève une exception. Si on utilisait
  `return`, la session serait fermée immédiatement, avant même que la route
  ait pu l'utiliser.
- Point archi crucial à retenir : `get_db` seul **ne pose aucun contexte
  RLS**. Une route qui utiliserait `Depends(get_db)` au lieu de
  `Depends(get_tenant_db)` sur une table protégée par RLS verrait
  simplement... rien (table vide, cf. section 3g sur `current_setting`
  avec `missing_ok=true`) — pas une erreur explicite, ce qui rend ce bug
  particulièrement traître à débugger si on ne connaît pas cette règle.
  `get_db` reste légitime pour les routes d'auth (`routes_auth.py`), qui
  touchent `utilisateur`/`organisation`, volontairement hors RLS.

#### k) Le JWT comme porteur du tenant — `backend/app/auth.py:69-73`

```python
def create_access_token(utilisateur_id: str, organisation_id: str, role: str) -> str:
    return _create_token(
        {"sub": utilisateur_id, "organisation_id": organisation_id, "role": role, "type": "access"},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
```

- Le token signé embarque directement `organisation_id` et `role` — le
  serveur n'a **pas besoin de retourner en base** pour connaître le tenant
  de l'appelant à chaque requête, il lui suffit de décoder et vérifier la
  signature (HS256, secret serveur). C'est ce qui rend `get_current_user`
  (flow 2) rapide et stateless.
- Conséquence directe pour ce flow : `get_tenant_db` (section 3i) peut lire
  `user.organisation_id` sans jamais faire de `SELECT` sur `utilisateur` —
  c'est le JWT, pas la base, qui fait autorité sur "qui appartient à quel
  tenant" à chaque requête. Le détail du hachage de mot de passe et de la
  durée de vie des tokens est couvert au flow 2 (Authentification).

#### l) Le rôle pilote l'affichage, jamais les données — `frontend/src/App.jsx:359-371`

```jsx
if (status === 'anonymous') {
  return <LoginPage />
}

if (user?.role === 'admin_plateforme') {
  return <PlatformAdminShell />
}

if (user?.role === 'dirigeant_pme') {
  return <DirigeantShell />
}

return <AppShell />
```

- Ce `if/else` en cascade est **la seule** logique de routing de tout le
  frontend (pas de `react-router`) — voir flow "routing manuel" prévu plus
  loin. Ici, il ne sert qu'à choisir quel arbre de composants monter selon
  le rôle lu dans `user` (renvoyé par `/auth/me`).
- Le point à défendre : ce `role` vient du state React, lui-même rempli par
  un appel API — un utilisateur malveillant pourrait théoriquement modifier
  ce state en mémoire via les devtools et se faire passer pour un
  `admin_plateforme` **côté affichage**. Ça ne lui donnerait accès à
  **aucune donnée** qu'il n'a pas déjà : chaque appel vers le backend est
  revalidé par `get_current_user`/RLS avec le rôle réel encodé dans le JWT
  signé, que le frontend ne peut pas falsifier. Le pire qu'il obtiendrait :
  voir des boutons d'une interface qui, une fois cliqués, se feraient
  rejeter en 401/403 par le backend.

---

### 4. Flux complet des données

```
Utilisateur (navigateur)
     │  saisit email/password (LoginPage)
     ▼
AuthContext.login()  ──fetch──►  POST /auth/login (FastAPI)
     │                                │
     │                                ▼
     │                     vérifie email+password (table utilisateur, hors RLS)
     │                     émet un JWT {sub, organisation_id, role}
     ▼                                │
applyTokens() (App.jsx/api.js) ◄──────┘
     │  access_token en variable JS module
     │  refresh_token en localStorage
     ▼
fetchMe() ──fetch──► GET /auth/me (Authorization: Bearer <JWT>)
     │                    │
     │                    ▼
     │         get_current_user décode le JWT → CurrentUser(id, organisation_id, role)
     ▼                    │
user (state React) ◄──────┘
     │
     ▼
App.jsx : if (user.role === ...) → choix du shell (AppShell / DirigeantShell / PlatformAdminShell)
     │
     ▼
Utilisateur clique sur un dossier ──► dossierFetch('/audit/run') ──►
     GET/POST /dossiers/{dossier_id}/... (Authorization: Bearer <JWT>, PAS d'organisation_id)
                    │
                    ▼
     get_tenant_db = get_db() + get_current_user() + set_tenant_context(db, user.organisation_id)
                    │
                    ▼
     SELECT set_config('app.current_org_id', '<org_id du JWT>', true)
                    │
                    ▼
     requête SQLAlchemy normale (ex. SELECT * FROM dossier WHERE id = :dossier_id)
                    │
                    ▼
     Postgres applique la policy RLS tenant_isolation AVANT de renvoyer les lignes
     (dossier.organisation_id = current_setting('app.current_org_id'))
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  dossier_id appartient      dossier_id appartient à
  au bon tenant               un AUTRE tenant
        │                       │
        ▼                       ▼
  lignes renvoyées          aucune ligne renvoyée
  normalement                (pas d'erreur, résultat vide)
        │                       │
        └───────────┬───────────┘
                     ▼
              Réponse JSON → Frontend → affichage
```

---

### 5. Lien avec le frontend

| Étape | Composant / Page | Hook | Appel | Endpoint FastAPI | JSON envoyé | JSON reçu | Impact UI |
|---|---|---|---|---|---|---|---|
| Connexion | `LoginPage.jsx` | `useAuth()` → `login()` | `fetch` direct (pas `apiFetch`, pas encore de token) | `POST /auth/login` | `{email, password}` | `{access_token, refresh_token, token_type}` | Passe `status` à `authenticated`, déclenche le choix du shell |
| Récupération du profil | `AuthContext.jsx` (interne) | `fetchMe()` | `apiFetch('/auth/me')` | `GET /auth/me` | *(rien, juste le JWT en header)* | `{id, email, nom_complet, role, organisation_id, organisation_nom}` | Remplit `user` → déclenche `App.jsx` à choisir le shell |
| Choix du shell | `App.jsx` | `useAuth()` | *(pas de fetch, lecture du state `user`)* | — | — | — | Monte `AppShell`, `DirigeantShell` ou `PlatformAdminShell` |
| Requête tenant-scoped | ex. `DashboardPage.jsx` (via `AppShell`) | — | `dossierFetch('/dashboard/summary')` | `GET /dossiers/{dossier_id}/dashboard/summary` | — (JWT en header, `dossier_id` dans l'URL) | données filtrées par RLS pour ce dossier | Affiche uniquement les données du dossier actif, jamais celles d'un autre cabinet même en cas d'URL trafiquée |

---

### 6. Pourquoi cette architecture ?

**RLS plutôt que filtrage applicatif seul (`WHERE organisation_id = X` dans
chaque route).**
Alternative écartée : faire confiance à un filtre écrit à la main dans
chaque endpoint. Rejetée parce qu'un seul oubli — sous pression, en fin de
sprint, dans une des dizaines de routes du projet — devient une fuite de
données entre cabinets clients, silencieuse, potentiellement découverte des
mois après en production. Avec RLS, c'est **Postgres lui-même** qui refuse
de renvoyer les lignes hors tenant, même si la requête SQLAlchemy générée
par une route buguée oublie le filtre. C'est de la défense en profondeur :
deux mécanismes indépendants (JWT + RLS) doivent être compromis
**simultanément** pour qu'une fuite se produise.

**JWT signé plutôt qu'un `organisation_id` envoyé par le client**
(query param, header custom, payload). Rejetée : vecteur direct d'IDOR —
n'importe quel utilisateur authentifié pourrait changer cette valeur dans
sa requête et lire les données d'un autre cabinet. En dérivant
`organisation_id` uniquement du JWT signé (jamais d'un paramètre fourni par
le navigateur) et en le faisant réappliquer une seconde fois par RLS côté
DB, l'isolation ne dépend d'aucune donnée que le client contrôle.

**4 rôles précisément ceux-là, pas un système de permissions plus fin
(RBAC générique avec permissions à la carte) :**

| Rôle | Portée | Pourquoi ce découpage |
|---|---|---|
| `admin_plateforme` | Global (équipe Nisab/IAAI) | PAS un tenant client — rattaché à une `Organisation` de type `interne` pour ne pas polluer les compteurs "nombre de cabinets" du dashboard plateforme. |
| `admin_cabinet` | Son organisation entière | Gère dossiers + collaborateurs de SON cabinet, isolé des autres par RLS. |
| `collaborateur` | Dossier par dossier | Accès via `Acces.niveau_droit`, pas organisation-wide — un cabinet peut restreindre qui voit quel client. |
| `dirigeant_pme` | Son dossier, lecture seule | Le client final (patron de la PME), pas un power user — consulte ce que le cabinet a produit. |

Un RBAC plus générique (permissions granulaires configurables) aurait été
sur-ingénieré pour un MVP à 2 mois : les 4 rôles couvrent exactement les 4
réalités métier identifiées dans le cahier des charges, sans complexité de
configuration supplémentaire à développer ni à expliquer à un utilisateur
non technique (dirigeant de PME).

**`dirigeant_pme` a un shell frontend séparé (`DirigeantShell.jsx`) plutôt
que des boutons masqués conditionnellement dans la même UI que le cabinet.**
Alternative écartée : un seul `AppShell` avec des `if (role === ...)` pour
cacher certains boutons. Rejetée parce qu'un `if` oublié ou une règle CSS
mal appliquée laisserait une fonctionnalité réservée au cabinet
partiellement visible/cliquable pour un dirigeant. Séparer les shells rend
l'omission **structurellement impossible** (le composant n'existe même pas
dans l'arbre monté) plutôt que de compter sur la discipline du code à
chaque nouvel ajout de fonctionnalité.

**`utilisateur`/`organisation` volontairement hors RLS.**
Point que le jury va probablement creuser : au moment du login, le serveur
n'a qu'un email — le tenant (`organisation_id`) n'est **pas encore connu**,
c'est justement ce que le login détermine. Une RLS filtrée par
`app.current_org_id` bloquerait cette recherche puisque le contexte tenant
n'existe pas encore à ce stade (problème de la poule et de l'œuf). Ces deux
tables restent protégées uniquement au niveau **applicatif** :
`routes_auth.py` ne retourne jamais que la ligne de l'utilisateur
authentifié, et aucune route métier ne les expose en liste brute. **C'est
documenté et voulu** (commentaire explicite dans la migration, lignes
206-217), pas un oubli.

**`set_config` plutôt que `SET LOCAL` / `RESET`** : détaillé en section 3i —
en résumé, `set_config` est paramétrable (évite l'injection SQL par
interpolation de chaîne) et reste scope-transaction de façon fiable même
avec un pooler de connexions partagées (Supabase/PgBouncer en mode
transaction), contrairement à `RESET` qui est scope-session et pourrait
fuiter un contexte tenant vers la prochaine requête sur la même connexion
physique.

---

### 7. Lien avec le cahier des charges

Ce flux répond directement au **module fonctionnel 7 — "Espaces &
multi-tenant"** : *"vue cabinet multi-dossiers + vue dirigeant simplifiée
(feux tricolores), comptes, rôles, isolation des données"* —
[`cahier-des-charges.md:46-47`](../cahier-des-charges.md#L46-L47). La
séparation `AppShell` / `DirigeantShell` / `PlatformAdminShell` est la
traduction directe de "vue cabinet" vs "vue dirigeant simplifiée".

Il répond aussi à la **contrainte technique imposée** : *"Multi-tenant,
isolation stricte des données ; confidentialité et hébergement conformes
(loi 09-08, CNDP)"* —
[`cahier-des-charges.md:55-56`](../cahier-des-charges.md#L55-L56). Le choix
RLS (plutôt que filtrage applicatif seul) est directement ce qui permet de
défendre le mot **"stricte"** de cette exigence à l'oral : l'isolation est
garantie par la base de données elle-même, indépendamment de la discipline
du code applicatif.

---

### 8. Ce que je dois retenir pour la soutenance

- Cabinet = `Organisation`, PME cliente = `Dossier` — isolation stricte exigée par le module 7 + la contrainte technique du cahier des charges.
- 4 rôles, chacun correspondant à une réalité métier distincte, pas à un RBAC générique : `admin_plateforme` (équipe Nisab, org `interne`), `admin_cabinet` (son cabinet entier), `collaborateur` (accès dossier par dossier via `Acces`), `dirigeant_pme` (lecture seule, son dossier).
- Isolation à 2 niveaux indépendants = défense en profondeur : le JWT porte `organisation_id`+`role` (jamais fourni par le client), ET les policies RLS Postgres refiltrent en base indépendamment du code applicatif.
- `utilisateur`/`organisation` sont volontairement hors RLS (problème poule/œuf au login) — protégées seulement au niveau applicatif. Documenté dans la migration, pas un oubli.
- `set_config(..., true)` plutôt que `SET LOCAL`/`RESET` : paramétrable (pas d'injection SQL) et fiable avec un pooler de connexions partagées.
- Une table métier oubliée dans la liste des policies RLS reste sans protection — la RLS ne s'hérite pas automatiquement, c'est le vrai point de vigilance de ce design.
- Côté frontend, le rôle (`/auth/me`) pilote uniquement **quel shell afficher**, jamais quelles données arrivent — ça reste la responsabilité du backend/RLS, même si le state React était falsifié côté client.

---

### 9. Questions probables du jury

**Pourquoi RLS et pas simplement un `WHERE organisation_id = X` dans chaque route ?**
Parce qu'un filtre applicatif dépend de la discipline du développeur à
chaque route, à chaque endpoint futur. Un seul oubli = fuite de données
entre cabinets. RLS déplace cette garantie dans la base elle-même : même
une requête buguée ne peut pas contourner la policy.

**Les tables `utilisateur` et `organisation` ne sont pas protégées par
RLS — n'est-ce pas une faille ?**
Non, c'est documenté et intentionnel : au moment du login, le tenant n'est
pas encore connu (c'est ce que le login détermine), donc une RLS basée sur
`app.current_org_id` bloquerait la recherche par email elle-même. La
protection est déplacée au niveau applicatif : ces routes ne retournent
jamais que la ligne de l'utilisateur authentifié.

**Que se passe-t-il si un utilisateur modifie le `dossier_id` dans l'URL
pour viser un dossier d'un autre cabinet ?**
Le contexte RLS (`app.current_org_id`) reste celui de son propre JWT — la
policy sur `dossier` compare `organisation_id` réel du dossier ciblé à ce
contexte. Résultat : liste vide ou 404, jamais les données de l'autre
client, quelle que soit la valeur trafiquée dans l'URL.

**Et si c'est un dossier du MÊME cabinet, mais qui n'est pas assigné à cet
utilisateur (ex. un `dirigeant_pme` visant le dossier d'un autre client du
même cabinet) ?**
Ici RLS seule ne suffit pas — les deux dossiers appartiennent à la même
organisation, donc la policy `tenant_isolation` laisse passer. C'est
exactement le bug identifié et corrigé le 02/08/2026 (voir point f)
ci-dessus) : il fallait une vérification supplémentaire sur la table
`Acces`, ajoutée dans `_get_dossier_or_404`. Avant le fix, ce scénario
précis fuitait réellement des données entre clients d'un même cabinet.

**Pourquoi 4 rôles précisément, et pas un système de permissions plus
fin/configurable ?**
Parce que les 4 rôles couvrent exactement les 4 réalités métier du cahier
des charges (équipe plateforme, cabinet, collaborateur, client final). Un
RBAC configurable aurait ajouté de la complexité de configuration sans
bénéfice pour un MVP à 2 mois, ni pour un dirigeant de PME non technique.

**Pourquoi un shell frontend séparé pour `dirigeant_pme` plutôt qu'un
simple `if` pour masquer des boutons ?**
Parce qu'un `if` mal placé ou une règle CSS oubliée laisserait une
fonctionnalité cabinet partiellement accessible. Séparer les shells rend
l'erreur structurellement impossible plutôt que de compter sur la
vigilance à chaque nouvel ajout.

**`admin_plateforme` peut-il accéder aux données d'un cabinet client ?**
Les routes admin globales utilisent `clear_tenant_context` (pas
`get_tenant_db`) pour voir tous les tenants dans un but de supervision
(corpus, veille, statistiques globales) — mais ce flow ne détaille pas
lui-même les vérifications faites route par route côté `admin.py` pour
s'assurer que cet accès reste limité aux données de supervision et
n'expose pas les données comptables/fiscales détaillées d'un dossier
client ; ce point relève du flow "Espace admin_plateforme" à venir.

**Que se passerait-il avec le pooler Supabase (PgBouncer) si vous
utilisiez `RESET` plutôt que `set_config` pour effacer le contexte ?**
`RESET` est scope-session. Avec un pooler en mode transaction, une
connexion physique est réutilisée par des requêtes HTTP différentes dans le
temps — un `RESET` laisserait la connexion dans un état qui pourrait
fuiter vers la requête suivante sur cette même connexion. `set_config(...,
true)` reste scope-transaction, donc chaque nouvelle transaction repart
d'un état neutre, indépendamment de l'historique de la connexion physique.

**Quel est le principal point faible de ce design RLS ?**
La RLS ne s'hérite pas automatiquement : une nouvelle table métier doit
explicitement recevoir sa policy dans une migration dédiée. Si un
développeur ajoute une table et oublie cette étape, elle reste accessible
sans isolation tenant — c'est un oubli possible, contrairement à un ORM qui
imposerait le filtre par construction.

---

### 10. Étapes de test dans l'application

1. **Vérifier le bon shell par rôle** :
   ```
   @browser va sur localhost:5173, connecte-toi avec un compte admin_cabinet,
   et vérifie que la sidebar affiche les vues cabinet (dashboard, audit,
   simulation, calendar, chat, odoo, invitations)
   ```
2. **Vérifier le shell dirigeant** :
   ```
   @browser déconnecte-toi puis connecte-toi avec un compte dirigeant_pme,
   et vérifie que l'interface est différente : pas de sidebar cabinet,
   vue lecture seule
   ```
3. **Vérifier le shell plateforme** :
   ```
   @browser connecte-toi avec un compte admin_plateforme et vérifie que
   tu arrives sur PlatformAdminShell (vues overview/organisations/users/corpus)
   ```
4. **Vérifier qu'aucun `organisation_id` n'est envoyé par le client** :
   ```
   @browser ouvre les DevTools > onglet réseau, va sur le dashboard, clique
   sur une requête vers /dossiers/..., et montre-moi les headers et l'URL —
   confirme qu'il n'y a que le JWT en Authorization et un dossier_id dans
   le chemin, jamais d'organisation_id
   ```
5. **Preuve applicative de l'isolation RLS** (nécessite 2 comptes de test
   dans 2 organisations différentes) :
   modifie manuellement le `dossier_id` dans l'URL du dashboard pour viser
   un dossier appartenant à l'AUTRE organisation, en étant connecté sur le
   premier compte → attendu : erreur/liste vide, jamais les données de
   l'autre client. (Nécessite d'avoir seedé 2 orgs de test au préalable —
   voir `backend/scripts/`.)
6. **Preuve SQL directe de la RLS (niveau base, sans passer par l'API)** :
   ```sql
   -- Dans psql, connecté avec un rôle NON superuser/BYPASSRLS :
   SELECT * FROM dossier;
   -- attendu : 0 ligne, car app.current_org_id n'est pas positionné

   SELECT set_config('app.current_org_id', '<uuid-org-1>', true);
   SELECT * FROM dossier;
   -- attendu : uniquement les dossiers de l'org 1

   SELECT set_config('app.current_org_id', '<uuid-org-2>', true);
   SELECT * FROM dossier;
   -- attendu : uniquement les dossiers de l'org 2, pas ceux de l'org 1
   ```
   Ce test isole la garantie RLS de tout le code applicatif — il prouve que
   la protection tient même si on contourne complètement FastAPI.
7. **Isolation par dossier à l'intérieur d'un même cabinet** (corrigé le
   02/08/2026 — nécessite un `dirigeant_pme` assigné à un seul dossier via
   une invitation avec `dossier_id`) :
   ```
   @browser connecte-toi en dirigeant_pme (assigné à un seul dossier),
   vérifie que le sélecteur de dossier n'affiche QUE son dossier assigné,
   pas les autres dossiers du même cabinet
   ```
8. **Désactivation d'un membre par l'admin_cabinet** :
   ```
   @browser connecte-toi en admin_cabinet, va sur "Équipe", vérifie la
   section "Membres", désactive un compte collaborateur/dirigeant_pme,
   puis dans une fenêtre privée essaie de te connecter avec ce compte —
   vérifie que la connexion échoue
   ```

---

## 2. Authentification & session

### 1. Vue d'ensemble

Le flow 1 a posé la règle : l'isolation entre cabinets repose sur un
`CurrentUser(id, organisation_id, role)` de confiance, dérivé du JWT. Ce
flow-ci explique **comment ce JWT est fabriqué, vérifié et renouvelé** — la
porte d'entrée réelle de l'application, avant même de voir un dossier.

Problème résolu : prouver l'identité d'un utilisateur à chaque requête HTTP,
**sans état côté serveur** (pas de table `sessions` à interroger), tout en
supportant une durée de vie longue (l'utilisateur ne doit pas retaper son
mot de passe toutes les 30 minutes) sans pour autant garder un jeton
dangereux (longue durée) exposé à chaque appel API.

Comment, en une phrase : deux jetons signés HS256 — un `access_token`
courte durée (30 min) envoyé à chaque requête, et un `refresh_token` longue
durée (14 jours) gardé de côté et échangé contre un nouvel `access_token`
quand ce dernier expire — plus un hachage bcrypt pour ne jamais stocker de
mot de passe en clair.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Lignes | Rôle |
|---|---|---|---|
| `backend/app/auth.py` | `hash_password` / `verify_password` | 46-51 | Hachage/vérification bcrypt des mots de passe |
| `backend/app/auth.py` | `TokenPayload`, `_create_token` | 56-66 | Schéma du contenu du JWT + fabrication générique d'un token signé |
| `backend/app/auth.py` | `create_access_token` / `create_refresh_token` | 69-80 | Fabriquent les deux jetons avec leur durée de vie propre |
| `backend/app/auth.py` | `decode_token` | 83-92 | Décode + vérifie signature et type d'un JWT |
| `backend/app/auth.py` | `CurrentUser`, `get_current_user` | 97-105 | Dependency FastAPI : JWT → objet utilisateur de confiance |
| `backend/app/auth.py` | `require_role` | 108-122 | Dependency factory pour restreindre une route à certains rôles |
| `backend/app/routes_auth.py` | `register` | 73-105 | Crée une `Organisation` + son premier `admin_cabinet` |
| `backend/app/routes_auth.py` | `login` | 108-119 | Vérifie email/password, émet les 2 jetons |
| `backend/app/routes_auth.py` | `refresh` | 122-135 | Échange un refresh_token valide contre une nouvelle paire de jetons |
| `backend/app/routes_auth.py` | `me` / `update_me` / `change_password` | 138-190 | Lecture/mise à jour du profil courant |
| `backend/app/models.py` | `class Utilisateur` | 99-116 | `password_hash`, `role`, `actif` — champs consommés par ce flow |
| `frontend/src/context/AuthContext.jsx` | `AuthProvider` (`login`, `register`, `logout`, `tryRefresh`, restauration) | 11-110 | State React de session, orchestre les appels `/auth/*` |
| `frontend/src/config/api.js` | store de token + `apiFetch` | 10-54 | Garde l'access token en mémoire JS, l'attache à chaque requête |
| `frontend/src/pages/LoginPage.jsx` | formulaire login/register | 1-85 | UI de connexion/inscription |
| `frontend/src/App.jsx` | rendu selon `status` | 334-361 | Écran de chargement / login / app selon l'état de session |

---

### 3. Explication détaillée du code

#### a) Mots de passe — `backend/app/auth.py:40, 46-51`

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)
```

- `CryptContext(schemes=["bcrypt"], ...)` : objet de `passlib` configuré
  pour **un seul** algorithme, bcrypt. `deprecated="auto"` sert à marquer
  automatiquement comme "à re-hacher" tout hash produit par un schéma
  retiré de la liste dans le futur (permet de changer d'algorithme plus
  tard sans casser les comptes existants) — inutile tant qu'il n'y a qu'un
  seul schéma, mais ne coûte rien à laisser en place.
- `hash_password` : bcrypt génère un **sel aléatoire** à chaque appel et
  l'embarque dans la chaîne de sortie — deux appels avec le même mot de
  passe produisent deux hash différents. Nécessaire pour empêcher une
  attaque par table arc-en-ciel (rainbow table) si la base fuitait un jour.
  Paramètre : `password: str` en clair. Retour : une chaîne opaque
  (algorithme + sel + hash), stockée telle quelle dans `password_hash`.
- `verify_password` : ne "décode" jamais le hash pour comparer — bcrypt
  re-hache `plain_password` avec le **même sel** extrait de
  `password_hash`, puis compare les deux chaînes résultantes en temps
  constant (protection contre les attaques par timing). Retourne un
  booléen, ne lève pas d'exception sur mot de passe incorrect.
- Si on supprimait `verify_password` et comparait `password == stored_hash`
  directement : ça ne marcherait jamais (le hash ne ressemble en rien au
  mot de passe), et même si on comparait deux hashs égaux naïvement, on
  perdrait la protection contre le timing attack que `passlib` gère en
  interne.

#### b) Fabrication d'un token — `backend/app/auth.py:56-66`

```python
class TokenPayload(BaseModel):
    sub: str  # utilisateur_id
    organisation_id: str
    role: str
    type: str  # "access" | "refresh"

def _create_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
```

- `TokenPayload` : modèle Pydantic qui documente le **contrat** du contenu
  d'un JWT décodé — pas utilisé pour créer le token (ça reste un `dict`),
  mais pour valider sa forme après décodage (voir `decode_token`). `sub`
  (subject) est le nom standard JWT pour l'identifiant du sujet du token.
- `_create_token(data, expires_delta)` : fonction privée (préfixe `_`)
  partagée par `create_access_token` et `create_refresh_token`, pour ne pas
  dupliquer la logique de signature. `data.copy()` : évite de muter le
  dict passé par l'appelant en y ajoutant `exp` — sans ce `.copy()`, un
  appelant qui réutiliserait son dict après l'appel se retrouverait avec un
  champ `exp` parasite qu'il n'a jamais demandé.
- `to_encode["exp"] = datetime.now(timezone.utc) + expires_delta` : `exp`
  est une claim JWT **standard**, comprise nativement par la librairie
  `jose` — c'est elle qui rejette le token comme expiré au décodage
  (`decode_token`), pas une vérification manuelle de date écrite à la main.
  `timezone.utc` est essentiel : sans fuseau explicite, une comparaison
  entre une date naïve et une date consciente du fuseau lèverait une
  `TypeError` au décodage sur certains environnements.
- `jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)` : signe le
  payload avec **HS256** (HMAC-SHA256), un algorithme **symétrique** — la
  même clé (`JWT_SECRET`) sert à signer et à vérifier. Retour : une chaîne
  de 3 segments encodés en base64 (header.payload.signature). Si
  `JWT_SECRET` fuitait, n'importe qui pourrait forger un token valide pour
  n'importe quel rôle — c'est la clé de voûte de toute la sécurité auth,
  d'où le `raise RuntimeError` au démarrage si elle est absente de `.env`
  (`auth.py:31-35`).

#### c) Les deux jetons — `backend/app/auth.py:69-80`

```python
def create_access_token(utilisateur_id: str, organisation_id: str, role: str) -> str:
    return _create_token(
        {"sub": utilisateur_id, "organisation_id": organisation_id, "role": role, "type": "access"},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

def create_refresh_token(utilisateur_id: str, organisation_id: str, role: str) -> str:
    return _create_token(
        {"sub": utilisateur_id, "organisation_id": organisation_id, "role": role, "type": "refresh"},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
```

- Les deux fonctions ont une signature identique et ne diffèrent que par
  `"type"` (`"access"` vs `"refresh"`) et la durée de vie
  (`ACCESS_TOKEN_EXPIRE_MINUTES = 30` vs `REFRESH_TOKEN_EXPIRE_DAYS = 14`,
  lignes 37-38). Le champ `"type"` est ce qui empêche un refresh_token
  volé d'être utilisé directement comme access_token sur une route
  protégée — voir `decode_token` (section suivante) qui vérifie ce champ.
- Les deux jetons embarquent **les mêmes claims métier**
  (`organisation_id`, `role`) — ce qui permet à `refresh` (routes_auth.py)
  de réémettre un nouvel access_token sans re-décoder la base, uniquement
  à partir de ce que le refresh_token contenait déjà.
- Si on supprimait le refresh_token et gardait un seul token longue durée
  (14 jours) envoyé à chaque requête : ce jeton traînerait dans le
  `localStorage`/les headers réseau pendant 2 semaines à chaque requête,
  augmentant fortement la fenêtre d'exploitation en cas de vol (XSS, log
  réseau). Le découpage limite l'exposition du jeton *utilisé activement*
  à 30 minutes.

#### d) Décodage — `backend/app/auth.py:83-92`

```python
def decode_token(token: str, expected_type: str = "access") -> TokenPayload:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide ou expiré")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Type de token incorrect")

    return TokenPayload(**payload)
```

- `jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])` : vérifie la
  signature (donc l'intégrité et l'authenticité) **et** l'expiration
  (`exp`) en un seul appel — `jose` lève `JWTError` pour les deux cas
  (signature invalide OU expiré), volontairement fusionnés côté message
  utilisateur ("Token invalide ou expiré") pour ne pas donner d'indice
  différent à un attaquant qui tenterait de distinguer "j'ai un mauvais
  secret" de "mon token a expiré".
- `algorithms=[JWT_ALGORITHM]` **doit** être une liste explicite : c'est une
  protection connue contre une classe de vulnérabilités JWT où un
  attaquant force l'algorithme `none` ou bascule HS256/RS256 pour forger un
  token. Sans cette liste (en laissant la librairie deviner l'algorithme
  depuis le header du token), un attaquant contrôlant le header JWT
  pourrait potentiellement contourner la vérification de signature.
- `if payload.get("type") != expected_type` : c'est **ce test précisément**
  qui empêche un refresh_token volé (mais valide) d'être présenté comme
  access_token à `get_current_user`, ou inversement. Sans lui, un
  refresh_token capturé donnerait un accès direct aux routes protégées,
  sans jamais passer par `/auth/refresh`.
- `TokenPayload(**payload)` : validation Pydantic finale — si le payload
  décodé ne contient pas exactement `sub`/`organisation_id`/`role`/`type`,
  cette ligne lève une `ValidationError` (non interceptée ici, donc remonte
  en 500). Ça détecterait un token structurellement invalide qui aurait
  quand même une signature valide (scénario peu probable en pratique, mais
  filet de sécurité gratuit).

#### e) Dependency FastAPI — `backend/app/auth.py:41, 97-105`

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

class CurrentUser(BaseModel):
    id: str
    organisation_id: str
    role: str

def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    payload = decode_token(token, expected_type="access")
    return CurrentUser(id=payload.sub, organisation_id=payload.organisation_id, role=payload.role)
```

- `OAuth2PasswordBearer(tokenUrl="/auth/login")` : ce n'est **pas** un vrai
  flux OAuth2 (le endpoint `/auth/login` attend du JSON, pas le format
  `application/x-www-form-urlencoded` qu'exige le standard
  `OAuth2PasswordRequestForm`). Cet objet sert uniquement à deux choses :
  extraire le header `Authorization: Bearer <token>` de la requête, et
  déclarer à Swagger UI (`/docs`) où se trouve l'écran "Authorize". Point à
  ne pas confondre à l'oral : le nom "OAuth2" ici est un détail
  d'intégration FastAPI/Swagger, pas une implémentation du protocole OAuth2.
- `get_current_user(token: str = Depends(oauth2_scheme))` : FastAPI résout
  d'abord `oauth2_scheme`, qui lève lui-même une 401 si l'en-tête
  `Authorization` est absent — donc `get_current_user` n'est même jamais
  appelée dans ce cas. Si l'en-tête est présent, `token` contient la
  chaîne brute après `Bearer `.
- `decode_token(token, expected_type="access")` : **c'est ici** que le
  choix "access uniquement" est fait — cette dependency, utilisée par
  toutes les routes protégées via `get_tenant_db` (flow 1), n'accepte
  jamais un refresh_token, même valide et non expiré.
- Retour : un `CurrentUser` — objet minimal (pas de nom, pas d'email) :
  volontairement réduit aux 3 champs nécessaires à l'autorisation
  (identité, tenant, rôle), pour ne pas coupler cette dependency aux
  détails du modèle `Utilisateur` en base ni faire de requête DB à chaque
  appel.

#### f) Restriction par rôle — `backend/app/auth.py:108-122`

```python
def require_role(*allowed_roles: str):
    def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle '{user.role}' non autorisé pour cette action.",
            )
        return user
    return _checker
```

- `require_role(*allowed_roles: str)` : une **dependency factory** — elle
  ne retourne pas directement une dependency FastAPI, mais une fonction
  (`_checker`) paramétrée par les rôles autorisés. C'est ce qui permet
  d'écrire `Depends(require_role("admin_cabinet"))` avec un rôle différent
  par route, sans dupliquer `_checker` pour chaque combinaison de rôles.
- `_checker` dépend elle-même de `get_current_user` : la vérification de
  rôle **s'appuie sur**, mais ne remplace pas, la vérification d'identité —
  l'ordre est : d'abord prouver qui on est (JWT valide), ensuite vérifier
  si ce rôle a le droit d'agir ici.
- `403 Forbidden` (et non 401) : distinction volontaire — 401 signifie "je
  ne sais pas qui vous êtes" (déjà géré par `get_current_user`), 403
  signifie "je sais qui vous êtes, mais vous n'avez pas le droit". Un
  frontend bien écrit peut réagir différemment (401 → renvoyer au login,
  403 → afficher "accès refusé" sans déconnecter).

#### g) Inscription — `backend/app/routes_auth.py:73-105`

```python
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.execute(select(Utilisateur).where(Utilisateur.email == req.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email.")

    org = Organisation(id=uuid.uuid4(), nom=req.nom_organisation, type_organisation=req.type_organisation)
    db.add(org)
    db.flush()  # pour obtenir org.id sans commit complet

    user = Utilisateur(
        id=uuid.uuid4(), organisation_id=org.id, email=req.email,
        password_hash=hash_password(req.password), nom_complet=req.nom_complet,
        role=RoleUtilisateur.admin_cabinet,
    )
    db.add(user)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id), str(org.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id), str(org.id), user.role.value),
    )
```

- `Depends(get_db)`, pas `get_tenant_db` : logique — au moment de
  l'inscription, il n'y a **pas encore** d'organisation à poser en
  contexte tenant, c'est justement cette route qui va en créer une (même
  raison que l'exception RLS du flow 1).
- Vérification d'unicité d'email **avant** toute création : évite de créer
  une `Organisation` orpheline si l'email existe déjà — sans ce garde-fou,
  une tentative d'inscription avec un email déjà pris laisserait quand même
  une `Organisation` fantôme en base (créée avant l'échec).
- `db.flush()` : envoie les instructions SQL en attente à Postgres **sans**
  valider la transaction (pas de `COMMIT`), ce qui fait qu'`org.id`
  (généré par défaut Python `uuid.uuid4`, donc déjà connu **avant** même le
  flush ici — voir `_uuid_pk()`) est disponible pour construire `user`. En
  réalité, comme les deux ID sont des UUID générés côté Python et non des
  séquences Postgres, ce `flush()` n'est pas strictement nécessaire pour
  obtenir `org.id` — mais il garantit que si la contrainte `ForeignKey`
  vers `organisation.id` était violée, l'erreur remonterait ici plutôt qu'au
  `commit()` final, ce qui rendrait le message d'erreur plus précis.
- `role=RoleUtilisateur.admin_cabinet` **codé en dur** : le commentaire du
  code (ligne 75-78) précise que c'est volontaire — ce endpoint public ne
  crée jamais que des `admin_cabinet` (auto-inscription), jamais un
  `admin_plateforme` (voir `scripts/create_platform_admin.py`, seul chemin
  légitime).
- **Point à noter honnêtement** : `RegisterRequest.type_organisation` est
  typé `TypeOrganisation` (l'enum complet), sans restriction explicite à
  `{cabinet, pme}` côté serveur — seul le `<select>` du frontend
  (`LoginPage.jsx:52-55`) limite le choix à ces deux valeurs. Un appel direct
  à l'API (hors frontend) avec `type_organisation: "interne"` serait accepté
  par la validation Pydantic (l'enum contient bien cette valeur) et créerait
  une organisation de type `interne` sans jamais donner le rôle
  `admin_plateforme` associé (le rôle reste codé en dur ci-dessus) — donc
  pas d'élévation de privilège, mais une organisation `interne` "polluante"
  pourrait fausser les compteurs plateforme que le flow 1 mentionnait. Un
  contrôle explicite (`if req.type_organisation == TypeOrganisation.interne:
  raise HTTPException(...)`) n'existe pas aujourd'hui côté backend.
- Retour `TokenResponse` : l'utilisateur est connecté **immédiatement**
  après inscription, sans étape de vérification d'email — compromis MVP,
  pas de SMTP en place (cf. carte du code : "SMTP reporté en phase 6").

#### h) Connexion — `backend/app/routes_auth.py:108-119`

```python
@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(Utilisateur).where(Utilisateur.email == req.email)).scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")
    if not user.actif:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ce compte a été désactivé. Contactez votre administrateur.")

    return TokenResponse(
        access_token=create_access_token(str(user.id), str(user.organisation_id), user.role.value),
        refresh_token=create_refresh_token(str(user.id), str(user.organisation_id), user.role.value),
    )
```

- `if not user or not verify_password(...)` : **un seul et même message
  d'erreur** ("Email ou mot de passe incorrect") que l'email n'existe pas
  OU que le mot de passe soit faux. C'est volontaire — un message distinct
  ("cet email n'existe pas") permettrait à un attaquant d'énumérer les
  comptes existants en testant des emails un par un (user enumeration).
  Court-circuit important : Python évalue `not user` en premier, donc si
  `user` est `None`, `verify_password` n'est jamais appelée (évite un crash
  sur `user.password_hash` qui n'existerait pas).
- `if not user.actif` : vérifié **une seule fois, ici**, au login (et dans
  `refresh`, section suivante) — pas à chaque requête protégée, cohérent
  avec le commentaire déjà vu sur `Utilisateur.actif` (flow 1, section 3d).
  Un compte désactivé pendant qu'un access_token de 30 min est encore
  valide continuera de fonctionner jusqu'à expiration de ce token.
- Aucune limite de tentatives (rate limiting) n'est visible dans ce code —
  point honnête à signaler : rien n'empêche aujourd'hui une attaque par
  force brute sur `/auth/login` au niveau applicatif.

#### i) Renouvellement — `backend/app/routes_auth.py:122-135`

```python
@router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(req.refresh_token, expected_type="refresh")
    user = db.get(Utilisateur, uuid.UUID(payload.sub))
    if not user or not user.actif:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalide.")
    return TokenResponse(
        access_token=create_access_token(payload.sub, payload.organisation_id, payload.role),
        refresh_token=create_refresh_token(payload.sub, payload.organisation_id, payload.role),
    )
```

- `decode_token(req.refresh_token, expected_type="refresh")` : rejette
  immédiatement un access_token présenté ici (mauvais `type`) — voir
  section 3d.
- `db.get(Utilisateur, uuid.UUID(payload.sub))` : **seul point de tout le
  flux d'authentification qui retouche la base** en dehors de
  login/register — le commentaire du code (routes_auth.py:125-128)
  l'explique : contrairement à l'access_token (courte durée, une
  vérification stateless suffit), le refresh_token vit 14 jours. Sans ce
  contrôle DB, un compte désactivé pourrait continuer à renouveler
  indéfiniment son accès pendant ces 14 jours en ignorant totalement la
  désactivation.
- Le nouveau couple de jetons est réémis à partir de `payload` (les claims
  du refresh_token), **pas** en relisant `user.role` fraîchement depuis la
  base — donc si le rôle d'un utilisateur change en base pendant que son
  refresh_token est encore valide, le nouvel access_token émis ici portera
  encore **l'ancien rôle**, jusqu'à ce que l'utilisateur se reconnecte
  complètement (nouveau login). C'est une conséquence directe du design
  stateless, à connaître si le jury demande "et si on change le rôle de
  quelqu'un en cours de session ?".

#### j) Restauration de session côté frontend — `frontend/src/context/AuthContext.jsx:26-56`

```jsx
const tryRefresh = useCallback(async () => {
  const refresh_token = localStorage.getItem(REFRESH_KEY)
  if (!refresh_token) return false
  const res = await fetch(`${API_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token }),
  })
  if (!res.ok) return false
  const data = await res.json()
  applyTokens(data.access_token, data.refresh_token)
  return true
}, [applyTokens])

useEffect(() => {
  (async () => {
    const refreshed = await tryRefresh()
    if (!refreshed) { setStatus('anonymous'); return }
    try {
      const me = await fetchMe()
      setUser(me)
      setStatus('authenticated')
    } catch { setStatus('anonymous') }
  })()
}, [tryRefresh, fetchMe])
```

- Ce `useEffect` tourne **une seule fois** au montage de `AuthProvider`
  (dépendances stables via `useCallback`) — c'est ce qui permet à une
  session de survivre à un F5 ou une réouverture d'onglet, alors que
  l'access_token, lui, vit uniquement en mémoire JS et disparaît à chaque
  rechargement de page.
- `tryRefresh` utilise `fetch` **direct**, pas `apiFetch` : logique, à cet
  instant précis il n'y a par définition aucun access_token à attacher —
  `apiFetch` n'aurait rien de plus à offrir ici que d'ajouter un header
  Authorization vide.
- Si `localStorage` ne contient pas de refresh_token (première visite,
  logout précédent) : retourne `false` **sans faire d'appel réseau** —
  évite un aller-retour HTTP inutile qui échouerait de toute façon.
- Si `/auth/refresh` échoue (refresh_token expiré après 14 jours, ou compte
  désactivé) : `res.ok` est faux, la fonction retourne `false`, et
  `setStatus('anonymous')` renvoie l'utilisateur au `LoginPage`. Le
  `refresh_token` périmé reste dans le `localStorage` à ce stade (pas de
  nettoyage explicite) — sans conséquence pratique puisqu'il sera de toute
  façon rejeté au prochain essai, mais un `localStorage.removeItem` ici
  serait plus propre.
- Le `catch { setStatus('anonymous') }` autour de `fetchMe()` couvre le cas
  où le refresh a réussi (nouveaux tokens obtenus) mais `/auth/me` échoue
  quand même (ex. utilisateur supprimé entre-temps) — sans ce filet,
  l'exception non gérée resterait bloquée en `status: 'loading'`
  indéfiniment, un écran de chargement infini pour l'utilisateur.

#### k) Connexion côté frontend — `frontend/src/context/AuthContext.jsx:58-73`

```jsx
const login = useCallback(async (email, password) => {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail
    throw new Error(detail || 'Échec de connexion')
  }
  const data = await res.json()
  applyTokens(data.access_token, data.refresh_token)
  const me = await fetchMe()
  setUser(me)
  setStatus('authenticated')
}, [applyTokens, fetchMe])
```

- `.json().catch(() => null)` : défensif contre une réponse d'erreur qui ne
  serait pas du JSON valide (ex. 502 renvoyé par un proxy/reverse-proxy
  devant le backend, corps HTML) — sans ce `.catch`, une erreur réseau
  ferait planter le parsing JSON lui-même et masquerait le vrai message
  d'erreur derrière une exception différente.
- `throw new Error(detail || 'Échec de connexion')` : propage l'erreur à
  l'appelant (`LoginPage.submit`, section suivante) qui l'affiche —
  `AuthContext` ne gère lui-même aucun affichage, seulement l'état et les
  appels réseau (séparation state/UI).
- Après un login réussi, `fetchMe()` est appelé **immédiatement** : le
  login ne renvoie que les jetons, pas le profil complet (email, rôle,
  nom) — c'est `/auth/me` qui fournit ces informations. Si `fetchMe()`
  échouait ici (improbable juste après un login réussi, mais possible en
  cas de coupure réseau), l'exception remonterait non gérée jusqu'à
  `LoginPage.submit`, qui l'afficherait comme une erreur de connexion —
  légèrement trompeur puisque le login a en réalité réussi côté serveur.

#### l) Store de token — `frontend/src/config/api.js:10-19, 36-54`

```js
let _accessToken = null

export function setAccessToken(token) { _accessToken = token }
export function getAccessToken() { return _accessToken }

export async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (_accessToken) headers['Authorization'] = `Bearer ${_accessToken}`
  ...
  const res = await fetch(`${API_URL}${path}`, { ...options, headers })
  if (res.status === 401) {
    const err = new Error('unauthorized')
    err.status = 401
    throw err
  }
  return res
}
```

- `_accessToken` en **variable module-level**, pas en state React ni en
  `localStorage` : c'est la décision structurante de ce flow côté frontend.
  Un `localStorage` serait lisible par n'importe quel script injecté en XSS
  sur la page — une variable JS purement en mémoire ne survit pas à un F5
  (d'où le besoin de `tryRefresh` au montage) mais n'est jamais persistée
  sur disque. Seul le refresh_token (plus rarement utilisé, un seul appel
  toutes les 30 min) accepte ce compromis de persistance.
- `if (_accessToken) headers['Authorization'] = ...` : attache le token
  **seulement s'il existe** — permet à `apiFetch` d'être utilisé aussi bien
  avant login (aucun header) qu'après, sans code dupliqué.
- `if (res.status === 401) throw ...` : transforme un 401 HTTP en exception
  JS avec un `.status` attaché, pour que l'appelant puisse le distinguer
  d'une autre erreur réseau. **Point à noter honnêtement** : ce bloc lève
  une erreur, mais rien dans le code lu ne rattrape spécifiquement ce
  `err.status === 401` pour déclencher automatiquement un
  `tryRefresh()`/`logout()` — chaque appelant (`loadDashboard`,
  `runAudit`...) traite l'erreur via son propre `catch (e)` générique, qui
  l'affiche comme une erreur métier plutôt que de re-tenter une
  reconnexion. En pratique, l'utilisateur ne revoit l'écran de login
  qu'après un F5 (qui redéclenche `tryRefresh` dans `AuthContext`), pas
  automatiquement au moment du 401. C'est une amélioration possible, pas
  un bug qui casse l'appli — mais un vrai point à assumer si le jury
  demande "que se passe-t-il exactement quand mon token expire en pleine
  navigation ?".

#### m) Rendu selon le statut — `frontend/src/App.jsx:334-361`

```jsx
export default function App() {
  const { status, user } = useAuth()
  ...
  if (status === 'loading') {
    return <div className="auth-shell"><span className="spinner dark" /></div>
  }
  if (status === 'anonymous') {
    return <LoginPage />
  }
  if (user?.role === 'admin_plateforme') { return <PlatformAdminShell /> }
  ...
```

- `status` a 3 valeurs possibles (`'loading' | 'authenticated' |
  'anonymous'`, déclarées dans `AuthContext.jsx:13`) — un booléen simple
  (`isLoggedIn`) n'aurait pas suffi : il faut un 3e état pour couvrir la
  fenêtre entre le montage de l'app et la fin de `tryRefresh()`, pendant
  laquelle on ne sait **pas encore** si l'utilisateur est connecté. Sans
  cet état intermédiaire, l'app afficherait un flash de `LoginPage` avant
  de basculer vers le shell applicatif à chaque F5 d'un utilisateur déjà
  connecté — désagréable et donnerait l'impression que la session ne
  persiste pas.
- L'ordre des `if` est significatif : `loading` avant `anonymous` avant le
  routing par rôle — chaque cas n'a de sens que si le précédent est écarté
  (on ne peut pas lire `user.role` tant que `status !== 'authenticated'`,
  `user` serait `null`).

---

### 4. Flux complet des données

**A. Connexion initiale**

```
LoginPage (submit)
   │
   ▼
AuthContext.login(email, password) ──fetch──► POST /auth/login
   │                                                │
   │                                    vérifie email + bcrypt(password)
   │                                    vérifie actif
   │                                    émet {access_token, refresh_token}
   ▼                                                │
applyTokens() ◄────────────────────────────────────┘
   │  access_token → variable JS (api.js, en mémoire)
   │  refresh_token → localStorage
   ▼
fetchMe() ──apiFetch──► GET /auth/me (Authorization: Bearer access_token)
   │                          │
   │                          ▼
   │              get_current_user décode le JWT
   │              relit Utilisateur+Organisation en base pour le profil affichable
   ▼                          │
setUser(me) / setStatus('authenticated') ◄──┘
   │
   ▼
App.jsx choisit le shell (AppShell / DirigeantShell / PlatformAdminShell)
```

**B. Restauration de session (F5, réouverture d'onglet)**

```
Montage de <AuthProvider>
   │  access_token en mémoire = perdu (variable JS réinitialisée)
   │  refresh_token = encore présent dans localStorage
   ▼
tryRefresh() ──fetch──► POST /auth/refresh {refresh_token}
   │                          │
   │              decode_token(type="refresh")
   │              vérifie user.actif en base
   │              réémet {access_token, refresh_token} neufs
   ▼                          │
applyTokens() ◄───────────────┘
   │
   ▼
fetchMe() → setUser() → setStatus('authenticated')
        (ou setStatus('anonymous') si refresh_token expiré/invalide)
```

**C. Requête protégée pendant la navigation**

```
Composant (ex. DashboardPage) ──dossierFetch──► apiFetch (attache Authorization)
                                                        │
                                                        ▼
                                          backend : get_current_user décode l'access_token
                                                        │
                                          ┌─────────────┴─────────────┐
                                          ▼                           ▼
                                   token valide                token expiré/invalide
                                          │                           │
                                          ▼                           ▼
                                  requête traitée            401 renvoyé au frontend
                                  normalement                        │
                                                                       ▼
                                                        apiFetch lève une exception
                                                        `err.status === 401`
                                                                       │
                                                        (aujourd'hui : traitée comme une
                                                        erreur métier générique par
                                                        l'appelant, pas de retry auto —
                                                        voir section 3l)
```

---

### 5. Lien avec le frontend

| Étape | Composant / Page | Hook | Appel | Endpoint | JSON envoyé | JSON reçu | Impact UI |
|---|---|---|---|---|---|---|---|
| Connexion | `LoginPage.jsx` | `useAuth().login` | `fetch` direct | `POST /auth/login` | `{email, password}` | `{access_token, refresh_token, token_type}` | `status → authenticated` après `fetchMe` |
| Inscription | `LoginPage.jsx` (mode register) | `useAuth().register` | `fetch` direct | `POST /auth/register` | `{nom_organisation, type_organisation, email, password, nom_complet}` | `{access_token, refresh_token, token_type}` | Crée l'org + connecte immédiatement |
| Restauration | `AuthContext.jsx` (interne, au montage) | — | `fetch` direct | `POST /auth/refresh` | `{refresh_token}` | `{access_token, refresh_token, token_type}` | Évite l'écran de login après un F5 |
| Profil courant | `ProfilePage.jsx` (lecture) | `useAuth().user` | *(déjà en state, pas de fetch)* | — | — | — | Affiche email/rôle/organisation |
| Modifier le nom | `ProfilePage.jsx` | `refreshUser` (après le fetch) | `apiFetch('/auth/me', {method:'PATCH'})` | `PATCH /auth/me` | `{nom_complet}` | `UserResponse` complet | Message "Profil mis à jour", nom rafraîchi |
| Changer le mot de passe | `ProfilePage.jsx` | — | `apiFetch('/auth/me/password', {method:'POST'})` | `POST /auth/me/password` | `{mot_de_passe_actuel, nouveau_mot_de_passe}` | *(204, pas de corps)* | Message succès/erreur, champs vidés |
| Déconnexion | `ProfilePage.jsx` (bouton) | `useAuth().logout` | *(aucun appel réseau)* | — | — | — | Efface le token mémoire + `localStorage`, `status → anonymous` |

---

### 6. Pourquoi cette architecture ?

**JWT stateless plutôt qu'une session serveur (table `sessions` / Redis).**
Alternative écartée : stocker un identifiant de session en base ou en cache
et le vérifier à chaque requête. Rejetée pour un MVP solo à 2 mois : ça
ajoute une dépendance opérationnelle (Redis à héberger/monitorer) et un
aller-retour DB/cache sur **chaque** requête protégée, alors que la
vérification JWT est un calcul cryptographique local, sans I/O. Coût
assumé en échange : pas de révocation immédiate d'un token déjà émis (voir
plus bas).

**Deux jetons (access court + refresh long) plutôt qu'un seul jeton longue
durée.**
Réduit la fenêtre d'exposition du jeton réellement utilisé à chaque requête
à 30 minutes, tout en gardant une expérience utilisateur confortable (pas
de redemande de mot de passe pendant 14 jours). Alternative écartée : un
seul jeton de 14 jours envoyé à chaque appel API — rejetée parce qu'un vol
de ce jeton (XSS, log, proxy compromis) donnerait un accès complet et
prolongé, sans aucun mécanisme de contrôle intermédiaire.

**bcrypt plutôt que SHA-256 simple ou Argon2.**
SHA-256 seul est **rapide** — une qualité pour du hachage générique, un
défaut pour des mots de passe (permet des milliards de tentatives/seconde
en cas de fuite de la base, attaque par force brute hors-ligne). bcrypt est
délibérément lent et intègre un sel automatique. Argon2 (vainqueur du
concours Password Hashing Competition) est un choix plus moderne et
recommandé aujourd'hui, mais bcrypt reste un standard éprouvé et largement
supporté par `passlib` sans configuration supplémentaire — choix pragmatique
pour un MVP, pas une régression de sécurité significative.

**`organisation_id` + `role` embarqués dans le JWT plutôt qu'un lookup DB à
chaque requête.**
Permet à `get_current_user` (utilisée par **toutes** les routes protégées)
de rester un calcul pur, sans session DB. Contrepartie assumée et déjà
documentée (section 3i) : un changement de rôle ou une désactivation ne
prend effet qu'au prochain refresh/login, pas immédiatement.

**refresh_token en `localStorage` plutôt qu'un cookie `httpOnly`.**
Commentaire explicite dans le code
(`AuthContext.jsx:6-8`) : un cookie `httpOnly` émis par le backend serait
plus sûr contre le XSS (inaccessible en JavaScript, donc invisible même à
un script injecté), mais demande de servir frontend et backend sur le même
domaine (ou sous-domaine) pour que le cookie soit envoyé automatiquement —
non garanti dans le déploiement actuel (frontend/backend potentiellement
sur des origines différentes). Compromis explicitement marqué "à revisiter
en Phase 7 (sécurité)" — pas un oubli, un arbitrage assumé pour le MVP.

**Pas de mécanisme de révocation/blacklist de token.**
Conséquence directe du choix stateless : un access_token émis reste valide
jusqu'à expiration (30 min max), même si l'utilisateur se déconnecte ou est
désactivé entre-temps côté frontend. `logout()` efface les jetons **côté
client** mais ne les invalide pas côté serveur — un jeton volé avant le
logout resterait utilisable jusqu'à sa propre expiration. Alternative
(liste noire de tokens révoqués, vérifiée à chaque requête) écartée pour la
même raison que "pas de session serveur" : réintroduit un état partagé et
un aller-retour supplémentaire à chaque requête, ce que le design JWT
cherchait justement à éviter.

**`OAuth2PasswordBearer` alors que `/auth/login` n'est pas un vrai flux
OAuth2 form-encoded.**
Détaillé en section 3e — choix pragmatique pour bénéficier gratuitement de
l'intégration Swagger UI (`/docs`) sans implémenter le standard OAuth2
complet, non nécessaire ici puisqu'il n'y a qu'un seul client (le frontend
Nisab), pas un écosystème de clients tiers à authentifier.

---

### 7. Lien avec le cahier des charges

Ce flow n'est **pas un module numéroté** du cahier des charges en tant que
tel — c'est une brique d'infrastructure prérequise, qui sous-tend le
module 7 : *"Espaces & multi-tenant [...] comptes, rôles, isolation des
données"* —
[`cahier-des-charges.md:46-47`](../cahier-des-charges.md#L46-L47). Sans un
mécanisme fiable de "prouver qui je suis", le module 7 (comptes/rôles) et
la contrainte technique *"Multi-tenant, isolation stricte des données ;
confidentialité et hébergement conformes (loi 09-08, CNDP)"* —
[`cahier-des-charges.md:55-56`](../cahier-des-charges.md#L55-L56) — n'ont
aucun fondement : c'est ce flow qui produit le `organisation_id`+`role` de
confiance que le flow 1 (RLS) consomme ensuite.

À l'oral, le point à assumer clairement : l'authentification n'est écrite
nulle part comme un "module" dans le cahier des charges, parce que c'est
une brique technique transverse implicite à tout produit multi-tenant, pas
une fonctionnalité métier différenciante pour un cabinet comptable.

---

### 8. Ce que je dois retenir pour la soutenance

- Deux jetons signés HS256 : `access_token` (30 min, utilisé à chaque requête) et `refresh_token` (14 jours, gardé de côté, échangé contre un nouvel access_token).
- Le JWT est **stateless** : pas de table de sessions, la vérification est un calcul cryptographique local — contrepartie assumée : pas de révocation immédiate d'un token déjà émis.
- bcrypt pour les mots de passe (sel automatique, lenteur volontaire) — jamais de mot de passe en clair stocké ni comparé directement.
- `actif` (désactivation de compte) n'est vérifié qu'au login/refresh, jamais à chaque requête — cohérent avec le design stateless, mais effectif seulement au prochain renouvellement de token.
- Le refresh est le **seul** point du flux d'auth qui retouche la base après le login initial — nécessaire pour bloquer un compte désactivé avant l'expiration naturelle du refresh_token (14 jours).
- Access token en variable JS mémoire (jamais `localStorage`) pour limiter l'exposition XSS ; refresh_token en `localStorage` par compromis assumé (pas de cookie httpOnly pour l'instant).
- Point faible identifié et assumé : un 401 en cours de navigation n'enclenche pas de retry/reconnexion automatique côté frontend aujourd'hui — l'utilisateur ne revoit le login qu'au prochain F5.
- Ce flow n'est pas un module métier du cahier des charges — c'est le socle technique qui rend le module 7 (comptes/rôles/isolation) possible.

---

### 9. Questions probables du jury

**Pourquoi deux tokens plutôt qu'un seul ?**
Pour limiter à 30 minutes la fenêtre d'exposition du jeton réellement
utilisé à chaque requête, tout en gardant une session confortable de 14
jours grâce au refresh_token, qui lui n'est envoyé qu'une fois toutes les
30 minutes environ.

**Que se passe-t-il si le `JWT_SECRET` fuite ?**
N'importe qui pourrait forger un token valide avec n'importe quel rôle et
`organisation_id` — compromission totale de l'isolation multi-tenant. C'est
pour ça que le serveur refuse de démarrer si `JWT_SECRET` est absent du
`.env` (`auth.py:31-35`), et que ce secret ne doit jamais être commité.

**Comment désactiver immédiatement un compte compromis ?**
Le champ `actif` passe à `false` en base, mais l'effet n'est garanti
qu'au prochain `/auth/refresh` ou `/auth/login` — un access_token déjà émis
reste valide jusqu'à ses 30 minutes maximum. Il n'existe pas de mécanisme
de révocation immédiate côté JWT à ce stade du projet.

**Pourquoi bcrypt et pas Argon2, qui est plus moderne ?**
bcrypt reste un standard éprouvé, supporté nativement par `passlib` sans
configuration supplémentaire, suffisant pour un MVP. Argon2 serait un choix
plus recommandé aujourd'hui pour un produit en production long terme, mais
ce n'est pas une faille — bcrypt bien configuré (coût par défaut de
`passlib`) résiste toujours efficacement à une attaque par force brute
hors-ligne.

**Le refresh_token en `localStorage`, n'est-ce pas risqué face au XSS ?**
Oui, c'est un compromis documenté dans le code, pas un oubli : un cookie
`httpOnly` serait plus sûr mais demande frontend et backend sur le même
domaine. L'access_token (utilisé à chaque requête, donc plus exposé) reste
lui en mémoire JS, jamais persisté — c'est le jeton le plus sensible qui
reçoit la protection la plus forte.

**Un développeur peut-il créer un `admin_plateforme` via `/auth/register` ?**
Non — le rôle est codé en dur à `admin_cabinet` dans l'endpoint (ligne 97),
peu importe ce qu'un client enverrait. Seul
`scripts/create_platform_admin.py` (exécuté manuellement, hors API) peut
créer ce rôle.

**Et si on envoie `type_organisation: "interne"` directement à
`/auth/register` sans passer par le frontend ?**
La requête serait acceptée (l'enum `TypeOrganisation` accepte cette
valeur), créant une organisation `interne` avec un simple `admin_cabinet` —
pas d'élévation de privilège puisque le rôle reste codé en dur, mais ça
polluerait les compteurs "organisations internes" que la plateforme
utilise pour distinguer l'équipe Nisab des cabinets clients. C'est un gap
identifié en lisant le code, pas un correctif déjà en place.

**Que se passe-t-il exactement quand mon token expire pendant que je
navigue ?**
Le backend répond 401, `apiFetch` le transforme en exception avec
`err.status === 401`, mais rien n'intercepte spécifiquement ce cas pour
relancer un refresh automatique — l'appelant (ex. `loadDashboard`) l'affiche
comme une erreur générique. L'utilisateur retrouve une session valide en
rechargeant la page (ce qui redéclenche `tryRefresh`). C'est une
amélioration identifiée, pas implémentée à ce stade.

---

### 10. Étapes de test dans l'application

1. **Connexion / déconnexion** :
   ```
   @browser va sur localhost:5173, connecte-toi avec un compte existant,
   vérifie que tu arrives sur le bon shell, puis déconnecte-toi depuis
   la page profil et vérifie le retour à l'écran de login
   ```
2. **Persistance de session au F5** :
   ```
   @browser connecte-toi, recharge la page (F5), et vérifie que tu restes
   connecté sans repasser par l'écran de login
   ```
3. **Mauvais mot de passe → message générique** :
   ```bash
   curl -X POST http://localhost:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"inconnu@test.com","password":"n_importe_quoi"}'
   # attendu : 401, "Email ou mot de passe incorrect." (même message que
   # pour un email existant avec un mauvais mot de passe)
   ```
4. **Cycle complet access → refresh** :
   ```bash
   # 1. login, récupérer refresh_token
   curl -s -X POST http://localhost:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"<email_test>","password":"<mdp_test>"}'

   # 2. échanger le refresh_token contre une nouvelle paire
   curl -s -X POST http://localhost:8000/auth/refresh \
     -H "Content-Type: application/json" \
     -d '{"refresh_token":"<refresh_token_recupere>"}'
   ```
5. **Un refresh_token refusé comme access_token** :
   ```bash
   curl -s http://localhost:8000/auth/me \
     -H "Authorization: Bearer <refresh_token_recupere>"
   # attendu : 401 "Type de token incorrect"
   ```
6. **Compte désactivé** (nécessite un compte de test, `actif=false` en base
   ou via un futur endpoint admin) :
   ```
   @browser connecte-toi avec un compte désactivé et vérifie le message
   "Ce compte a été désactivé. Contactez votre administrateur."
   ```
7. **Changement de mot de passe** :
   ```
   @browser va sur la page profil, change le mot de passe, déconnecte-toi,
   puis reconnecte-toi avec le NOUVEAU mot de passe pour confirmer
   ```

---

*(Flows 3 à 5 et 7 à 13 à venir au fil de nos échanges, avec le même format complet
en 10 points : vue d'ensemble, localisation code, explication ligne par
ligne, flux de données, lien frontend, choix d'architecture, cahier des
charges, résumé, questions du jury, tests interface.)*

---

---

## 6. Pipeline d'audit IA — détection de risques RAG-only

### 1. Vue d'ensemble

C'est le cœur produit. Tout le reste de Nisab existe pour l'alimenter (les
connecteurs, le corpus) ou pour exploiter ce qu'il produit (le dashboard, la
simulation de contrôle, le workflow de correction).

Sa mission : prendre les écritures comptables d'une PME et dire, **pour chacune**,
si elle présente un risque fiscal — en s'appuyant exclusivement sur le corpus
juridique marocain versionné, et en citant l'article qui fonde le jugement.

Deux contraintes gouvernent toute sa conception, et il faut les avoir en tête
avant de lire une ligne de code :

**1. RAG-only.** Aucune règle fiscale n'est codée en dur. Il a existé dans le
projet un `compliance_checker.py` à seuils écrits à la main (« paiement en
espèces > 5 000 DH ») ; il est **déprécié et ne doit pas être relancé**. La
raison n'est pas esthétique : ses `reference_cgi` n'étaient jamais vérifiées
contre le corpus versionné et il ne produisait aucun `rag_sources`, donc aucune
`CitationRisque` n'était jamais créée pour ses findings. Il fabriquait des
alertes **qui avaient l'air sourcées et ne l'étaient pas** — à l'endroit exact
du produit où l'anti-hallucination est non négociable.

**2. Aucun seuil de similarité brut.** On ne filtre jamais les candidats par un
score de cosinus minimal. Les embeddings de textes juridiques souffrent
d'anisotropie : les scores se concentrent dans une bande étroite, et un seuil
qui marche sur un article en fait taire un autre. Le filtrage est **sémantique**,
confié à un LLM qui lit l'écriture et l'article et juge si les conditions
d'application sont réunies.

D'où l'architecture en **deux temps** : un retrieval large qui privilégie le
rappel, puis un filtrage de pertinence qui rétablit la précision.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Rôle |
|---|---|---|
| `backend/app/ai_auditor.py` | `run_ai_rag_audit()` | Point d'entrée, boucle sur les écritures + passe de retry |
| `backend/app/ai_auditor.py` | `_audit_single_move()` | Le pipeline complet pour UNE écriture |
| `backend/app/ai_auditor.py` | `_build_transaction_summary()` | Écriture Odoo → texte lisible par un LLM |
| `backend/app/ai_auditor.py` | `_reformulate_queries()` | 1 à 3 requêtes focalisées, vocabulaire juridique |
| `backend/app/ai_auditor.py` | `_filter_relevant_articles()` | Filtrage sémantique de pertinence |
| `backend/app/ai_auditor.py` | `_normalize_ref()` | Comparaison de références insensible à la casse |
| `backend/app/ai_auditor.py` | `AUDIT_SYSTEM_PROMPT` | Les 3 issues possibles, format JSON strict |
| `backend/app/vectorstore.py` | `PgVectorStore.search()` | Recherche dense pgvector sur `statut = 'valide'` |
| `backend/app/llm_client.py` | `llm_call_json()`, 2 modèles | Fallback Groq → OpenRouter, backoff sur quota |
| `backend/app/routes_dossiers.py` | `_execute_audit()` | Cache par hash + persistance (voir flux 14) |
| `backend/app/compliance_checker.py` | *(déprécié)* | Ne pas relancer — importé par personne |

---

### 3. Explication détaillée du code

#### a) Le résumé de transaction — parler au LLM, pas à un parseur

```python
summary = f"""ÉCRITURE COMPTABLE A ANALYSER :
N° Pièce / Facture : {name}
Date : {date_str}
Journal comptable : {journal}
Fournisseur / Tiers : {partner_name} (ICE / N° TVA : {partner_ice or 'NON RENSEIGNÉ / MANQUANT'})
Montant Total TTC : {amount:,.2f} DH

Détail des écritures comptables :
{lines_str}
"""
```

Deux détails qui ne sont pas des détails.

**`'NON RENSEIGNÉ / MANQUANT'` en toutes lettres.** Un champ vide dans un
prompt est invisible pour un LLM — il ne remarque pas une absence. L'écrire
explicitement transforme un silence en fait analysable, et c'est ce qui permet
de détecter l'anomalie « fournisseur sans ICE » (Art. 145 CGI).

**Le mode de règlement est propagé jusque dans le résumé** (`Mode: especes`).
C'est un fait fiscalement significatif **en lui-même**, indépendamment de la
nature de l'achat — le plafond de déductibilité des paiements en espèces (Art.
193 CGI) ne dépend pas de ce qu'on a acheté.

#### b) La reformulation en requêtes focalisées, et la mesure qui la justifie

C'est probablement le point le plus intéressant du pipeline.

Le résumé de transaction est du **vocabulaire comptable brut** : des montants,
des noms de sociétés, des numéros de pièce. Le corpus, lui, est écrit en
**vocabulaire juridique** : « rémunérations allouées à des tiers », « règlement
des transactions en espèces ». Chercher l'un avec l'autre noie le signal.

Mais la vraie découverte est ailleurs. Une écriture peut porter **plusieurs
faits fiscalement significatifs à la fois** : un paiement en espèces **et** un
tiers sans ICE **et** une nature de dépense particulière. Une requête unique qui
les combine retrouve **moins bien chacun** qu'une requête focalisée sur un seul.

Le prompt l'impose explicitement :

```
NE MÉLANGE JAMAIS deux faits différents dans la même requête — une requête qui
combine plusieurs sujets retrouve moins bien chaque sujet individuellement
qu'une requête focalisée sur un seul.
```

Et la docstring porte la mesure :

> **Article 193 passe du 41e rang (requête combinée) au 1er-2e rang (requête
> focalisée espèces seule).**

Un article au 41e rang est hors de tout `top_k` raisonnable : l'anomalie était
purement et simplement **invisible**. C'est le genre de chiffre à citer à
l'oral, parce qu'il montre que le réglage du RAG n'est pas cosmétique.

Les 1 à 3 requêtes sont ensuite exécutées séparément, leurs résultats fusionnés
et **dédupliqués par référence**, puis triés par score :

```python
for q in reformulated_queries:
    for m in store.search(q, top_k=10):
        if m.reference not in seen_refs:
            seen_refs.add(m.reference)
            merged.append(m)
merged.sort(key=lambda m: m.score, reverse=True)
candidates = merged[:top_k_legal]
```

#### c) Le filtrage de pertinence — la précision, après le rappel

Le retrieval ramène 15 candidats. Beaucoup partagent du vocabulaire fiscal avec
l'écriture sans que leurs conditions d'application soient réunies. Le prompt de
filtrage est précis sur ce qu'il faut vérifier :

```
- secteur d'activité concerné
- nature de l'opération ou du bien/service
- seuils de montant éventuels
- qualité des parties (assujetti, résident, etc.)
```

et pose la règle qui évite le faux positif le plus courant :

```
Ne suppose jamais qu'une condition est réunie si rien dans l'écriture ne
l'indique explicitement.
```

Sans elle, le LLM « complète » : il suppose que l'entreprise est assujettie,
que le bien relève du secteur visé, et déclare pertinent un article qui ne
s'applique pas.

**Le matching par index, avec repli positionnel.** Les articles sont numérotés
`ARTICLE 0`, `ARTICLE 1`… et le LLM doit renvoyer l'`index` correspondant :

```python
idx = e.get("index")
if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
    print(f"[RAG-DEBUG] ... index absent/invalide, repli sur la position brute.")
    idx = pos
```

Se fier uniquement à la **position** dans le tableau de réponse casserait
silencieusement si le LLM en sautait un — on attribuerait la justification de
l'article 5 à l'article 4, et le décalage se propagerait. Se fier uniquement à
l'`index` déclaré casserait si le champ manquait. Les deux ensemble : le
mécanisme fiable d'abord, le repli ensuite, et une trace dans les logs quand le
repli sert.

#### d) L'analyse finale et le budget de caractères

```python
per_article_budget = max(500, AUDIT_LEGAL_CONTEXT_CHAR_BUDGET // max(1, len(relevant_articles)))
```

Le budget total (6 000 caractères) est **réparti entre les articles retenus**
plutôt que tronqué à une longueur fixe par article. Avec un cutoff fixe, huit
articles retenus feraient exploser le contexte ; avec un budget réparti, on
garde un extrait de chacun. Le plancher de 500 caractères évite qu'un article
soit réduit à une phrase inexploitable.

La justification produite au filtrage est **réinjectée** dans le contexte
juridique :

```python
f"[Pertinence retenue : {justifications.get(m.reference, '')}]"
```

Le modèle d'analyse sait ainsi *pourquoi* l'article lui a été présenté. C'est un
passage de témoin entre les deux étapes, qui évite qu'il refasse le raisonnement
de sélection au lieu de faire l'analyse de fond.

#### e) Le garde-fou anti-hallucination

```python
valid_refs = {_normalize_ref(m.reference) for m in relevant_articles}
if _normalize_ref(reference_cgi) not in valid_refs:
    fallback_ref = relevant_articles[0].reference
    print(f"[RAG] ... référence non reconnue parmi les sources fournies, remplacée (garde-fou).")
    reference_cgi = fallback_ref
```

`reference_cgi` est du **texte libre renvoyé par le LLM**. Rien ne garantit
qu'elle corresponde à un article réellement fourni : un modèle peut très bien
citer de mémoire un article plausible qui n'était pas dans le contexte.

On ne fait donc **pas confiance au prompt seul**. La référence est vérifiée
contre l'ensemble des articles effectivement présentés, et remplacée si elle
n'y figure pas. C'est ce garde-fou qui est réutilisé ailleurs dans le produit
(le filtrage des citations du workflow de correction, flux 16, applique la même
logique).

#### f) Trois issues, et pourquoi la troisième existe

Le prompt d'audit impose exactement trois `status` :

| `status` | Signification | Traitement |
|---|---|---|
| `anomalie` | Risque identifié et fondé sur un article | Devient un finding, puis une `AlerteRisque` |
| `conforme` | L'écriture respecte les textes disponibles | Rien n'est produit |
| `contexte_insuffisant` | Impossible de conclure | Remonte dans `inconclusive[]` |

La troisième issue est la traduction directe d'une exigence du cahier des
charges : *« Anti-hallucination = cœur produit : zones grises renvoyées à
l'expert »*.

Et le code insiste, dans les commentaires comme dans les noms de variables, sur
un point : **`inconclusive` ne doit jamais être silencieusement confondu avec
`conforme`**. Une écriture qu'on n'a pas su juger n'est pas une écriture sans
risque. Le frontend les affiche dans deux blocs distincts.

#### g) Échec technique ≠ résultat d'audit

C'est la distinction la plus subtile du module, et elle porte tout le reste.
`_audit_single_move` retourne un triplet :

```python
-> tuple[dict | None, bool, dict | None]
   #  finding   technical_failure  inconclusive
```

Un `None` en première position peut signifier trois choses très différentes :
« conforme », « pas concluant », ou « le LLM n'a pas répondu ». Les confondre
reviendrait à présenter une écriture **non auditée** comme une écriture
**sans risque**.

D'où la passe de retry, sur les seules écritures en échec technique :

```python
time.sleep(RETRY_PAUSE_SECONDS)
for idx, move in enumerate(failed_moves):
    ...
if technical_failures:
    print(f"ATTENTION : {len(technical_failures)} écriture(s) toujours non auditée(s) après retry "
          f"(échec technique persistant), PAS parce qu'elles sont conformes ou sans risque")
```

Et ce qui reste en échec après retry **remonte jusqu'à l'interface**, dans un
bandeau de vigilance distinct. Le cabinet doit savoir que trois écritures n'ont
pas été analysées — un audit silencieusement partiel est pire qu'un audit qui
échoue franchement.

#### h) Deux modèles, choisis par tâche

| Tâche | Modèle | Pourquoi |
|---|---|---|
| Reformulation de requêtes | `llama-3.1-8b-instant` | Tâche simple, tourne 1 fois par écriture |
| Filtrage de pertinence | `llama-3.1-8b-instant` | **Gros volume d'entrée** (15 articles par appel), raisonnement modéré |
| Analyse de conformité | `llama-3.3-70b-versatile` | Le jugement de fond, seul endroit qui a besoin du meilleur raisonnement |

Le quota TPM du tier gratuit Groq est serré sur le 70B (~6-12K/min) et bien
plus généreux sur le 8B (14 400 requêtes/jour). Le filtrage consomme beaucoup de
tokens en **entrée** sans exiger le meilleur raisonnement : c'est exactement le
cas d'usage du modèle léger. Faire tourner le 70B sur le filtrage épuiserait le
quota avant même d'atteindre l'analyse.

S'y ajoutent un `time.sleep(1.2)` entre appels et un **fallback OpenRouter** si
Groq échoue, avec backoff basé sur le `Retry-After` réel quand l'API le fournit.

#### i) Le verrou global

```python
_audit_lock = threading.Lock()

def run_ai_rag_audit(odoo_data, top_k_legal=CANDIDATE_TOP_K):
    with _audit_lock:
        return _run_ai_rag_audit_locked(odoo_data, top_k_legal)
```

Un verrou **global au processus**, pas par dossier : deux audits simultanés,
même sur deux dossiers différents, se disputeraient le même quota LLM et se
feraient mutuellement rate-limiter. Sérialiser est ici plus rapide que
paralléliser.

À signaler comme limite : ce verrou ne protège que dans un seul processus. Avec
plusieurs workers uvicorn, il faudrait un verrou distribué (Redis, ou un
`SELECT … FOR UPDATE` sur une ligne de contrôle).

#### j) Le périmètre des écritures auditées

```python
auditable_moves = [m for m in moves if m.get("move_type") in ("in_invoice", "entry")]
```

Factures **fournisseur** et opérations diverses. Les factures clients
(`out_invoice`) sont exclues : le risque fiscal analysé ici est celui de la
**déductibilité** (charges, TVA récupérable), qui ne concerne pas les ventes.
C'est un choix de périmètre assumé, pas un oubli — les anomalies sur ventes
(TVA collectée, facturation irrégulière) relèveraient d'un autre jeu de règles.

---

### 4. Flux complet des données

```
odoo_data {company, partners, moves, lines}   (Odoo OU import CSV — flux 15)
     |
     v
run_ai_rag_audit()   [verrou global : un seul audit a la fois]
     |
     +-- auditable_moves = move_type dans (in_invoice, entry)
     |
     v
POUR CHAQUE ECRITURE  --> _audit_single_move()
     |
     |  1. _build_transaction_summary()
     |         piece, date, journal, tiers + ICE ou "NON RENSEIGNE",
     |         montant TTC, lignes avec mode de reglement
     |
     |  2. _reformulate_queries()          [8B]
     |         1 a 3 requetes FOCALISEES, un fait fiscal chacune
     |         (mesure : Art. 193 du 41e rang au 1er-2e)
     |              |
     |              v
     |     store.search(q, top_k=10) pour chaque requete
     |     fusion + deduplication par reference + tri par score
     |              |
     |              v
     |     candidats (max 15)   <-- AUCUN seuil de similarite
     |              |
     |         vide ? --> inconclusive (resultat reel, pas un echec)
     |
     |  3. _filter_relevant_articles()     [8B]
     |         conditions d'application reunies ? oui / non + justification
     |         matching par index declare, repli sur la position
     |              |
     |         echec technique ? --> retry
     |         aucun retenu ?     --> inconclusive
     |              |
     |              v
     |  4. Analyse de conformite            [70B]
     |         contexte = articles retenus, budget 6000 car. REPARTI
     |         + justification de pertinence reinjectee
     |              |
     |              v
     |     status = anomalie | conforme | contexte_insuffisant
     |              |
     |     GARDE-FOU : reference_cgi appartient-elle aux articles fournis ?
     |                 sinon --> remplacee par relevant_articles[0]
     |              |
     v              v
findings[]    inconclusive[]    failed_moves[]
                                     |
                                     v
                          PASSE DE RETRY (apres 5 s)
                                     |
                                     v
                          technical_failures[]  --> bandeau de vigilance
     |
     v
tri par severite (rouge, orange, vert)
     |
     v
_execute_audit()  --> reconciliation par cle metier (flux 14)
                      AlerteRisque + CitationRisque persistees
```

---

### 5. Lien avec le frontend

| Étape | Composant | Appel | Endpoint | JSON reçu | Impact UI |
|---|---|---|---|---|---|
| Audit au chargement | `App.jsx` → `loadDashboard()` | `fetchAuditRun()` | `POST /dossiers/{id}/audit/run` | `{nb_anomalies, findings[], technical_failures[], inconclusive[]}` | Alimente `AuditPage` et `DashboardPage` |
| Relance forcée | `AuditPage.jsx` | `runAudit()` | `POST .../audit/run?force=true` | idem | Ignore le cache par hash |
| Anomalies | `AuditPage.jsx` → `FindingCard` | — | — | `findings[]` | Cartes triées par gravité, pastilles d'articles cliquables |
| Écritures non concluantes | `AuditPage.jsx` | — | — | `inconclusive[]` | Bloc **distinct** — jamais mélangé aux conformes |
| Échecs techniques | `AuditPage.jsx` | — | — | `technical_failures[]` | Bandeau de vigilance : « non auditées, PAS conformes » |

Le frontend impose un **timeout de 15 minutes** côté navigateur
(`AUDIT_TIMEOUT_MS`) avec un message explicite : le calcul continue côté serveur
et son résultat sera enregistré même si le client abandonne. L'audit est
synchrone et peut réellement dépasser 5 minutes sur plusieurs dizaines
d'écritures — deux appels LLM par écriture, plus les retries.

---

### 6. Pourquoi cette architecture ?

**RAG-only plutôt qu'un moteur de règles.**
Alternative écartée, et effectivement retirée du projet : `compliance_checker.py`,
avec ses seuils codés en dur. Rejetée pour une raison de fond — ses alertes
portaient des `reference_cgi` jamais vérifiées contre le corpus versionné et
aucun `rag_sources`, donc aucune `CitationRisque`. **Elles avaient l'air
sourcées sans l'être.** Un moteur de règles doit aussi être maintenu à chaque
loi de finances, alors que le RAG suit le corpus.

**Filtrage LLM plutôt qu'un seuil de similarité.**
Alternative écartée : ne garder que les candidats au-dessus d'un score de
cosinus. Rejetée à cause de l'**anisotropie** des embeddings juridiques : les
scores se tassent dans une bande étroite, un seuil calibré sur un cas en fait
rater un autre. Un LLM qui lit l'article et l'écriture juge sur les
**conditions d'application**, ce qu'aucun score ne mesure.

**Retrieval large puis filtrage, plutôt qu'un retrieval précis directement.**
On cherche 15 candidats pour n'en garder que 2 ou 3. C'est délibéré : en RAG,
un article manqué au retrieval est définitivement perdu — aucune étape suivante
ne peut le rattraper. On privilégie donc le **rappel** en amont et on rétablit
la **précision** en aval, là où c'est rattrapable.

**Plusieurs requêtes focalisées plutôt qu'une requête riche.**
Contre-intuitif, et c'est la mesure qui tranche : une requête combinant
« rémunération non déclarée » et « paiement en espèces » faisait tomber
l'article 193 au 41e rang. Séparées, chaque requête le remonte en tête.

**Un modèle léger pour le filtrage, un lourd pour l'analyse.**
Le filtrage consomme beaucoup de tokens en entrée sans exiger le meilleur
raisonnement. Utiliser le 70B partout épuiserait le quota TPM avant l'analyse
de fond.

**Trois issues plutôt que deux.**
Sans `contexte_insuffisant`, le LLM serait forcé de trancher entre « anomalie »
et « conforme » même quand il n'a pas de quoi conclure — et il choisirait
« conforme », l'option qui ne demande pas de justification. La zone grise doit
avoir un nom pour être remontée à l'expert.

**Échec technique remonté à l'utilisateur plutôt qu'avalé.**
Un audit silencieusement partiel donne l'illusion d'une couverture complète.
C'est la même logique que les lignes ignorées à l'import (flux 15) : ce qui n'a
pas été traité doit se voir.

---

### 7. Lien avec le cahier des charges

Répond au **module 3 — Détection erreurs & risques** : *« analyse des données au
regard du corpus : charges non déductibles, incohérences ; chiffrage de
l'exposition et priorisation »*
([`cahier-des-charges.md:36-38`](../cahier-des-charges.md#L36-L38)). Le chiffrage
est `amount_risk`, la priorisation est le tri par gravité.

Répond surtout à la **contrainte technique la plus structurante** : *« IA via
API d'un LLM (aucun modèle à entraîner) + RAG sur corpus fiscal marocain
structuré et versionné par exercice — réponses uniquement sourcées »*
([`cahier-des-charges.md:50-52`](../cahier-des-charges.md#L50-L52)). Le mot
**« uniquement »** est ce que le garde-fou anti-hallucination fait respecter au
niveau du code, pas seulement du prompt.

Et à *« Anti-hallucination = cœur produit : zones grises renvoyées à l'expert »*
([`cahier-des-charges.md:57`](../cahier-des-charges.md#L57)) : c'est le statut
`contexte_insuffisant`, affiché dans un bloc distinct.

---

### 8. Ce que je dois retenir pour la soutenance

- **RAG-only** : aucune règle fiscale codée en dur. `compliance_checker.py` a été déprécié parce que ses alertes **avaient l'air sourcées sans l'être** — pas de `rag_sources`, donc aucune `CitationRisque`.
- **Aucun seuil de similarité** : anisotropie des embeddings juridiques, les scores se tassent. Le filtrage est sémantique, confié à un LLM qui juge les **conditions d'application**.
- Architecture en deux temps : **rappel large** (15 candidats) puis **précision** (filtrage). Un article manqué au retrieval est définitivement perdu ; un candidat en trop est rattrapable.
- La mesure à citer : une requête combinant deux faits fiscaux faisait tomber **l'Article 193 du 1er-2e au 41e rang**. D'où 1 à 3 requêtes **focalisées sur un seul fait chacune**.
- Garde-fou anti-hallucination : `reference_cgi` est du texte libre du LLM, **vérifiée contre les articles réellement fournis** et remplacée sinon. On ne fait pas confiance au prompt seul.
- **Trois issues** : anomalie / conforme / contexte_insuffisant. La troisième existe pour que la zone grise ne soit pas classée « conforme » par défaut.
- **Échec technique ≠ conforme.** Le triplet de retour distingue les trois cas, une passe de retry est faite, et ce qui échoue encore remonte dans un bandeau à l'écran.
- Deux modèles par économie de quota : **8B** pour reformulation et filtrage (gros volume d'entrée), **70B** pour le jugement de fond uniquement.
- Périmètre assumé : factures fournisseur et OD seulement. Le risque analysé est celui de la **déductibilité**, pas des ventes.

---

### 9. Questions probables du jury

**Pourquoi ne pas coder les règles fiscales en dur ? Ce serait plus fiable.**
Plus déterministe, oui ; plus fiable, non. Un moteur de règles doit être
maintenu à chaque loi de finances, et surtout — c'est ce qui a fait supprimer le
nôtre — il produisait des alertes portant des références jamais vérifiées contre
le corpus versionné. Elles avaient l'apparence d'alertes sourcées sans l'être,
à l'endroit du produit où c'est le plus grave.

**Comment évitez-vous que le LLM invente un article ?**
Trois barrières. Il ne voit que les articles réellement retrouvés dans le
corpus. Le filtrage écarte ceux dont les conditions d'application ne sont pas
réunies. Et la référence finale est **vérifiée par le code** contre la liste des
articles fournis : si elle n'y figure pas, elle est remplacée et l'événement est
journalisé.

**Pourquoi ne pas filtrer les résultats par un score de similarité minimal ?**
Parce que les embeddings de textes juridiques sont anisotropes : les scores se
concentrent dans une bande étroite, et un seuil calibré sur un cas en fait
manquer un autre. Surtout, un score mesure une proximité sémantique, pas si les
**conditions d'application** de l'article sont réunies — ce que seul un jugement
sur le contenu peut établir.

**Pourquoi plusieurs requêtes de recherche pour une seule écriture ?**
Parce qu'une écriture porte souvent plusieurs faits fiscaux à la fois, et qu'une
requête qui les combine dilue le signal. Mesuré : l'Article 193 passait du 1er-2e
rang au 41e quand la requête mélangeait paiement en espèces et rémunération de
tiers. Au 41e rang, l'anomalie est invisible.

**Que se passe-t-il si le LLM ne répond pas ?**
L'écriture est marquée en échec **technique**, distinct d'un résultat d'audit.
Une passe de retry est faite après 5 secondes ; ce qui échoue encore est affiché
au cabinet avec un message explicite : « non auditées, PAS parce qu'elles sont
conformes ».

**Le pipeline est-il lent ?**
Oui, et c'est assumé : deux appels LLM par écriture, plus une pause de 1,2 s
pour les quotas. Plusieurs minutes sur quelques dizaines d'écritures. C'est
pourquoi le résultat est mis en cache sur un hash des données comptables, et
pourquoi le frontend prévient que le calcul continue côté serveur même s'il
abandonne l'attente.

**Pourquoi n'auditez-vous pas les factures clients ?**
Choix de périmètre. Le risque analysé est celui de la déductibilité (charges,
TVA récupérable), qui concerne les achats. Les anomalies sur ventes relèveraient
d'un autre jeu de critères, non traité dans ce MVP.

---

### 10. Étapes de test dans l'application

1. Onglet **Sources de données** → **Mode démonstration** → scénario
   **Commerce** → *Charger les données de démonstration*.
2. Onglet **Audit fiscal** : l'analyse démarre. Compter plusieurs minutes
   (deux appels LLM par écriture).
3. Vérifier les trois blocs distincts en haut de page :
   - les compteurs par gravité (critique / modéré / faible),
   - le bandeau **écritures non concluantes** s'il y en a,
   - le bandeau **échecs techniques** le cas échéant — bien lire le libellé,
     il dit « non auditées, PAS conformes ».
4. Déplier une carte d'anomalie et vérifier la chaîne complète :
   écriture auditée → **fondement légal cliquable** → constat → recommandation.
5. Cliquer sur une pastille d'article : le texte de loi du corpus s'affiche.
   C'est la démonstration de la traçabilité de bout en bout.
6. Charger le scénario **Conforme** : l'audit doit produire **0 anomalie**.
   C'est le seul moyen de vérifier que le pipeline ne génère pas de faux
   positifs par construction.
7. Charger le scénario **Services** : les anomalies portent sur d'autres articles
   (151, 146), ce qui montre que la détection suit le contenu et non un scénario
   figé.

Dans les logs du backend, suivre la trace complète d'une écriture :

```
[RAG] FACT-2026-002 — 15 candidat(s) -> 2 jugé(s) pertinent(s) (Article 193, Article 145, ...)
[RAG-DEBUG] FACT-2026-002 — brut du LLM : [{"index":0,"reference":"Article 193","pertinent":true,...}]
```

Pour tester le retrieval seul, sans audit : `backend/test_rag.py` interroge
directement le vectorstore.


---

## 14. Identité stable des alertes — clé métier et cycle de vie

### 1. Vue d'ensemble

Ce flux n'est pas une fonctionnalité visible. C'est une **correction
structurelle** sans laquelle deux fonctionnalités entières (le classement des
alertes, le workflow de correction) ne pouvaient tout simplement pas exister.

Le problème, en une phrase : **l'audit RAG effaçait la mémoire du produit à
chaque exécution.**

`_execute_audit()` supprimait toutes les `AlerteRisque` du dossier puis les
recréait avec des `id` neufs à chaque fois que les données comptables
changeaient. Conséquence : si un collaborateur classait une alerte comme
« traitée », l'information disparaissait à la prochaine synchronisation Odoo.
Et toute donnée humaine qu'on aurait voulu accrocher à une alerte — une
validation, un commentaire, une proposition de correction — était détruite
avant d'avoir servi.

La difficulté n'est pas d'arrêter de supprimer : sans identité, ne plus
supprimer produirait des **doublons** à chaque run. La vraie question, celle
qui structure tout ce flux, est :

> **Qu'est-ce qui fait que deux détections successives sont la *même*
> anomalie ?**

La réponse retenue : une anomalie est le couple **(écriture, fondement
légal)**. Tant que ce couple réapparaît d'un audit à l'autre, c'est la même
ligne — on la met à jour au lieu de la recréer, donc son `id` et son `statut`
survivent.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Rôle |
|---|---|---|
| `backend/app/models.py` | `class AlerteRisque` (docstring + 8 colonnes) | `cle_metier`, `actif`, et le contexte de l'écriture auditée |
| `backend/migrations/versions/e5a9c2d4f8b1_add_alerte_cle_metier.py` | migration | Colonnes + backfill non destructif + index unique |
| `backend/app/routes_dossiers.py` | `_cle_metier()` | Construit la clé `"{pièce}|{article normalisé}"` |
| `backend/app/routes_dossiers.py` | `_appliquer_finding()` | Recopie un finding **sans jamais toucher `id` ni `statut`** |
| `backend/app/routes_dossiers.py` | `_reecrire_citations()` | Supprime/recrée les `CitationRisque` (données dérivées) |
| `backend/app/routes_dossiers.py` | `_execute_audit()` | Réconciliation insert / update / désactivation |
| `backend/app/routes_dossiers.py` | `_alerte_to_dict()` | Forme **unique** du finding renvoyé au frontend |
| `backend/app/routes_dossiers.py` | `PATCH /dossiers/{id}/alertes/{alerte_id}` | Écrit enfin `StatutAlerte` |
| `backend/app/tenant_guard.py` | module entier | Contrôle d'accès factorisé (était dupliqué) |
| `backend/test_cle_metier.py` | script de vérification | 13 contrôles, dont la preuve que l'`id` survit |

---

### 3. Explication détaillée du code

#### a) La clé métier

```python
def _cle_metier(f: dict) -> str:
    odoo_path = f.get("odoo_path") or {}
    piece = f.get("invoice") or odoo_path.get("move_id") or "sans_piece"
    ref = _normalize_ref(f.get("reference_cgi") or "sans_reference")
    return f"{piece}|{ref}"[:160]
```

Trois décisions dans quatre lignes.

**On préfère le numéro de pièce (`invoice`) à l'identifiant technique
(`move_id`).** `FACT-2026-002` est lisible directement en base, et surtout il
est **stable à travers les sources** : le même exercice réimporté en CSV après
avoir été lu depuis Odoo garde ses numéros de pièce, pas ses identifiants
internes. C'est ce qui rend le flux 15 (import CSV) compatible avec les
corrections déjà validées.

**On réutilise `_normalize_ref` d'`ai_auditor.py`** plutôt que d'en écrire une
autre. « Article 106 », « article 106 » et « Art. 106 » doivent produire la
même clé ; deux implémentations de normalisation finiraient par diverger.

**On tronque à 160 caractères**, la taille de la colonne. Une troncature
silencieuse vaut mieux qu'une `DataError` en production sur une pièce au nom
inhabituellement long.

#### b) La réconciliation, cœur du flux

```python
incoming: dict[str, dict] = {}
for f in findings:
    cle = _cle_metier(f)
    precedent = incoming.get(cle)
    if precedent is None or _SEVERITY_RANK.get(f.get("severity"), 0) > _SEVERITY_RANK.get(precedent.get("severity"), 0):
        incoming[cle] = f
```

**Déduplication d'abord.** Le LLM audite pièce par pièce et peut produire deux
findings identiques. L'index unique `(dossier_id, cle_metier)` l'interdit en
base ; on tranche donc ici, en gardant **le plus grave**, plutôt que de laisser
remonter une `IntegrityError` qui invaliderait toute la transaction.

```pythoni
connues = {a.cle_metier: a for a in existing if a.cle_metier}

for cle, f in incoming.items():
    alerte = connues.get(cle)
    if alerte is None:
        alerte = AlerteRisque(id=uuid.uuid4(), dossier_id=dossier_id, cle_metier=cle,
                              statut=StatutAlerte.ouverte, niveau_risque=NiveauRisque.faible)
        db.add(alerte)
    _appliquer_finding(alerte, f, new_hash)
    db.flush()
    _reecrire_citations(db, alerte)
```

Trois cas, **un seul touche à quelque chose de destructif** :

| Cas | Action | Ce qui est préservé |
|---|---|---|
| Clé présente avant **et** après | `UPDATE` des champs mutables | `id`, `statut`, tout ce qui y est rattaché |
| Clé nouvelle | `INSERT` | — |
| Clé disparue | `actif = False` | **tout**, y compris l'historique |

```python
for cle, alerte in connues.items():
    if cle not in incoming:
        alerte.actif = False
        alerte.hash_donnees = new_hash
```

La ligne `alerte.hash_donnees = new_hash` sur une alerte **désactivée** n'est
pas cosmétique. La condition de cache est
`all(a.hash_donnees == new_hash for a in existing)` : si les lignes
désactivées gardaient l'ancien hash, la condition serait fausse à jamais et
l'audit LLM se relancerait à chaque appel du dashboard. Un oubli d'une ligne
ici transforme un cache en gouffre à quota Groq.

#### c) `_appliquer_finding` — ce qu'il ne fait pas

```python
def _appliquer_finding(alerte, f, new_hash):
    alerte.titre = f.get("title", "Anomalie détectée")
    ...
    alerte.actif = True
```

La fonction écrit une quinzaine de champs. Elle ne touche **jamais** `id` ni
`statut`. C'est écrit dans sa docstring, parce que c'est exactement l'invariant
que toute la migration sert à protéger : ce sont les deux champs porteurs de
décision humaine.

#### d) Le bug latent corrigé au passage

`_alerte_to_dict()` ne renvoyait ni `recommendation`, ni `invoice`, ni
`partner`, ni `date`, ni `odoo_path`. Sur le **chemin de cache** (données
inchangées), `FindingCard` perdait donc silencieusement les blocs « Écriture
comptable auditée » et « Recommandation ». Le même écran affichait plus ou
moins d'informations selon qu'on venait de relancer l'audit ou non.

La correction n'est pas d'ajouter les champs manquants : c'est de faire passer
**les deux chemins par la même fonction**. La divergence n'est plus corrigée,
elle est devenue **inatteignable**.

#### e) La limite assumée

`reference_cgi` est produite par le LLM. Il est déjà contraint par le garde-fou
anti-hallucination d'`ai_auditor` (obligé de citer un article réellement
retrouvé), mais un re-run peut retenir l'article 146 au lieu du 145 sur la même
écriture. La clé change alors, et l'alerte réapparaît comme neuve.

**C'est le comportement voulu, pas un défaut toléré.** Si le fondement légal
change, une correction validée sur l'ancien fondement n'est plus nécessairement
valable juridiquement. Mieux vaut re-proposer que reporter en silence une
validation humaine sur une autre base légale.

---

### 4. Flux complet des données

```
Données comptables modifiées (Odoo ou import)
     │
     ▼
POST /dossiers/{id}/audit/run
     │
     ▼
_execute_audit(db, dossier_id, data, force)
     │
     ├─ new_hash = sha256(data)
     │
     ├─ existing = SELECT * FROM alerte_risque WHERE dossier_id = ...
     │       (actives ET désactivées : on a besoin des deux pour réconcilier)
     │
     ├─ CACHE : tous les hash == new_hash et pas de force ?
     │       └─► OUI : return [_alerte_to_dict(a) for a in existing if a.actif]
     │                 (aucun appel LLM)
     │
     ├─ NON : run_ai_rag_audit(data)  ──► findings[]
     │
     ├─ incoming = {cle_metier: finding}   (déduplication, plus grave gagne)
     ├─ connues  = {cle_metier: AlerteRisque}
     │
     │   pour chaque clé de incoming :
     │       ┌── connue ?  ──OUI──► UPDATE champs mutables, actif=True
     │       │                      (id et statut INTOUCHÉS)
     │       └────────────  NON──► INSERT (uuid neuf, statut=ouverte)
     │                             puis _reecrire_citations()
     │
     │   pour chaque clé de connues absente d'incoming :
     │       └──► actif=False, hash_donnees=new_hash   (PAS de DELETE)
     │
     ▼
db.commit()
     │
     ▼
[_alerte_to_dict(a) for a in alertes_actives]   ← même forme que le cache
     │
     ▼
AuditPage → FindingCard (avec écriture auditée + recommandation)
```

---

### 5. Lien avec le frontend

| Étape | Composant | Appel | Endpoint | JSON reçu | Impact UI |
|---|---|---|---|---|---|
| Chargement du dashboard | `App.jsx` → `loadDashboard()` | `fetchAuditRun()` | `POST /dossiers/{id}/audit/run` | `{findings[], technical_failures[], inconclusive[]}` | Remplit `findings`, alimente `AuditPage` et `DashboardPage` |
| Relance forcée | `AuditPage.jsx` → bouton « Relancer l'analyse » | `runAudit()` | `POST .../audit/run?force=true` | idem | Ignore le cache, réconcilie sur données identiques |
| Affichage d'une anomalie | `FindingCard.jsx` | — | — | `{id, cle_metier, title, severity, statut, invoice, partner, date, recommendation, odoo_path, reference_cgi, rag_sources}` | Blocs « Écriture auditée » et « Recommandation » présents **quel que soit le chemin** |
| Classement d'une alerte | *(à brancher)* | — | `PATCH /dossiers/{id}/alertes/{alerte_id}` | alerte mise à jour | Le statut survit désormais au ré-audit |
| Historique complet | *(à brancher)* | — | `GET /dossiers/{id}/alertes?inclure_inactives=true` | alertes actives + désactivées | Permet de justifier qu'une anomalie a été corrigée |

---

### 6. Pourquoi cette architecture ?

**Clé métier déterministe plutôt qu'UUID régénéré.**
Alternative écartée : garder la suppression/recréation et stocker l'état humain
dans une table séparée indexée par… quoi ? Il aurait fallu de toute façon une
identité stable. Le problème n'était pas *où* stocker l'état, mais *à quoi
l'accrocher*.

**Désactivation (`actif = False`) plutôt que suppression.**
Alternative écartée : supprimer les anomalies qui ne sont plus détectées.
Rejetée pour deux raisons. D'abord l'**historique** : pouvoir montrer qu'une
anomalie a existé puis a disparu est exactement ce qu'un cabinet doit produire
face à un contrôle. Ensuite l'**intégrité référentielle** : une proposition de
correction pointe vers une alerte ; supprimer l'alerte rendrait la proposition
orpheline ou la ferait disparaître en cascade, alors qu'elle documente une
décision humaine qui, elle, a bien eu lieu.

**Index unique `(dossier_id, cle_metier)` plutôt qu'une simple convention de
code.** Sans lui, « une clé = une ligne » ne serait qu'une intention. Avec lui,
c'est Postgres qui le garantit — y compris face à une exécution concurrente que
le verrou applicatif `_lock_for()` ne couvrirait pas (deux processus uvicorn).

**Backfill `'legacy_' || id::text` plutôt qu'un `DELETE` dans la migration.**
Les alertes existantes n'ont pas de `move_ref` persisté (les colonnes de
contexte arrivent avec cette migration), on ne peut donc pas leur recalculer
une vraie clé. Leur donner une clé dérivée de leur `id` les rend uniques sans
rien détruire ; elles seront naturellement remplacées au prochain audit forcé.
**Une migration qui supprime des données client pour se simplifier la vie est
une migration qu'on ne peut pas rejouer en production.**

**Extraction de `tenant_guard.py`.** Le contrôle d'accès par dossier était
dupliqué mot pour mot entre `routes_dossiers.py` et `routes_simulation.py`. Le
dupliquer une troisième fois pour les nouveaux routeurs aurait fini par
produire une divergence silencieuse **sur un contrôle d'accès** — précisément
l'endroit où une divergence ne se voit pas jusqu'au jour où elle se voit.

---

### 7. Lien avec le cahier des charges

Indirectement mais fondamentalement lié au **module 3 — Détection erreurs &
risques** : *« chiffrage de l'exposition et priorisation »*
([`cahier-des-charges.md:36-38`](../cahier-des-charges.md#L36-L38)). Priorisér
suppose de pouvoir dire « celle-ci est traitée, celle-là non » — donc que le
statut survive. Sans ce flux, la priorisation se réinitialisait à chaque
synchronisation.

C'est aussi le **prérequis technique** du workflow agentique promis par les
règles d'architecture du projet (« proposition + validation humaine ») : une
validation qui ne survit pas au ré-audit n'est pas une validation.

---

### 8. Ce que je dois retenir pour la soutenance

- Le problème : l'audit **effaçait la mémoire du produit** à chaque exécution — statut « traitée » et toute donnée humaine détruits à la synchro suivante.
- « Ne plus supprimer » n'était pas la solution : ça produirait des doublons. La vraie question était **qu'est-ce qui fait que deux détections sont la même anomalie**.
- Réponse : une anomalie = le couple **(écriture, fondement légal)**, soit `FACT-2026-002|article 193`.
- Trois cas, un seul destructif : présente→`UPDATE` (id et statut intouchés), nouvelle→`INSERT`, disparue→`actif=False` sans `DELETE`.
- Le numéro de pièce plutôt que l'ID technique, **parce qu'il survit à un changement de source** (Odoo → CSV).
- Bug latent corrigé : le chemin de cache perdait `recommendation`/`invoice`/`date`/`odoo_path`. Les deux chemins passent maintenant par la même fonction — la divergence est devenue **inatteignable**, pas seulement corrigée.
- Limite assumée : la clé dépend d'une sortie de LLM. Si le fondement légal change, l'alerte réapparaît comme neuve — **c'est voulu**, une correction validée sur l'ancien article n'est plus forcément valable.
- Le test `test_cle_metier.py` prouve les trois invariants : `id` stable, `statut` préservé, aucune ligne supprimée.

---

### 9. Questions probables du jury

**Pourquoi ne pas simplement stocker l'état dans une table à part ?**
Il aurait fallu l'indexer par quelque chose. Le problème n'était pas *où*
stocker l'état humain, mais *à quoi l'accrocher* : sans identité stable,
aucune table externe ne peut retrouver son alerte après un ré-audit.

**Votre clé dépend d'une sortie de LLM, elle n'est donc pas fiable ?**
Elle est contrainte par le garde-fou anti-hallucination : le LLM ne peut citer
qu'un article réellement retrouvé par le RAG. Un changement d'article reste
possible, et fait réapparaître l'alerte comme neuve — comportement souhaité,
puisqu'une correction validée sur l'article 145 n'est pas transposable telle
quelle à l'article 146.

**Que se passe-t-il si deux findings produisent la même clé ?**
Ils sont dédupliqués en amont, en gardant le plus grave. C'est nécessaire parce
que l'index unique le refuserait en base, et qu'une `IntegrityError` invaliderait
toute la transaction d'audit.

**Pourquoi garder les alertes désactivées plutôt que les supprimer ?**
Pour l'historique (prouver qu'une anomalie a été corrigée) et pour l'intégrité
référentielle (une proposition de correction pointe dessus, et elle documente
une décision humaine qui a réellement eu lieu).

**Le cache ne risque-t-il pas de masquer une nouvelle anomalie ?**
Le cache est clé sur un hash SHA-256 de l'intégralité des données comptables.
Toute modification, même d'un centime, change le hash et déclenche un audit
complet.

---

### 10. Étapes de test dans l'application

1. Charger un dossier avec le scénario de démonstration `commerce`
   (onglet **Sources de données**), puis ouvrir **Audit fiscal**.
2. Noter l'identifiant d'une anomalie (visible via l'API, ou en base :
   `SELECT id, cle_metier, statut FROM alerte_risque`).
3. Cliquer sur **Relancer l'analyse** (`force=true`).
4. Vérifier en base que **l'`id` est inchangé** pour la même `cle_metier`.
5. Passer l'alerte en `traitee` :
   `PATCH /dossiers/{id}/alertes/{alerte_id}` avec `{"statut": "traitee"}`.
6. Relancer l'analyse une nouvelle fois → le statut vaut toujours `traitee`.
7. Recharger le scénario `conforme` (données différentes) → les alertes
   précédentes passent `actif = false` **sans être supprimées**
   (`SELECT count(*) FROM alerte_risque WHERE dossier_id = ...` ne diminue pas).

Ou, en une commande depuis `backend/` : `python test_cle_metier.py`.

---

## 15. Ingestion élargie — connecteurs, import CSV, réconciliation

### 1. Vue d'ensemble

Jusqu'ici, Nisab ne savait lire qu'Odoo. Un cabinet qui tient ses dossiers sous
Sage, sous Ciel, ou simplement sur un tableur, ne pouvait pas utiliser le
produit. Le module 1 du cahier des charges demande pourtant explicitement
« connexion logiciel comptable **+ import** (balance, factures, déclarations),
réconciliation, détection des pièces manquantes ».

Ce flux fait deux choses distinctes :

1. **Rendre le moteur d'audit indépendant de sa source.** Une interface commune
   (`AccountingConnector`) et trois implémentations : Odoo, fichier CSV/Excel,
   et Sage — ce dernier volontairement non implémenté, pour une raison
   documentée plus bas.
2. **Détecter les obligations déclaratives non honorées.** Croiser le
   calendrier fiscal légal avec les traces comptables disponibles pour dire
   « la TVA de mars était due le 20 avril, aucune trace de dépôt ni de
   paiement ».

La preuve que le premier point est atteint n'est pas « le CSV se lit », c'est
**« le moteur d'audit ne sait pas qu'il ne parle plus à Odoo »** : aucune ligne
d'`ai_auditor.py` n'a été modifiée.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Rôle |
|---|---|---|
| `backend/app/connectors/base.py` | `AccountingConnector` (ABC), `ConnectorError` | Le contrat + le schéma pivot documenté champ par champ |
| `backend/app/connectors/odoo_connecteur.py` | `OdooAccountingConnector` | Adaptateur mince autour de l'existant |
| `backend/app/connectors/fichier_connecteur.py` | `FichierAccountingConnector`, `MODELE_CSV` | Lecture CSV/Excel vers le schéma pivot |
| `backend/app/connectors/sage_connecteur.py` | `SageAccountingConnector` | **Stub explicite**, non implémenté |
| `backend/app/connectors/__init__.py` | `get_connector()` | Fabrique par `TypeConnexion` |
| `backend/app/reconciliation.py` | `rapprochement_declaratif()` | Obligations échues sans trace |
| `backend/app/tax_calendar.py` | `nb_months_back`, `detect_tax_payment_months()`, `paiement_detecte()` | Horizon arrière + détection par catégorie |
| `backend/app/routes_ingestion.py` | 4 routes | Import, modèle, état Sage, réconciliation |
| `frontend/src/components/ingestion/ImportFichierCard.jsx` | carte d'import | Dépôt de fichier + retour détaillé |
| `frontend/src/components/calendar/ReconciliationBanner.jsx` | bandeau | Obligations manquantes, dépliable |
| `backend/test_import_fichier.py` | 22 contrôles | Dont « l'auditeur consomme le CSV sans modification » |

---

### 3. Explication détaillée du code

#### a) La décision structurante : ne pas inventer de schéma pivot

La tentation évidente était de définir un modèle de données « neutre », puis
d'écrire un adaptateur Odoo vers ce modèle. **On ne l'a pas fait**, et c'est le
point à défendre.

Le schéma pivot **est déjà le dict que produit Odoo** :
`{company, partners, moves, lines, source}`. `ai_auditor.py`,
`tax_calendar.py` et `dashboard_summary()` le consomment tous les trois.
Inventer un format neutre aurait obligé à réécrire ces trois consommateurs —
c'est-à-dire tout le moteur d'audit — sans qu'aucun utilisateur y gagne quoi
que ce soit.

La dette assumée : le vocabulaire du pivot est celui d'Odoo (`move_type`,
`amount_total`, couples `[id, libellé]` de la convention many2one). C'est une
**dette de nommage, pas une dette de conception**, et elle est documentée en
tête de `base.py` plutôt que subie.

#### b) L'identifiant déterministe

```python
def _identifiant_stable(valeur: str) -> int:
    return (int(hashlib.sha1(valeur.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF) or 1
```

Un compteur (1, 2, 3…) aurait été plus simple, mais dépendrait de **l'ordre des
lignes du fichier** : deux exports du même exercice triés différemment
donneraient des identifiants différents pour la même pièce, et la clé métier du
flux 14 se détacherait de ses corrections validées. Le hachage rend l'identité
**intrinsèque à la pièce**, pas à la façon dont on l'a lue.

Le masque `& 0x7FFFFFFF` est un bug attrapé par le test. L'`INTEGER` de
Postgres est **signé** et plafonne à 2 147 483 647 ; prendre les 32 bits bruts
du hachage produisait une valeur trop grande environ une fois sur deux. L'échec
ne se serait vu qu'à l'écriture d'`alerte_risque.move_id`, sur certaines pièces
seulement — donc de façon apparemment aléatoire, le pire type de bug à
diagnostiquer.

#### c) Tolérance aux fichiers réels

```python
except ValueError as exc:
    self.nb_lignes_ignorees += 1
    if len(self.warnings) < 25:
        self.warnings.append(f"Ligne {numero} ignorée — {exc}")
    continue
```

Un export comptable réel contient des lignes de total, des séparateurs, des
dates au mauvais format. Refuser le fichier entier à cause de trois lignes
serait inutilisable pour un comptable qui en a 800. On collecte, on importe le
reste, **et on le dit** — l'interface affiche les lignes écartées, parce qu'un
import silencieusement partiel produirait un audit incomplet que personne ne
saurait interpréter.

Le parseur tolère aussi « 1 200,50 », « 1.200,50 », JJ/MM/AAAA, les dates
natives d'Excel, et détecte automatiquement le séparateur (virgule,
point-virgule ou tabulation — les exports français utilisent souvent le
point-virgule).

#### d) L'ICE manquant vaut `False`, pas chaîne vide

```python
"vat": ice or False,
```

C'est ce que renvoie Odoo pour un champ vide, et `ai_auditor` teste la valeur
telle quelle pour signaler un ICE manquant — qui est un **risque fiscal réel**
(Art. 145 CGI). Une chaîne vide passerait le test de vérité de la même façon,
mais la cohérence de type avec la source Odoo évite qu'un futur `is False`
diverge selon la provenance des données.

#### e) Le connecteur Sage : le stub est le livrable honnête

`SageAccountingConnector.test_connection()` renvoie
`{"ok": False, "untested": True, "message": ...}` — **ni panne, ni succès**.

Écrire du SQL ODBC jamais exécuté contre une vraie base Sage aurait produit du
code d'apparence fonctionnelle, indémontrable, et probablement faux dans le
détail (les schémas Sage varient selon la version et le paramétrage du
dossier). Le module documente les tables qu'il faudrait mapper
(`F_ECRITUREC`, `F_COMPTET`, `F_JOURNAL`, `F_COMPTEG`) et pourquoi ce n'est pas
fait.

**Ce que prouve réellement la phase 5, ce n'est pas Sage : c'est que le moteur
d'audit ne dépend plus d'Odoo.** Et ça, `fichier_connecteur.py` le démontre.

#### f) Le calendrier ne regardait jamais en arrière

Problème découvert en écrivant la réconciliation : `get_calendar_events()` ne
générait que des échéances **futures** (`if due >= today` partout). On ne peut
pas constater qu'une déclaration manque si on ne regarde jamais les échéances
passées. Sur un dossier fraîchement créé, la réconciliation aurait toujours
retourné une liste vide.

D'où `nb_months_back`, **désactivé par défaut** pour que l'affichage du
calendrier reste identique (vérifié par test), et appelé avec 12 mois par la
réconciliation.

#### g) Le bug de détection de paiement

Le code d'origine faisait :

```python
if any(kw in ref or kw in name for kw in ["tva", "is", "acompte", "ir", "taxe", "impot"]):
```

Recherche de **sous-chaîne**. « is » matche « Bismillah », « Devis », « Mise à
disposition » ; « ir » matche « Virement ». Des échéances étaient donc marquées
« payées » sur des écritures sans aucun rapport.

**C'est un faux négatif sur de la détection de risque** — le cabinet ne voyait
pas une obligation réellement non remplie. C'est la pire direction possible
pour se tromper dans ce produit.

Corrigé par recherche de mot entier et rattachement du paiement à sa catégorie
d'impôt :

```python
_MOTS_CLES_PAIEMENT = [("tva", "TVA"), ("is", "IS"), ("cnss", "CNSS"), ..., ("impot", None)]

def paiement_detecte(paiements, categorie, mois) -> bool:
    return (categorie, mois) in paiements or (None, mois) in paiements
```

Sans le rattachement, un virement de TVA faisait taire l'alerte CNSS du même
mois. Mesuré sur le test : la couverture passe de **4 échéances à 1** pour un
paiement unique.

#### h) Réconciliation : un module court, et c'est voulu

`reconciliation.py` fait ~90 lignes parce qu'il **ne calcule presque rien de
neuf**. `tax_calendar.py` sait déjà quelles obligations tombent à quelle date et
sait déjà les qualifier payé / en retard / à venir. Réconcilier, c'est lire ce
résultat sur une fenêtre qui inclut le passé.

Deux signaux marquent une échéance comme couverte : une ligne `Declaration`
déposée, **ou** un paiement détecté dans les écritures. Le second est une
heuristique, pas une preuve — d'où le vocabulaire imposé à l'interface :
**« aucune trace de dépôt ni de paiement »**, jamais « vous n'avez pas
déclaré ». Nisab signale, le comptable tranche.

Toute la sortie porte `sourced: false`, y compris ligne par ligne : elle hérite
du statut non-RAG de `tax_calendar.py`. **Une affirmation non sourcée a le droit
d'exister, à condition de ne jamais se faire passer pour une affirmation
sourcée.**

À noter : la table `Declaration` existe depuis la phase 1 et n'est alimentée par
aucun flux. C'est volontaire — c'est le point d'entrée prévu pour une saisie
manuelle (« j'ai déposé, arrête de me le signaler »). Tant qu'elle est vide, la
détection repose uniquement sur les traces comptables.

---

### 4. Flux complet des données

```
                     3 sources, 1 seul contrat
                     
  Odoo XML-RPC        Fichier CSV/Excel        Sage ODBC (stub)
       |                     |                       |
       v                     v                       X
OdooAccountingConnector  FichierAccountingConnector
       |                     |
       +----------+----------+
                  |
                  v
         fetch_accounting_data()
                  |
                  v
      SCHEMA PIVOT {company, partners, moves, lines, source}
      (= le dict Odoo ; move["id"] DETERMINISTE par hachage)
                  |
                  v
      _persist_accounting_data()  --> PieceComptable (snapshot JSONB)
                  |                   ConnexionComptable (derniere_sync)
                  |
       +----------+----------------------+
       |          |                      |
       v          v                      v
  ai_auditor  tax_calendar        dashboard_summary
  (INCHANGE)  get_calendar_events()
       |          |
       |          v  nb_months_back=12
       |     reconciliation.rapprochement_declaratif()
       |          |
       |          +-- echeance echue ?
       |          +-- Declaration deposee ?          --> couverte
       |          +-- paiement_detecte(cat, mois) ?  --> couverte
       |          +-- sinon                          --> MANQUANTE
       v          v
  AuditPage   CalendarPage + ReconciliationBanner (sourced: false)
```

---

### 5. Lien avec le frontend

| Étape | Composant | Appel | Endpoint | JSON reçu | Impact UI |
|---|---|---|---|---|---|
| Téléchargement du modèle | `ImportFichierCard.jsx` | `apiFetch` | `GET /dossiers/{id}/import/modele` | `text/csv` | Déclenche un téléchargement navigateur |
| Import d'un fichier | `ImportFichierCard.jsx` | `apiFetch` + `FormData` | `POST /dossiers/{id}/import/fichier` | `{company, nb_moves, nb_lignes, nb_partners, nb_lignes_ignorees, warnings[]}` | Bandeau vert + liste des lignes écartées |
| État du connecteur Sage | *(à brancher)* | — | `POST /dossiers/{id}/sage/test` | `{ok:false, untested:true, message}` | Badge « Non testé », jamais « en panne » |
| Obligations manquantes | `CalendarPage.jsx` → `ReconciliationBanner` | `dossierFetch` | `GET /dossiers/{id}/reconciliation/declaratif` | `{echeances_manquantes[], nb_couvertes, par_categorie, sourced:false, avertissement}` | Bandeau rouge dépliable, table des échéances + majorations |

La requête de réconciliation est **volontairement séparée et non bloquante** de
celle du calendrier : les deux répondent à des questions différentes (« ce qui
reste à faire » contre « ce qui aurait dû être fait »), et un échec de la
seconde ne doit pas priver le cabinet de la première.

---

### 6. Pourquoi cette architecture ?

**Le schéma pivot est le dict Odoo, plutôt qu'un modèle neutre.**
Détaillé en 3a. En une phrase : réécrire trois consommateurs pour un gain
utilisateur nul aurait été du travail contre soi-même. Le cahier des charges dit
« se brancher sur l'existant, ne pas le refaire » — la même discipline s'applique
à son propre code.

**Identifiants par hachage plutôt que par compteur.**
Le compteur dépend de l'ordre de lecture ; le hachage dépend de la pièce. La clé
métier du flux 14 en dépend directement : sans déterminisme, chaque ré-import
détacherait toutes les corrections validées de leurs anomalies.

**Warnings plutôt qu'exception sur ligne invalide.**
Alternative écartée : rejeter le fichier entier. Rejetée parce qu'inutilisable
en pratique — mais avec une contrepartie non négociable : les lignes écartées
sont **affichées**, jamais silencieuses.

**Stub Sage plutôt qu'implémentation invérifiable.**
Alternative écartée : écrire les quatre requêtes ODBC d'après la documentation.
Rejetée parce que du code jamais exécuté contre un vrai système donne une fausse
impression de complétude, à un jury comme à un futur mainteneur. L'abstraction
est le livrable ; le connecteur ne l'est pas.

**Réconciliation calculée à la volée, sans table dédiée.**
Alternative écartée : une table `rapprochement`. Rejetée parce qu'il n'y a **rien
à mémoriser** : le résultat est entièrement dérivé du calendrier légal et des
écritures déjà persistées. Une table aurait ajouté un risque de désynchronisation
(résultat périmé après un nouvel import) pour zéro gain.

**Le champ `sourced: false` répété sur chaque ligne**, pas seulement au niveau de
la réponse. Le frontend ne doit pas avoir à se souvenir d'une règle globale pour
savoir comment afficher une ligne.

---

### 7. Lien avec le cahier des charges

Répond directement au **module 1 — Ingestion & données** : *« connexion logiciel
comptable + import (balance, factures, déclarations), réconciliation, détection
des pièces manquantes »*
([`cahier-des-charges.md:31-33`](../cahier-des-charges.md#L31-L33)).

Répond aussi à la **contrainte technique** : *« Connecteurs logiciels comptables
(Sage, Odoo...) + import fichiers/OCR : se brancher sur l'existant, ne pas le
refaire »*
([`cahier-des-charges.md:53-54`](../cahier-des-charges.md#L53-L54)).

**Ce qui n'est pas couvert, et qu'il faut assumer :** l'OCR de factures et le
rapprochement pièce-par-pièce (chaque écriture a-t-elle sa facture
justificative, Art. 146 CGI). Le cahier des charges les mentionne ; ils ont été
écartés du périmètre par arbitrage de temps, et la valeur `ocr` de
`TypeConnexion` reste disponible pour les brancher. À dire explicitement plutôt
qu'à laisser croire couvert.

---

### 8. Ce que je dois retenir pour la soutenance

- La preuve de la phase 5 n'est pas « on lit un CSV », c'est **« le moteur d'audit ne sait pas qu'il ne parle plus à Odoo »** — zéro ligne d'`ai_auditor.py` modifiée, prouvé par test.
- Le schéma pivot **est** le dict Odoo, délibérément : inventer un format neutre aurait obligé à réécrire tout le moteur pour zéro gain utilisateur.
- Les identifiants de pièce sont **déterministes par hachage** : ré-importer le même fichier produit les mêmes ids, sinon les corrections validées se détacheraient de leurs anomalies.
- Bug attrapé par le test : hachage sur 32 bits contre `INTEGER` **signé** de Postgres → échec une fois sur deux, de façon apparemment aléatoire. Masqué sur 31 bits.
- Bug corrigé dans l'existant : « is » en sous-chaîne matchait « Bismillah », « Devis », « Virement » → des échéances marquées payées à tort. **Faux négatif sur de la détection de risque**, la pire direction possible.
- Le calendrier ne générait que du futur ; on ne peut pas détecter une déclaration manquante sans regarder en arrière → `nb_months_back`, désactivé par défaut pour ne pas changer l'affichage.
- Sage est un **stub assumé** : l'abstraction est le livrable, pas une implémentation ODBC jamais exécutée.
- Vocabulaire imposé : « aucune trace de dépôt » et jamais « vous n'avez pas déclaré ». Nisab signale, le comptable tranche.

---

### 9. Questions probables du jury

**Pourquoi ne pas avoir défini un vrai format pivot neutre ?**
Parce que trois modules le consommaient déjà sous forme de dict Odoo. Un format
neutre aurait imposé de réécrire le moteur d'audit, le calendrier et le
dashboard, sans qu'un seul utilisateur y gagne. La dette est de nommage, pas de
conception, et elle est documentée.

**Votre connecteur Sage ne fait rien — n'est-ce pas un livrable manquant ?**
C'est un choix explicite. Sans licence ni instance Sage, écrire du SQL ODBC
jamais exécuté aurait produit du code d'apparence fonctionnelle et probablement
faux. Ce que la phase devait prouver — l'indépendance du moteur vis-à-vis
d'Odoo — est démontré par le connecteur fichier, qui, lui, tourne.

**Comment garantissez-vous qu'un ré-import ne casse pas les corrections déjà validées ?**
Par le déterminisme des identifiants : `move["id"]` est un hachage du numéro de
pièce, pas un compteur. Le test le vérifie explicitement, y compris avec les
lignes du fichier dans un ordre différent.

**Votre détection de paiement repose sur des mots-clés — c'est fragile ?**
Oui, et c'est assumé : elle est marquée `sourced: false` et l'interface dit
« aucune trace de », jamais « vous n'avez pas déclaré ». Elle a d'ailleurs été
durcie après un test : recherche de mot entier au lieu de sous-chaîne, et
rattachement du paiement à sa catégorie d'impôt.

**Que se passe-t-il si le fichier importé est mal formé ?**
Les lignes illisibles sont écartées une par une, comptées, et **affichées** à
l'utilisateur. Le fichier n'est rejeté en entier que si aucune écriture
exploitable n'en ressort.

---

### 10. Étapes de test dans l'application

1. Onglet **Sources de données** → carte **Import de fichier comptable** →
   **Télécharger le modèle**.
2. Ouvrir le modèle : trois lignes formant une écriture équilibrée
   (`6142` et `34551` au débit, `4411` au crédit).
3. Le redéposer tel quel dans la zone de dépôt → bandeau vert :
   « 1 écriture, 3 lignes, 1 tiers importés ».
4. Ouvrir **Audit fiscal** → l'analyse tourne sur les données importées, sans
   Odoo.
5. Modifier le modèle : ajouter une ligne avec une date illisible → réimporter
   → bandeau orange « 1 ligne ignorée » avec le motif exact.
6. Ouvrir **Calendrier fiscal** → bandeau rouge en tête si des obligations
   échues n'ont aucune trace ; le déplier affiche les échéances, leurs
   majorations encourues, et l'avertissement non-RAG.

Ou, en une commande depuis `backend/` : `python test_import_fichier.py`
(22 contrôles, dont le passage des données CSV dans les fonctions internes
d'`ai_auditor.py` non modifiées).

---

## 16. Workflow agentique de correction avec validation humaine

### 1. Vue d'ensemble

C'est le seul flux du projet qui **écrit** dans le système comptable du client.
C'est donc celui où chaque garde-fou compte.

Les modules 3 et 4 disent au cabinet *ce qui ne va pas* et *comment il se
défendrait devant un contrôle*. Ils ne disent pas *quoi faire concrètement*.
Ce flux comble cet écart : à partir d'une anomalie **déjà détectée et déjà
sourcée**, il produit une proposition d'action — le plus souvent une écriture
d'opérations diverses — qu'un humain valide, amende ou rejette, et qui peut
ensuite être déposée **en brouillon** dans Odoo.

La phrase qui résume tout le flux, et qu'il faut pouvoir dire telle quelle :

> **Le LLM propose, la comptabilité arbitre, l'humain décide.**

Trois garde-fous en cascade, et le plus fort — l'équilibre en partie double —
ne dépend d'aucun modèle de langage.

Ce que ce flux n'est pas : un agent autonome. La boucle est contrainte à un
tour, et aucune écriture ne quitte Nisab sans qu'un humain identifié l'ait
endossée. Le mot « agentique » désigne ici le cycle *propose → critique →
révise*, pas une délégation de décision.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Rôle |
|---|---|---|
| `backend/app/models.py` | `StatutProposition`, `TypeCorrection` | 5 états, 4 natures de correction |
| `backend/app/models.py` | `PropositionCorrection`, `CitationProposition` | La proposition et ses sources |
| `backend/migrations/versions/a7c1e4f6b0d3_...py` | migration | 2 tables + **RLS écrite à la main** + index partiel |
| `backend/app/correction_agent.py` | `generer_proposition()` | Génération + boucle d'auto-critique |
| `backend/app/correction_agent.py` | `valider_equilibre()` | Garde-fou déterministe, sans LLM |
| `backend/app/correction_agent.py` | `_filtrer_references()` | Anti-hallucination sur les citations |
| `backend/app/secrets_store.py` | `chiffrer()` / `dechiffrer()` | Fernet, clé séparée de `JWT_SECRET` |
| `backend/app/odoo_connector.py` | `create_draft_move()`, `resolve_account()`, `detect_company_id()` | Écriture Odoo, **jamais postée** |
| `backend/app/routes_corrections.py` | 7 endpoints | Machine à états complète |
| `frontend/src/pages/CorrectionsPage.jsx` | file de validation | Maître/détail, écart débit/crédit visible |
| `frontend/src/components/audit/CitationPills.jsx` | pastilles de citation | Partagé audit / corrections / veille |
| `backend/test_correction.py` | 33 contrôles | Garde-fous, sans LLM |
| `backend/test_push_odoo.py` | 14 contrôles | Écriture réelle dans Odoo, vérifiée `draft` |

---

### 3. Explication détaillée du code

#### a) Le piège de conception à ne pas rouvrir

**Beaucoup d'anomalies fiscales n'ont pas de correction comptable.** Un
fournisseur sans ICE, une facture sans mentions obligatoires, un règlement en
espèces déjà effectué : aucune écriture d'OD ne répare ça.

Un prompt qui exigerait une écriture dans tous les cas en obtiendrait une —
inventée, plausible, et fausse. **Une écriture inventée pour un problème
qu'elle ne résout pas est pire qu'une absence de proposition, parce qu'elle a
l'air d'une réponse.**

D'où quatre natures de correction, dont deux **sans** écriture :

| `TypeCorrection` | Écriture ? | Cas typique |
|---|---|---|
| `ecriture_od` | oui | Charge à réintégrer, mauvaise imputation |
| `regularisation_tva` | oui | TVA déduite ou collectée à tort |
| `piece_a_reclamer` | **non** | Obtenir la facture conforme, l'ICE du fournisseur |
| `aucune_ecriture` | **non** | Fait acquis (espèces déjà versées), délai forclos |

Le test le vérifie explicitement : quand le LLM propose des lignes d'écriture
sur un type documentaire, **elles sont retirées**.

#### b) Garde-fou 1 — le filtrage des citations

```python
def _filtrer_references(brutes, autorisees: list[str]) -> list[str]:
    index = {_normalize_ref(r): r for r in autorisees}
    ...
```

Le générateur **ne fait aucune nouvelle recherche RAG**. Il reçoit uniquement
le texte des articles déjà cités par l'alerte, via
`get_texts_by_references()`. C'est le précédent posé par
`control_simulator.py`, et ce n'est pas une économie : si ce module allait
chercher ses propres articles, il pourrait fonder une correction sur un texte
que l'alerte ne citait pas, et **le constat ne correspondrait plus au remède**.

Toute référence citée par le LLM en dehors de celles de l'alerte est écartée.
Si après filtrage il n'en reste aucune :

```python
if not references:
    raise RuntimeError(
        "La proposition ne cite aucun article vérifiable parmi ceux qui fondent l'alerte. "
        "Elle n'est pas enregistrée : une correction sans source n'a aucune valeur devant un contrôle."
    )
```

**Rien n'est persisté.** L'API répond 502. C'est l'invariant du module : une
`PropositionCorrection` n'existe en base que si elle est rattachée à au moins
une `CitationProposition`.

#### c) Garde-fou 2 — l'auto-critique

Après génération, un second appel (modèle rapide) relit la proposition en
regard des textes d'articles et répond `{"coherent": bool, "motif": str}`. Si
non : **une seule** régénération, avec la critique injectée dans le prompt,
puis abandon.

Détail important sur le mode dégradé :

```python
if not isinstance(resultat, dict) or "coherent" not in resultat:
    return {"coherent": True, "motif": "", "indisponible": True}
```

En cas d'échec technique du LLM, on retourne « cohérent ». **La critique est un
bonus de qualité, pas un garde-fou de sécurité.** La refuser par défaut ferait
échouer des propositions correctes parce qu'un quota Groq est épuisé — alors
que les vrais garde-fous (citations, équilibre) sont ailleurs et ne dépendent
d'aucun modèle.

Et si la révision est **pire** que l'original, on garde l'original en
conservant la trace de la réserve émise. Abandonner priverait l'utilisateur
d'une proposition par ailleurs valide.

#### d) Garde-fou 3 — la partie double, sans LLM

```python
ecart = round(total_debit - total_credit, 2)
if abs(ecart) > TOLERANCE_EQUILIBRE:
    return False, f"Écriture déséquilibrée : débit {total_debit:.2f} DH, crédit {total_credit:.2f} DH, écart de {abs(ecart):.2f} DH."
```

Vérification purement arithmétique : somme des débits égale somme des crédits à
un centime près, au moins deux lignes, aucun montant négatif, jamais débit
**et** crédit sur la même ligne, compte obligatoire.

**C'est le garde-fou le plus fort du module, précisément parce qu'il ne dépend
d'aucun modèle.** Aucun raisonnement, aussi convaincant soit-il, ne peut le
contourner. Il est rejoué à trois moments : à la génération, à l'amendement
(un humain se trompe aussi — la règle ne lui est pas plus indulgente), et
juste avant le push.

#### e) La machine à états — cinq états, pas un de plus

```
en_attente ──valider──► validee ──pousser──► poussee
   │  ▲                        │
   │  └── PATCH (amendement)   └── échec ─► erreur ──retry──► validee
   └──rejeter (motif obligatoire)──► rejetee   (terminal, regénérable)
```

**Pas d'état « brouillon ».** La génération est synchrone : si le LLM échoue ou
si un garde-fou refuse la sortie, rien n'est écrit. Une proposition qui existe
est une proposition valide.

**Pas d'état « amendée ».** Amender, c'est éditer le payload d'une proposition
restée `en_attente`. La traçabilité est portée par `amendee_le`,
`amendee_par_id` et `payload_origine_json`. Moins d'états à expliquer, même
information conservée.

Toute transition illégale répond **409** avec un message en français, jamais un
500.

#### f) `payload_origine_json` — la frontière machine / humain

Au **premier** amendement seulement :

```python
if p.payload_origine_json is None:
    p.payload_origine_json = p.payload_json
```

Sans cette colonne, on ne pourrait plus distinguer ce qui vient de la machine
de ce qui vient de l'humain. C'est exactement la question qu'un contrôleur
fiscal poserait — et l'interface l'affiche : « cette proposition a été modifiée
manuellement, la version initiale de l'IA est conservée en base ».

#### g) Le motif de rejet obligatoire

```python
class RejetRequest(BaseModel):
    motif: str = Field(..., min_length=5, max_length=2000)
```

Ce n'est pas de la bureaucratie. Un rejet sans motif ne se distingue pas d'un
oubli. Et c'est le seul signal exploitable sur ce que l'IA propose de travers,
ainsi que la trace qui permet de dire à un contrôleur « cette piste a été
examinée puis écartée pour telle raison » plutôt que « on ne l'a pas traitée ».

Côté interface, un `textarea` en ligne et **pas** `window.confirm` — on ne peut
pas saisir un motif dans une boîte de confirmation.

#### h) Le chiffrement des identifiants ERP

```python
NISAB_SECRET_KEY  # Fernet, base64 urlsafe 32 octets
```

Fernet fournit du chiffrement **authentifié** (AES-128-CBC + HMAC-SHA256) : un
contenu altéré est rejeté au déchiffrement plutôt que de produire des données
fausses.

**La clé est volontairement séparée de `JWT_SECRET`, et non dérivée de lui.**
Faire tourner le secret JWT est une opération de sécurité normale et
souhaitable (fuite suspectée, rotation périodique) ; si les deux étaient liés,
cette rotation rendrait **silencieusement illisibles** tous les identifiants
ERP déjà stockés. On ne s'en apercevrait qu'à la première tentative de push,
chez un client, sans comprendre pourquoi.

La mémorisation est **opt-in** : une case à cocher explicite dans l'interface.
On ne stocke pas le mot de passe de la comptabilité d'un client sans qu'il l'ait
demandé. Et aucun endpoint ne renvoie jamais les identifiants déchiffrés.

**Limite à énoncer plutôt qu'à laisser croire résolue :** une clé unique pour
toute la plateforme. Quiconque a la clé et un accès base peut déchiffrer les
identifiants de tous les cabinets. La vraie réponse serait un gestionnaire de
secrets externe (Vault, KMS) avec une clé par organisation — hors périmètre
d'un MVP de stage.

#### i) L'écriture Odoo, et ce qu'elle ne fait jamais

```python
# RÈGLE PRODUIT NON NÉGOCIABLE : cette méthode n'appelle JAMAIS action_post.
```

Nisab ne valide aucune écriture comptable, jamais. Elle dépose une proposition
déjà relue et validée par un humain **dans Nisab**, que le comptable relit une
seconde fois **dans son ERP** et poste lui-même s'il est d'accord. Le dernier
geste comptable reste au comptable — c'est le fondement de la responsabilité
professionnelle en cas de contrôle.

Et on ne se contente pas de ne pas appeler `action_post` : on **relit l'état**
après création et on lève une erreur si l'écriture n'est pas en `draft`. Si une
automatisation Odoo (règle serveur, module tiers) l'a postée, il faut le dire —
pas prétendre que la règle a été respectée.

#### j) Deux découvertes faites sur l'instance Odoo 18 réelle

Ces deux points n'étaient pas au plan. Ils ont été trouvés en écrivant un
script de diagnostic **avant** d'écrire le code (`scripts/check_odoo18.py`).

**La société courante Odoo n'est pas celle qui contient la comptabilité.** Sur
la base de test, la session pointait sur `My Company (San Francisco)` (0
écriture) alors que les 23 écritures étaient dans `MA Company`. Créer une
écriture dans la mauvaise société avec les comptes d'une autre fait échouer
Odoo avec un message peu lisible.

D'où `detect_company_id()`, qui déduit la société **des écritures**, jamais de
la session, et l'injection systématique d'`allowed_company_ids` dans le
contexte de chaque appel :

```python
if self.company_id is not None:
    kwargs.setdefault("context", {}).setdefault("allowed_company_ids", [self.company_id])
```

Ce n'est pas une précaution décorative : depuis Odoo 17, `account.account.code`
est un champ **dépendant de la société**. Hors du bon contexte,
`search([("code","=","441110")])` ne renvoie **rien du tout** — alors que le
compte existe. Et le même code désigne des enregistrements différents selon la
société (441110 = id 892 dans l'une, id 252 dans l'autre).

**Le LLM raisonne en codes CGNC à 4 chiffres, le plan Odoo est à 6.** Le CGI et
les manuels de comptabilité écrivent `6142` ; le plan marocain livré par Odoo
complète à `614210 Transport of Personnel`. Une recherche par égalité ne
trouverait donc jamais rien.

D'où une résolution par **préfixe**, avec un garde-fou ajouté après un test :

```python
if len(code) < LONGUEUR_MIN_PREFIXE_COMPTE:  # 4
    raise OdooWriteError(f"Code comptable « {code} » trop imprécis...")
```

Sans ce minimum, `resolve_account("6")` renverrait le premier compte de charge
venu. **Un code trop court est le symptôme d'une hallucination, pas d'une
abréviation.**

#### k) L'index partiel

```sql
CREATE UNIQUE INDEX ux_proposition_vivante ON proposition_correction (alerte_id)
WHERE statut <> 'rejetee';
```

Au plus une proposition non rejetée par alerte. Sans lui, cliquer deux fois sur
« Proposer une correction » créerait deux propositions concurrentes sur la même
anomalie, chacune validable indépendamment — donc potentiellement **deux
écritures poussées dans Odoo pour corriger une seule fois le même problème**.

Les rejetées sont exclues de la contrainte : elles restent en historique tout
en laissant regénérer une nouvelle proposition.

---

### 4. Flux complet des données

```
AlerteRisque (actif=true, cle_metier stable — voir flux 14)
     |
     |  POST /dossiers/{id}/alertes/{alerte_id}/proposition
     v
get_texts_by_references(alerte.rag_sources + reference_cgi)
     |            (AUCUNE nouvelle recherche RAG)
     v
generer_proposition(alerte, textes)
     |
     +-- llm_call_json(SYSTEM_PROMPT, contexte legal)  --> JSON brut
     |
     +-- GARDE-FOU 1 : _filtrer_references()
     |        references hors alerte ecartees
     |        aucune reste ? --> RuntimeError, RIEN n'est persiste (502)
     |
     +-- GARDE-FOU 3 : valider_equilibre()  (si type avec ecriture)
     |        desequilibre ? --> RuntimeError, RIEN n'est persiste
     |
     +-- GARDE-FOU 2 : _auto_critique()  (modele rapide)
     |        incoherent ? --> UNE regeneration avec la critique
     |        revision pire ? --> on garde l'original + trace de la reserve
     v
INSERT proposition_correction (statut = en_attente)
INSERT citation_proposition x N   <-- invariant : jamais zero
     |
     v
CorrectionsPage : le validateur lit, relit les articles cites,
                  edite les lignes si besoin (ecart affiche en rouge)
     |
     +---- PATCH .../{pid}          amendement (equilibre reverifie)
     |                              payload_origine_json fige au 1er passage
     |
     +---- POST .../{pid}/rejeter   motif OBLIGATOIRE --> rejetee (terminal)
     |
     +---- POST .../{pid}/valider   equilibre reverifie --> validee
                 |                  decide_par_id + decide_le renseignes
                 v
           POST .../{pid}/pousser   (niveau dossier = admin)
                 |
                 +-- cle Fernet disponible ?         non --> 503
                 +-- identifiants memorises ?        non --> 400
                 +-- type avec ecriture ?            non --> 400
                 +-- equilibre ?                     non --> 422
                 |
                 v
           OdooConnector(company_id = celui du snapshot audite)
                 |
                 +-- resolve_journal()   type=general
                 +-- resolve_account()   6142 --> 614210 (par prefixe)
                 |        compte introuvable --> OdooWriteError lisible
                 v
           account.move.create(state implicite = draft)
                 |
                 +-- JAMAIS action_post
                 +-- relecture de state ; si != draft --> erreur explicite
                 |
        +--------+--------+
        v                 v
    succes             echec XML-RPC
    statut=poussee     statut=erreur + erreur_message PERSISTE (502)
    odoo_move_id       (reprise possible : erreur --> pousser)
    alerte.statut=traitee
```

---

### 5. Lien avec le frontend

| Étape | Composant | Appel | Endpoint | JSON reçu | Impact UI |
|---|---|---|---|---|---|
| Proposer une correction | `FindingCard.jsx` → bouton | `dossierFetch` | `POST /dossiers/{id}/alertes/{aid}/proposition` | `Proposition` | Bascule automatiquement sur la vue Corrections |
| Charger la file | `App.jsx` → `loadPropositions()` | `dossierFetch` | `GET /dossiers/{id}/propositions` | `{propositions[]}` | Indexées par `alerte_id`, badge sur chaque `FindingCard` |
| Ouvrir le détail | `CorrectionsPage.jsx` | `dossierFetch` | `GET /dossiers/{id}/propositions/{pid}` | `Proposition` + `articles_cites[]` avec texte intégral | Panneau détail, pastilles de citation lisibles |
| Amender | `CorrectionsPage.jsx` | `dossierFetch` PATCH | `PATCH /dossiers/{id}/propositions/{pid}` | `Proposition` amendée | Bouton désactivé tant que l'écart n'est pas nul |
| Valider | `CorrectionsPage.jsx` | `dossierFetch` POST | `POST .../valider` | `Proposition` (`validee`) | Fait apparaître « Créer le brouillon dans Odoo » |
| Rejeter | `CorrectionsPage.jsx` | `dossierFetch` POST | `POST .../rejeter` | `Proposition` (`rejetee`) | `textarea` motif inline, 5 caractères minimum |
| Pousser | `CorrectionsPage.jsx` | `dossierFetch` POST | `POST .../pousser` | `{odoo_move_id, odoo_url, comptes_resolus[]}` | Lien direct vers le brouillon + rappel « il n'est PAS validé » |

Le chargement des propositions utilise le **garde anti-réponse-obsolète**
(`activeDossierIdRef` + `isStale()`) : une génération dure 10 à 30 secondes, et
un changement de dossier pendant ce temps ne doit pas écraser l'état du nouveau
dossier affiché.

---

### 6. Pourquoi cette architecture ?

**Aucune nouvelle recherche RAG dans le générateur.**
Alternative écartée : relancer une recherche pour trouver « les meilleurs
articles pour corriger ». Rejetée parce que le remède doit se fonder sur le même
texte que le constat. Sinon on obtiendrait une correction juridiquement
argumentée… sur un article que l'alerte ne citait pas, et la chaîne
constat → source → remède se romprait sans que personne ne le voie.

**Un garde-fou déterministe en plus des garde-fous LLM.**
Les deux premiers (filtrage des citations, auto-critique) dépendent de modèles.
Le troisième — la partie double — est de l'arithmétique. C'est la seule
protection qu'aucun raisonnement convaincant ne peut contourner, et c'est
pourquoi elle est rejouée trois fois.

**Quatre types de correction plutôt qu'un seul.**
Alternative écartée : toujours produire une écriture. Rejetée parce que le LLM
en produirait une même quand il n'y en a pas — et une écriture inventée pour un
problème documentaire est plus dangereuse qu'une absence de proposition.

**Cinq états plutôt que sept ou huit.**
Pas d'état « brouillon » (la génération est synchrone), pas d'état « amendée »
(l'amendement est une édition tracée par des colonnes). Chaque état supprimé est
une transition en moins à expliquer et à tester.

**Brouillon Odoo plutôt qu'écriture postée.**
Alternative écartée : poster directement après validation humaine. Rejetée pour
une raison qui n'est pas technique : la responsabilité. Le comptable engage sa
signature sur les écritures de son client ; il doit pouvoir relire dans son
propre outil avant de valider. Techniquement, `action_post` était une ligne de
plus — c'est le refus de la franchir qui est la décision.

**Échec du push persisté (`statut = erreur`) plutôt que message éphémère.**
Sans ça, l'utilisateur verrait une erreur passagère et la proposition resterait
« validée » comme si de rien n'était, sans trace de la tentative. L'état
`erreur` est aussi le chemin de reprise : mot de passe changé, compte manquant
depuis créé.

**`dossier_id` dénormalisé sur `proposition_correction`.**
Déductible via `alerte_id → alerte_risque.dossier_id`, mais dupliqué quand même
parce que c'est la colonne sur laquelle porte la policy RLS. Une policy qui
devrait faire une jointure serait plus lente et surtout plus facile à écrire de
travers. **La colonne qui protège les données du client doit être la plus simple
possible à relire.**

---

### 7. Lien avec le cahier des charges

Ce flux ne correspond à aucun module numéroté : il **n'était ni dans le cahier
des charges, ni dans le plan d'implémentation**. Il figure uniquement dans
les règles d'architecture du projet et le `README` comme intention — « workflow
agentique ERP = proposition + validation humaine (jamais d'écriture comptable
automatique) ».

C'est donc la **contribution propre du stage**, par-dessus le périmètre demandé,
et c'est ainsi qu'il faut le présenter. Il prolonge le module 4 — *« produit
rapport + plan de remédiation »*
([`cahier-des-charges.md:39-41`](../cahier-des-charges.md#L39-L41)) — en
transformant un plan de remédiation textuel en action exécutable et tracée.

Il respecte par ailleurs la contrainte **anti-hallucination** du cahier des
charges (*« zones grises renvoyées à l'expert »*,
[`cahier-des-charges.md:57`](../cahier-des-charges.md#L57)) de la façon la plus
littérale possible : la zone grise n'est pas seulement signalée, elle est
**bloquée** — sans citation vérifiable, la proposition n'est pas enregistrée.

---

### 8. Ce que je dois retenir pour la soutenance

- La phrase à dire : **le LLM propose, la comptabilité arbitre, l'humain décide.**
- Trois garde-fous en cascade : filtrage des citations (502 si aucune source valide), auto-critique (un tour), **partie double vérifiée en dur** — le seul qui ne dépend d'aucun modèle.
- **Aucune nouvelle recherche RAG** : le générateur ne voit que les articles déjà cités par l'alerte. Le remède se fonde sur le même texte que le constat.
- Le piège évité : beaucoup d'anomalies **n'ont pas** de correction comptable. Forcer une écriture en produirait une inventée — pire qu'une absence de proposition, parce qu'elle a l'air d'une réponse.
- `create_draft_move` n'appelle **jamais** `action_post`, et relit l'état pour le vérifier. Le dernier geste comptable reste au comptable.
- Deux découvertes sur l'Odoo réel : la société de session n'est pas celle des écritures (`allowed_company_ids` forcé), et le LLM dit `6142` là où le plan a `614210` (résolution par préfixe, minimum 4 chiffres).
- `NISAB_SECRET_KEY` séparée de `JWT_SECRET` : faire tourner le JWT ne doit pas rendre illisibles les identifiants ERP.
- Le motif de rejet est obligatoire : c'est le seul signal sur ce que l'IA propose de travers, et la trace qui distingue « écartée pour telle raison » de « pas traitée ».
- 47 contrôles automatisés, dont une écriture réellement créée dans Odoo 18 puis vérifiée `draft` et supprimée.

---

### 9. Questions probables du jury

**En quoi est-ce « agentique » et pas simplement un appel à un LLM ?**
Par la boucle *propose → critique → révise* : une seconde passe relit la
proposition et déclenche une régénération ciblée si elle la juge incohérente. À
dire honnêtement : c'est une boucle contrainte à **un seul tour**, avec
validation humaine obligatoire ensuite. Ce n'est pas un agent autonome, et je ne
le présente pas comme tel.

**Que se passe-t-il si le LLM invente une écriture fausse ?**
Trois filtres. S'il cite un article que l'alerte ne citait pas, la référence est
écartée ; s'il n'en reste aucune, rien n'est enregistré. Si l'écriture est
déséquilibrée, elle est refusée par un contrôle arithmétique qu'aucun
raisonnement ne peut contourner. Et si elle passe ces deux filtres, un humain la
lit avant qu'elle ne parte.

**Pourquoi ne pas poster directement l'écriture dans Odoo ?**
Ce n'est pas une limite technique — `action_post` est une ligne de plus. C'est
un refus délibéré : le comptable engage sa responsabilité professionnelle sur
les écritures de son client, il doit pouvoir relire dans son propre outil. Nisab
dépose, le comptable valide.

**Comment savez-vous que l'écriture créée est bien un brouillon ?**
On ne le suppose pas : on relit `state` après création et on lève une erreur si
ce n'est pas `draft`. Le test `test_push_odoo.py` crée une vraie écriture dans
Odoo 18, vérifie son état par une relecture indépendante, puis la supprime.

**Stocker des mots de passe ERP en base, n'est-ce pas dangereux ?**
Ils sont chiffrés avec Fernet (chiffrement authentifié), la mémorisation est
opt-in explicite, et aucun endpoint ne les renvoie jamais. La limite réelle,
que j'assume : une clé unique pour toute la plateforme. La réponse industrielle
serait un KMS avec une clé par organisation — hors périmètre d'un MVP.

**Et si deux utilisateurs valident la même correction en même temps ?**
L'index partiel `ux_proposition_vivante` garantit au plus une proposition non
rejetée par alerte, donc il ne peut pas y avoir deux propositions concurrentes.
Un verrou applicatif par dossier empêche par ailleurs deux générations
simultanées.

---

### 10. Étapes de test dans l'application

**Prérequis :** `NISAB_SECRET_KEY` dans `backend/.env`, et une connexion Odoo
établie **avec la case « Mémoriser les identifiants » cochée** si l'on veut
tester le push.

1. Charger le scénario de démonstration `commerce`, puis lancer **Audit fiscal**.
2. Déplier une anomalie rouge → **Proposer une correction**. Compter 10 à 30
   secondes (deux appels LLM : génération + auto-critique).
3. La vue bascule sur **Corrections**. Vérifier dans le panneau détail :
   - le résumé et la justification,
   - les **pastilles d'articles** : cliquer dessus affiche le texte de loi,
   - la table des lignes avec **Total débit / Total crédit / Écart**.
4. Modifier un montant pour déséquilibrer l'écriture → l'écart passe en rouge et
   les boutons **Enregistrer** et **Valider** se désactivent.
5. Rétablir l'équilibre → **Valider**. Le bouton « Créer le brouillon dans
   Odoo » apparaît.
6. **Créer le brouillon dans Odoo** → bandeau vert avec lien direct. Ouvrir le
   lien : l'écriture est bien en **brouillon**, non comptabilisée.
7. Sur une autre anomalie, tester **Rejeter** : le bouton n'agit pas tant que le
   motif fait moins de 5 caractères.

Vérifications en base (ce qu'un jury peut demander à voir) :

```sql
-- L'invariant : jamais de proposition sans citation
SELECT p.id, p.statut, count(c.id) AS nb_citations
FROM proposition_correction p
LEFT JOIN citation_proposition c ON c.proposition_id = p.id
GROUP BY p.id, p.statut;   -- nb_citations >= 1 partout

-- Qui a décidé, et quand
SELECT resume, statut, decide_le, decide_par_id, motif_decision
FROM proposition_correction;
```

Ou, en deux commandes depuis `backend/` :

```
python test_correction.py                      # 33 contrôles, sans LLM
ODOO_DB=... ODOO_USER=... ODOO_PASSWORD=... python test_push_odoo.py
```

---

## 17. Veille personnalisée par citations

### 1. Vue d'ensemble

Le pipeline de veille du corpus détectait déjà les Bulletins Officiels, en
extrayait les articles, les validait. Mais cette information **restait dans le
corpus** : personne, au cabinet, n'apprenait qu'un article qu'il utilise venait
de bouger. Le module 6 du cahier des charges demande exactement l'inverse —
« signalement de l'impact sur le dossier avec action à mener ».

La question centrale de ce flux :

> **Comment décider qu'un article concerne CE dossier plutôt qu'un autre ?**

La réponse retenue, et c'est ce qui fait la différence entre « veille » et
« veille **personnalisée** » : un article concerne un dossier si **ce dossier a
déjà cité cette référence**.

Le produit persiste quatre traces de citation — une alerte d'audit, une réponse
de l'assistant, une simulation de contrôle, une proposition de correction. Si
l'une d'elles a invoqué l'article 106 sur ce dossier, alors une évolution de
l'article 106 le concerne. C'est vérifiable, ça se dit en une phrase, et **aucun
LLM n'intervient dans la décision**.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Rôle |
|---|---|---|
| `backend/app/veille.py` | `_SOURCES_CITATION` | Les 4 requêtes, une par table de citations |
| `backend/app/veille.py` | `dossiers_concernes_par_lot()` | Ciblage + motif, en 4 requêtes pour tout le corpus |
| `backend/app/veille.py` | `articles_nouveaux_depuis()` | Lecture du corpus SQLite |
| `backend/app/veille.py` | `diffuser()` | Création idempotente des notifications |
| `backend/app/veille.py` | `_niveau_pour()` | BO = niveau élevé, CGI consolidé = moyen |
| `backend/migrations/versions/b8d2f5a7c1e4_...py` | migration | 5 colonnes + index unique d'idempotence |
| `backend/app/admin.py` | `POST /admin/veille/diffuser` | Seule route du produit hors `get_tenant_db` |
| `backend/app/routes_veille.py` | 3 routes | Consultation par dossier |
| `frontend/src/pages/VeillePage.jsx` | page | Liste, badge CGI/BO, motif affiché |
| `backend/test_veille.py` | 22 contrôles | Ciblage prouvé par **dossier témoin** |

---

### 3. Explication détaillée du code

#### a) Le ciblage par citations, et l'alternative écartée

```python
_SOURCES_CITATION = [
    ("alerte de risque",           "... FROM citation_risque cr JOIN alerte_risque a ..."),
    ("réponse de l'assistant",     "... FROM citation c ..."),
    ("simulation de contrôle",     "... FROM citation_simulation cs JOIN simulation_controle s ..."),
    ("proposition de correction",  "... FROM citation_proposition cp JOIN proposition_correction p ..."),
]
```

L'alternative naturelle aurait été de classer chaque article par thème fiscal
(avec un LLM), puis de matcher sur `dossier.secteur_activite`. Écartée pour
trois raisons : ça coûte un appel LLM par article, ça introduit une possibilité
d'erreur de classement, et c'est **moins précis** — deux sociétés du même
secteur n'ont pas les mêmes problèmes fiscaux.

Le ciblage par citations est déterministe, gratuit, et fondé sur ce que ce
dossier a **réellement rencontré**.

Ajouter une cinquième forme de citation un jour = ajouter une ligne dans cette
liste, rien d'autre.

#### b) Le motif, et pourquoi il est persisté

```python
return {ref: {d: "Cité dans " + ", ".join(parts) for d, parts in par_dossier.items()} ...}
```

Produit des motifs comme « Cité dans 2 alertes de risque, 1 simulation de
contrôle ». Ce n'est pas cosmétique : **la veille doit pouvoir se justifier**,
au même titre que le reste du produit.

« Vous recevez ceci parce que cet article fonde 2 alertes sur ce dossier » est
vérifiable. « Cet article pourrait vous concerner » ne l'est pas. C'est la même
exigence que les citations ailleurs dans Nisab, appliquée à la notification
elle-même.

#### c) Le module était 300 fois trop lent

Première version : une requête par article et par source, soit
**401 articles × 4 sources = plus de 1 600 allers-retours** vers une base
Supabase distante. Le test dépassait deux minutes et a dû être interrompu.

Réécrit en lots :

```sql
WHERE cr.article_reference = ANY(:refs)
GROUP BY cr.article_reference, a.dossier_id
```

Quatre requêtes en tout, le regroupement se fait en mémoire. Idem pour le
contrôle des doublons : les notifications déjà émises sont chargées **en une
fois** dans un `set`, au lieu d'un `SELECT` par couple (dossier, article).

C'est le genre de problème qu'on ne voit qu'en exécutant : à l'écriture, une
boucle avec une requête dedans se lit très bien.

#### d) Le bug de niveau, invisible sans test

```python
if (document_type or "").lower().startswith("bo"):   # AVANT
```

Le corpus stocke le type `BULLETIN_OFFICIEL`, qui commence par « bu », pas
« bo ». **Toutes les notifications de Bulletin Officiel** — c'est-à-dire les
mesures **nouvelles**, celles qui comptent — se retrouvaient au niveau
« moyen », noyées parmi les simples consolidations du CGI. Exactement l'inverse
de l'objectif du module.

```python
if t.startswith("bulletin") or t.startswith("bo_") or t == "bo":   # APRÈS
```

#### e) Un doublon apparent qui n'en était pas un

Le test attendait 1 notification par dossier, il en trouvait 2. Vérification
faite dans le corpus : **« Article 2 » existe dans les deux documents** — le BO
n° 7465 bis (Loi de Finances 2026) et le CGI consolidé 2026 — et **28
références sont dans ce cas**.

Deux notifications est donc le comportement **correct**. C'est précisément la
distinction que l'architecture du projet interdit de fusionner : *« CGI = texte légal
consolidé, BO = provenance temporelle + déclencheur de veille. Ne jamais les
fusionner en une seule source. »* Lire une consolidation et apprendre une mesure
nouvelle n'appellent pas la même réaction.

**C'est le test qui a été corrigé, pas le code.** Et il ne code plus « 2 » en
dur : il lit le nombre de documents portant la référence.

#### f) L'index unique et le `COALESCE`

```sql
CREATE UNIQUE INDEX ux_veille_unique ON notification_veille
(dossier_id, article_corpus_reference, COALESCE(date_version, ''));
```

Le `COALESCE` n'est pas une coquetterie : **un index unique sur une colonne
NULL ne contraint rien en Postgres**. Deux lignes avec `date_version` à NULL
seraient considérées comme distinctes, et le doublon passerait — précisément le
cas des articles sans version datée.

#### g) La seule route du produit hors contexte tenant

```python
@router.post("/veille/diffuser")
def veille_diffuser(req: DiffusionVeilleRequest, db: Session = Depends(get_admin_db)):
```

Toutes les autres routes passent par `get_tenant_db`, qui pose le contexte RLS
d'**une** organisation. La diffusion doit écrire des notifications pour les
dossiers de **toutes** les organisations : sous contexte tenant, elle n'en
verrait qu'une.

C'est une exception, elle est **délibérée et commentée**, et son garde-fou est
le `require_role("admin_plateforme")` porté par le routeur entier. Le module
`veille.py` ne doit jamais être appelé depuis une route utilisateur.

`dry_run` vaut **True par défaut** : on regarde qui serait notifié avant de
notifier de vrais cabinets.

---

### 4. Flux complet des données

```
Corpus SQLite (corpus.db)                Postgres multi-tenant
   articles (statut = valide)               citation_risque
   documents (CGI | BULLETIN_OFFICIEL)      citation
        |                                    citation_simulation
        |                                    citation_proposition
        v                                          |
articles_nouveaux_depuis(since)                     |
        |                                          |
        | references[]                             |
        +----------------->  dossiers_concernes_par_lot()
                                    |     (4 requetes, pas 1600)
                                    v
                        {reference: {dossier_id: motif}}
                                    |
                                    v
                     deja notifie ? (1 SELECT global -> set)
                          |                |
                        OUI              NON
                          |                |
                    nb_deja_notifies       v
                                  INSERT notification_veille
                                  (niveau selon CGI vs BO,
                                   source_label, document_id,
                                   date_version, motif, lu=false)
                                          |
                                          v
                        GET /dossiers/{id}/veille  (get_tenant_db)
                                          |
                                          v
                                  VeillePage : badge CGI/BO,
                                  motif « pourquoi ce dossier »,
                                  pastille de citation cliquable
```

---

### 5. Lien avec le frontend

| Étape | Composant | Appel | Endpoint | JSON reçu | Impact UI |
|---|---|---|---|---|---|
| Diffusion (admin) | `AdminPage.jsx` *(à brancher)* | `apiFetch` | `POST /admin/veille/diffuser` | `{nb_articles_examines, nb_notifications, nb_dossiers_touches, apercu[]}` | Aperçu avant envoi réel (`dry_run: true` par défaut) |
| Liste des notifications | `VeillePage.jsx` | `dossierFetch` | `GET /dossiers/{id}/veille` | `{notifications[], nb_non_lues}` | Cartes, non-lues en gras, badge CGI ou Bulletin Officiel |
| Marquer comme lue | `VeillePage.jsx` | `dossierFetch` PATCH | `PATCH /dossiers/{id}/veille/{nid}` | notification | Opacité réduite, compteur décrémenté |
| Tout marquer lu | `VeillePage.jsx` | `dossierFetch` POST | `POST /dossiers/{id}/veille/tout-lu` | `{nb_marquees}` | Remise à zéro du compteur |

Le texte de l'article est lisible directement depuis la notification, via le
composant `CitationPills` **partagé avec l'audit et les corrections** : « cliquer
sur un article affiche son texte » se comporte pareil partout dans le produit,
y compris quand l'article a disparu du corpus.

---

### 6. Pourquoi cette architecture ?

**Ciblage par citations passées plutôt que par classement thématique LLM.**
Déterministe, gratuit, sans hallucination possible, et plus précis qu'un match
sur le secteur d'activité. Fondé sur l'historique réel du dossier plutôt que sur
une supposition.

**Message statique plutôt qu'« impact » rédigé par LLM.**
Alternative écartée : faire rédiger « voici l'impact sur votre dossier » par un
modèle. Rejetée parce que ce serait une **affirmation juridique produite sans
que personne ne l'ait demandée**, sur un article que l'utilisateur n'a pas
encore lu. La notification dit ce qui a changé et où le lire ; l'analyse reste
le travail de l'assistant, sur demande, avec ses citations. Gain accessoire :
zéro coût LLM sur un job qui tourne sur tout le corpus.

**Enrichir `notification_veille` plutôt que créer une table.**
La table existait depuis la phase 1 avec sa policy RLS, et n'avait jamais été
alimentée. En créer une autre aurait ajouté une policy à écrire et un risque de
l'oublier.

**`source_label` et `document_id` conservés.**
Ce sont eux qui préservent la distinction CGI / Bulletin Officiel exigée par
l'architecture. Sans eux, le cabinet ne pourrait pas savoir s'il lit une
reformulation ou une mesure nouvelle.

**Idempotence par index unique plutôt que par logique applicative seule.**
Le contrôle applicatif évite les erreurs d'insertion inutiles ; l'index garantit
qu'aucun chemin de code, présent ou futur, ne pourra créer un doublon.

---

### 7. Lien avec le cahier des charges

Répond au **module 6 — Veille personnalisée** : *« lecture loi de finances +
notes DGI, signalement de l'impact sur le dossier avec action à mener »*
([`cahier-des-charges.md:44-45`](../cahier-des-charges.md#L44-L45)).

Le mot **« personnalisée »** est ici pris au sérieux : ce n'est pas une
newsletter filtrée par secteur, c'est un ciblage sur l'historique documenté de
chaque dossier. Le test le prouve avec un **dossier témoin** qui n'a jamais cité
l'article et ne reçoit rien — sans ce témoin, le test ne prouverait rien.

**Ce qui n'est pas fait :** le canal de poussée (e-mail, WhatsApp) mentionné au
périmètre. Les notifications sont consultables dans l'application ; leur envoi
sortant reste à brancher.

---

### 8. Ce que je dois retenir pour la soutenance

- La phrase : **si ce cabinet a déjà eu besoin de l'article 106 sur ce dossier, un changement de l'article 106 le concerne.**
- Ciblage sur les **4 tables de citations** du produit — aucun LLM, aucune hallucination possible, fondé sur l'historique réel.
- Le **motif est persisté** : « cité dans 2 alertes de risque ». La veille doit se justifier, comme le reste du produit.
- Bug de performance trouvé en testant : **plus de 1 600 requêtes** vers une base distante. Réécrit en 4 requêtes par lots.
- Bug de classement trouvé en testant : le corpus dit `BULLETIN_OFFICIEL`, le code testait `startswith("bo")` → **toutes les mesures nouvelles étaient rétrogradées** au niveau moyen.
- Deux notifications pour « Article 2 » n'était **pas** un doublon : l'article existe dans le BO **et** dans le CGI consolidé (28 références dans ce cas). C'est la distinction que l'architecture interdit de fusionner. Test corrigé, pas le code.
- `COALESCE(date_version, '')` dans l'index unique : un index unique sur NULL **ne contraint rien** en Postgres.
- Seule route du produit hors `get_tenant_db` — délibérée, commentée, protégée par `admin_plateforme`, et `dry_run` par défaut.

---

### 9. Questions probables du jury

**Pourquoi ne pas classer les articles par thème pour cibler les dossiers ?**
Ça coûterait un appel LLM par article, introduirait une erreur de classement
possible, et serait moins précis : deux sociétés du même secteur n'ont pas les
mêmes problèmes fiscaux. Le ciblage par citations est fondé sur ce que le
dossier a réellement rencontré.

**Comment prouvez-vous que le ciblage est correct ?**
Par un dossier **témoin** dans le test : il existe, il appartient à la même
organisation, mais il n'a jamais cité l'article — et il ne reçoit rien. Sans ce
témoin, on prouverait seulement que des notifications sont créées, pas
qu'elles sont ciblées.

**Pourquoi le même article génère-t-il deux notifications ?**
Parce qu'il existe dans deux couches distinctes du corpus : le Bulletin
Officiel (mesure nouvelle, datée) et le CGI consolidé (texte en vigueur).
L'architecture interdit de les fusionner — ce sont deux informations
différentes pour le cabinet.

**Pourquoi cette route n'utilise-t-elle pas la RLS comme les autres ?**
Parce qu'elle doit écrire pour toutes les organisations à la fois, ce que le
contexte RLS interdit par construction. C'est la seule exception du produit,
elle est commentée dans le code, et elle est réservée au rôle
`admin_plateforme`.

**Que se passe-t-il si on relance la diffusion ?**
Rien de nouveau n'est créé. L'idempotence est garantie à deux niveaux : un
contrôle applicatif sur un `set` chargé en une requête, et un index unique en
base qui couvre le cas d'un chemin de code futur.

---

### 10. Étapes de test dans l'application

1. Poser une question à l'**Assistant IA** sur un dossier, par exemple sur la
   TVA déductible → une ligne `citation` est créée pour ce dossier.
2. Se connecter en `admin_plateforme` et lancer la diffusion en simulation :
   `POST /admin/veille/diffuser` avec `{"dry_run": true}`.
   Vérifier dans `apercu[]` que **seuls** les dossiers ayant cité les articles
   apparaissent.
3. Relancer avec `{"dry_run": false}` → les notifications sont créées.
4. Revenir sur le dossier, onglet **Veille fiscale** : les notifications
   apparaissent, non lues, avec le badge **CGI** ou **Bulletin Officiel** et la
   ligne « Pourquoi ce dossier : cité dans 1 réponse de l'assistant ».
5. Cliquer sur la pastille d'article → le texte de loi s'affiche.
6. Relancer la diffusion une troisième fois → `nb_notifications` vaut **0**,
   `nb_deja_notifies` est renseigné, aucun doublon n'apparaît dans la liste.

Ou, en une commande depuis `backend/` : `python test_veille.py`
(22 contrôles, dont le dossier témoin et l'idempotence).

---

## 18. Assistant bilingue français / arabe-darija

### 1. Vue d'ensemble

Le cahier des charges annonce au périmètre : *« Langues (v1) : français et arabe
(darija pour l'assistant conversationnel) »*. La parenthèse est importante —
elle rattache explicitement l'arabe à **l'assistant**, pas à l'interface.

Ce flux fait donc trois choses :

1. **Détecter** la langue de la question (français, arabe, darija translittérée).
2. **Traduire la requête de recherche** vers le français avant d'interroger le
   corpus — parce qu'une mesure a montré que c'était indispensable.
3. **Rédiger la réponse** dans la langue de l'utilisateur, en gardant les
   citations légales **en français, mot pour mot**.

Le point 2 n'était pas prévu au plan. Il est le résultat d'une mesure faite
**avant** d'écrire le reste du bloc, et c'est probablement la partie la plus
intéressante de ce flux pour une soutenance.

---

### 2. Où cela apparaît dans le code

| Fichier | Élément | Rôle |
|---|---|---|
| `backend/app/langue.py` | `detecter_langue()`, `est_arabe()` | 3 issues : `fr`, `ar`, `ar_latin` |
| `backend/app/rag_retrieval.py` | `QUERY_REFORMULATION_SYSTEM_PROMPT` | La reformulation traduit désormais vers le français |
| `backend/app/rag_retrieval.py` | `retrieve_sourced_articles(..., langue)` | Signale une recherche dégradée si la reformulation échoue |
| `backend/app/generation.py` | `_CONSIGNE_ARABE`, `generate_answer(..., langue)` | Réponse en arabe, citations en français |
| `backend/app/routes_dossiers.py` | `chat()` | Détection + renvoi de `langue` |
| `backend/app/api.py` | `chat_general()` | Idem pour le chat hors dossier |
| `frontend/src/pages/ChatPage.jsx` | bulle + indice | `dir="rtl"` sur la seule réponse |
| `frontend/src/App.css` | `.bubble.msg-ar` | Police arabe, sens d'écriture |
| `backend/test_langue.py` | 20 contrôles | Détection + mesure du rappel cross-lingue |

---

### 3. Explication détaillée du code

#### a) La mesure qui a changé la conception

Le plan supposait que `multilingual-e5-base`, étant un modèle cross-lingue,
retrouverait les articles français depuis une question arabe. **Mesuré sur ce
corpus : 13 % de recouvrement** entre les résultats d'une même question posée en
français et en arabe.

Le point important n'est pas le chiffre bas. C'est **la façon dont ça échoue** :
le modèle ne plante pas, il retrouve *d'autres* articles, plausibles, mais pas
les bons. La réponse serait alors **sourcée et fausse** — le pire résultat
possible pour un produit dont l'argument est la vérifiabilité.

#### b) La correction ne coûte aucun appel supplémentaire

L'étape de reformulation de requête existait déjà et tourne à chaque question.
Il a suffi de lui ajouter une règle :

```
- La requête doit TOUJOURS être en FRANÇAIS, même si la question est posée en
  arabe, en darija ou dans une autre langue. Le corpus interrogé est
  exclusivement en français.
```

Coût marginal nul, un seul endroit à comprendre. L'alternative — ajouter un
appel de traduction dédié — aurait doublé la latence pour le même résultat.

#### c) Le témoin, et ce qu'il révèle

Le seuil « 50 % de recouvrement » que je m'étais fixé était arbitraire. La
métrique elle-même est fragile : deux formulations différentes d'une même
question ne remontent jamais exactement le même top-5, **même dans la même
langue**. Il fallait donc mesurer ce plancher de bruit avant de conclure.

| Mesure | Recouvrement top-5 |
|---|---|
| Deux formulations **françaises** de la même question (témoin) | **33 %** |
| Arabe brut, sans traduction | 27 % |
| Arabe traduit — le pipeline réel | **53 %** |

L'arabe traduit **dépasse** une reformulation française. L'explication : le
chemin arabe passe par la reformulation, qui normalise la question dans le
vocabulaire juridique du corpus ; le témoin français, lui, attaquait la
recherche directement.

**La reformulation pèse donc plus lourd que la barrière de langue.** Et le
« 13 % » initial mesurait en partie l'absence de reformulation, pas seulement
l'arabe. C'est un résultat qui se présente tel quel : une hypothèse, une mesure
qui la contredit, un témoin qui explique pourquoi, une correction à coût nul.

#### d) Pourquoi pas une librairie de détection de langue

`langdetect` ou `fasttext` pèsent environ 1 Mo et un modèle statistique, pour
résoudre ici un problème à trois issues dont deux se décident sur l'alphabet.

Mais surtout : **aucune librairie généraliste ne reconnaît la darija en
caractères latins** (« chhal ghadi n7ess f TVA »), qui est précisément le cas
d'usage nommé par le cahier des charges. Elle serait classée « français »,
« turc » ou « indonésien » selon les jours.

```python
_ARABE = re.compile(r"[؀-ۿ]")
SEUIL_ARABE = 0.30
MIN_MARQUEURS_DARIJA = 2
```

Le seuil de 30 % de caractères arabes est atteint dès qu'une phrase est
réellement en arabe, et jamais par une question française qui citerait un mot
arabe isolé. Il tolère qu'une question arabe contienne « TVA », « IS » et des
chiffres — exiger une majorité de caractères arabes raterait ces cas.

Les **deux marqueurs minimum** pour la darija évitent qu'un nom propre déclenche
la détection : le test vérifie que « la société Safi Industries » reste du
français.

#### e) La règle non négociable sur les citations

```
- **Garde EN FRANÇAIS, mot pour mot** : les références d'articles, les intitulés
  officiels d'articles, et toute citation littérale du texte de loi.
```

Traduire une citation légale produirait une **paraphrase présentée comme du
texte de loi**. L'utilisateur ne pourrait plus vérifier la réponse contre la
source, et c'est exactement la garantie que vend le produit. Une paraphrase
arabe de l'article 106 n'est pas l'article 106 — devant un contrôle, elle ne
vaut rien.

C'est aussi ce qui rend cohérente la décision de **ne pas traduire les 401
articles du corpus** : ce n'est pas une économie de travail, c'est le refus
d'introduire une couche non vérifiable entre le texte légal et l'utilisateur.

L'assistant peut expliquer en arabe ce que dit un article ; la citation
elle-même reste en français, entre guillemets.

#### f) Aucun sélecteur de langue

La langue est détectée sur la question, pas choisie dans un menu. Un dirigeant
de PME qui écrit `chhal ghadi nkhalles f TVA had chher` n'a **rien à
configurer** — et c'est plus convaincant en démonstration qu'un bouton
`FR / ع`, tout en étant zéro état à gérer.

Côté interface, seule la **bulle de réponse** bascule en RTL avec la police
arabe. L'interface reste en français : les références d'articles à l'intérieur
de la bulle s'affichent correctement grâce à l'algorithme bidirectionnel natif
des navigateurs.

#### g) Le mode dégradé est signalé

```python
if est_arabe(langue):
    print(f"[RAG-CHAT] {label} — reformulation indisponible sur une question en {langue} : "
          "recherche dégradée, la question n'a pas pu être traduite en français.")
```

Si la reformulation échoue (quota LLM épuisé), on retombe sur la question brute.
Acceptable en français ; pour une question arabe c'est une recherche à 27 % de
rappel. On le **signale** plutôt que de laisser croire à un fonctionnement
normal.

---

### 4. Flux complet des données

```
Utilisateur tape : "chhal ghadi nkhalles f TVA had chher ?"
     |
     v
POST /dossiers/{id}/chat   {query, top_k}
     |
     v
detecter_langue(query)
     |   ratio de caracteres arabes >= 0.30 ?  --> 'ar'
     |   >= 2 marqueurs darija latins ?        --> 'ar_latin'
     |   sinon                                 --> 'fr'
     v
langue = 'ar_latin'
     |
     v
retrieve_sourced_articles(store, query, langue='ar_latin')
     |
     +-- _reformulate_question()   ---> "conditions de deduction de la TVA
     |        (traduit vers le FR)        sur les achats du mois"
     |        echec ? --> log de recherche degradee
     |
     +-- store.search(requete_francaise)   --> candidats
     |
     +-- filter_relevant_articles_for_question()   --> articles pertinents
     v
generate_answer(query, sources, langue='ar_latin')
     |
     +-- SYSTEM_PROMPT + _CONSIGNE_ARABE
     |      . repondre en darija
     |      . titres de sections traduits
     |      . references et citations EN FRANCAIS, mot pour mot
     |      . montants en chiffres occidentaux + DH
     v
{query, answer, sources[], langue: 'ar_latin'}
     |
     v
ChatPage : <div dir="rtl" class="bubble msg-ar">
           (seule la bulle ; l'interface reste en francais)
     |
     v
Citation persistee (table citation) --> alimente la veille du flux 17
```

---

### 5. Lien avec le frontend

| Étape | Composant | Appel | Endpoint | JSON reçu | Impact UI |
|---|---|---|---|---|---|
| Question posée | `ChatPage.jsx` | `dossierFetch` | `POST /dossiers/{id}/chat` | `{answer, sources[], langue}` | La bulle passe en RTL si `langue` vaut `ar` ou `ar_latin` |
| Chat hors dossier | `GlobalCopilot.jsx` | `apiFetch` | `POST /chat/general` | idem | Même mécanique |
| Indice d'usage | `ChatPage.jsx` | — | — | — | Ligne discrète sous le champ : « Posez votre question en français, en arabe ou en darija — les références légales restent citées en français » |

Cette ligne d'indice est le seul élément d'interface ajouté par le flux. Elle
sert deux fois : elle **révèle la capacité** (sans elle, personne ne penserait à
écrire en darija) et elle **explique la limite** au seul endroit où
l'utilisateur en a besoin.

---

### 6. Pourquoi cette architecture ?

**L'assistant seulement, pas l'interface.**
Deux raisons, et les deux se défendent. D'abord le cahier des charges le scope
lui-même (« darija pour l'assistant conversationnel »). Ensuite la réalité
métier marocaine : la comptabilité d'entreprise est en français de bout en bout
— factures, plan comptable CGNC, télédéclarations SIMPL. Un collaborateur de
cabinet qui saisit des écritures n'a **aucun usage** d'une sidebar en arabe.

Traduire l'interface aurait coûté environ 4,5 jours de plus (~350 chaînes sur
15 pages, balayage RTL du CSS, plus un jour pour rendre les prompts d'audit
multilingues — le contenu généré par un LLM n'étant pas atteignable par un
dictionnaire). Pour un gain nul sur la population qui saisit réellement des
données.

**La traduction portée par la reformulation plutôt qu'un appel dédié.**
La reformulation tournait déjà à chaque question. Lui confier la traduction
coûte zéro appel supplémentaire et laisse un seul endroit à comprendre.

**Une règle de 20 lignes plutôt qu'une librairie.**
Aucune librairie généraliste ne reconnaît la darija translittérée, qui est le
cas d'usage principal. Et sur un projet où chaque ligne doit pouvoir être
expliquée à l'oral, une règle qu'on comprend bat un modèle qu'on subit.

**Détection automatique plutôt que sélecteur.**
Zéro configuration pour l'utilisateur, zéro état à gérer côté application, et
plus démonstratif.

**Citations jamais traduites.**
Non négociable : c'est la vérifiabilité, donc le cœur du produit.

---

### 7. Lien avec le cahier des charges

Répond au **périmètre linguistique** : *« Langues (v1) : français et arabe
(darija pour l'assistant conversationnel) »*
([`cahier-des-charges.md:24`](../cahier-des-charges.md#L24)).

La lecture retenue — arabe pour l'assistant, français pour l'interface — n'est
pas un arbitrage de temps déguisé : elle est **écrite dans la parenthèse du
cahier des charges**. C'est la formulation à utiliser si un jury demande
pourquoi l'interface n'est pas traduite.

Sert aussi le **module 7** en rendant l'assistant réellement utilisable par la
cible `dirigeant_pme`, qui n'est pas un professionnel de la fiscalité et ne
formule pas ses questions en français technique.

---

### 8. Ce que je dois retenir pour la soutenance

- Le cahier des charges **scope lui-même** l'arabe à l'assistant conversationnel — la parenthèse de la ligne 24. Ce n'est pas un raccourci.
- Justification métier : la comptabilité marocaine est en français de bout en bout (CGNC, SIMPL, factures). Le besoin d'arabe est **conversationnel**, côté dirigeant de PME.
- **13 %** de recouvrement cross-lingue mesuré : le modèle ne plante pas, il retrouve *d'autres* articles. La réponse serait **sourcée et fausse** — la pire façon d'échouer.
- La correction coûte **zéro appel** : la reformulation, qui tournait déjà, traduit désormais vers le français.
- Le témoin renverse la lecture : deux formulations **françaises** ne partagent que **33 %** ; l'arabe traduit atteint **53 %**, donc **dépasse** le français. **La reformulation pèse plus lourd que la langue.**
- Les citations restent en français **mot pour mot** : une paraphrase arabe de l'article 106 n'est pas l'article 106.
- Pas de librairie de détection : aucune ne reconnaît la darija translittérée, qui est le cas d'usage principal.
- Pas de sélecteur : la langue est détectée, l'utilisateur n'a rien à configurer.

---

### 9. Questions probables du jury

**Pourquoi l'interface n'est-elle pas traduite en arabe ?**
Parce que le cahier des charges rattache l'arabe à l'assistant conversationnel,
et parce que la comptabilité marocaine est en français de bout en bout. Un
collaborateur qui saisit des écritures en français n'a pas d'usage d'une sidebar
en arabe. Le besoin réel est celui du dirigeant de PME qui pose une question en
darija — et c'est exactement là que la fonctionnalité a été mise.

**Comment savez-vous que le modèle d'embedding ne suffisait pas ?**
Je l'ai mesuré avant d'écrire le code : 13 % de recouvrement entre une question
française et sa traduction arabe. Le protocole et les chiffres sont dans
`test_langue.py` et rejouables.

**53 % de recouvrement, c'est faible, non ?**
C'est ce que j'ai cru aussi, jusqu'à mesurer le plancher de bruit : deux
formulations françaises différentes de la même question ne partagent que 33 %.
L'arabe traduit fait donc mieux que le français reformulé. La métrique de
recouvrement mesure surtout la variabilité de formulation, pas la qualité.

**Pourquoi ne pas traduire le corpus en arabe ?**
Parce qu'une citation traduite est une paraphrase. L'utilisateur ne pourrait
plus vérifier la réponse contre le texte officiel, ce qui détruit la garantie
centrale du produit. Ce n'est pas une économie de travail, c'est un refus.

**Votre détection de langue fait 20 lignes — est-ce fiable ?**
Pour trois issues dont deux se décident sur l'alphabet, oui. Et aucune librairie
généraliste ne reconnaît la darija en caractères latins, qui est le cas d'usage
principal : elle serait classée « français » ou « turc ». Les faux positifs sont
testés, notamment les noms propres comme « Safi ».

---

### 10. Étapes de test dans l'application

1. Ouvrir **Assistant IA** sur un dossier. Vérifier la présence de la ligne
   d'indice sous le champ de saisie.
2. Poser une question en **français** :
   *« Quelles charges ne sont pas déductibles du résultat fiscal ? »*
   → réponse en français, mise en page normale (gauche à droite).
3. Poser la même question en **darija translittérée** :
   *« chnou hiya les charges li ma kaynach deduction dyalhom ? »*
   → réponse en darija, bulle en **RTL**, police arabe.
4. Vérifier dans cette réponse que :
   - les titres de sections sont en arabe,
   - **les références d'articles sont en français** (« Article 11 du CGI »),
   - les montants sont en chiffres occidentaux suivis de « DH ».
5. Poser une question en **arabe standard** :
   *« ما هي شروط خصم الضريبة على القيمة المضافة؟ »* → même comportement.
6. Vérifier qu'une question française contenant un nom propre marocain
   (« La société Safi Industries est-elle concernée ? ») reste bien traitée en
   **français**.

Ou, en une commande depuis `backend/` : `python test_langue.py`
(détection + mesure du rappel cross-lingue avec le témoin).
