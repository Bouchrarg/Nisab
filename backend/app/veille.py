"""
veille.py — Diffusion ciblée des évolutions du corpus vers les dossiers.

## Le problème que ça résout

Le pipeline de veille détecte des Bulletins Officiels, en extrait des articles,
les valide. Jusqu'ici cette information restait dans le corpus : personne au
cabinet n'apprenait qu'un article qu'il utilise avait bougé. Le Module 6 du
cahier des charges demande exactement l'inverse — « signalement de l'impact sur
le dossier avec action à mener ».

## Comment on décide qu'un dossier est concerné

**Par ses citations passées, pas par des mots-clés sectoriels.**

Un article nouvellement validé concerne un dossier si ce dossier a DÉJÀ cité
cette référence, à travers l'une des quatre traces que le produit persiste :

    citation_risque       -> une alerte d'audit s'appuyait dessus
    citation              -> l'assistant l'a cité dans une réponse
    citation_simulation   -> une simulation de contrôle l'a invoqué
    citation_proposition  -> une correction proposée s'y fondait

C'est déterministe, sans appel LLM, donc sans hallucination possible. Et c'est
authentiquement personnalisé : fondé sur ce que ce dossier a réellement
rencontré, pas sur une supposition à partir de son secteur d'activité.

L'alternative (classer les articles par thème, puis matcher sur
`dossier.secteur_activite`) aurait demandé un classement LLM de chaque article,
avec le risque d'erreur que ça implique, pour un résultat moins précis : deux
sociétés du même secteur n'ont pas les mêmes problèmes fiscaux.

## Pourquoi ce module utilise get_admin_db

Toutes les autres routes du produit passent par `get_tenant_db`, qui pose le
contexte RLS d'UNE organisation. La diffusion doit écrire des notifications
pour les dossiers de TOUTES les organisations : sous contexte tenant, elle n'en
verrait qu'une. C'est la seule exception du produit, et elle est délibérée —
d'où ce commentaire plutôt qu'un silence.

La contrepartie : ce module ne doit JAMAIS être appelé depuis une route
utilisateur. Il est réservé à `/admin/veille/diffuser`, gated
`admin_plateforme`.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

#: Les quatre tables de citations du produit, avec le chemin pour remonter au
#: dossier et le libellé affiché à l'utilisateur. Ajouter une cinquième forme
#: de citation un jour = ajouter une ligne ici, rien d'autre.
#:
#: Chaque requête est écrite pour un LOT de références (`= ANY(:refs)`) et non
#: pour une seule. La version initiale interrogeait article par article : sur
#: 401 articles de corpus × 4 sources, ça faisait plus de 1 600 allers-retours
#: vers une base distante, et la diffusion dépassait deux minutes. Ici c'est
#: quatre requêtes en tout, le regroupement se fait en mémoire.
_SOURCES_CITATION = [
    (
        "alerte de risque",
        """SELECT cr.article_reference AS ref, a.dossier_id AS dossier_id, count(*) AS n
           FROM citation_risque cr
           JOIN alerte_risque a ON a.id = cr.alerte_id
           WHERE cr.article_reference = ANY(:refs) AND a.actif = true
           GROUP BY cr.article_reference, a.dossier_id""",
    ),
    (
        "réponse de l'assistant",
        """SELECT c.article_reference AS ref, c.dossier_id AS dossier_id, count(*) AS n
           FROM citation c
           WHERE c.article_reference = ANY(:refs)
           GROUP BY c.article_reference, c.dossier_id""",
    ),
    (
        "simulation de contrôle",
        """SELECT cs.article_reference AS ref, s.dossier_id AS dossier_id, count(*) AS n
           FROM citation_simulation cs
           JOIN simulation_controle s ON s.id = cs.simulation_id
           WHERE cs.article_reference = ANY(:refs)
           GROUP BY cs.article_reference, s.dossier_id""",
    ),
    (
        "proposition de correction",
        """SELECT cp.article_reference AS ref, p.dossier_id AS dossier_id, count(*) AS n
           FROM citation_proposition cp
           JOIN proposition_correction p ON p.id = cp.proposition_id
           WHERE cp.article_reference = ANY(:refs)
           GROUP BY cp.article_reference, p.dossier_id""",
    ),
]


def articles_nouveaux_depuis(corpus_db_path: str, since_iso: str | None) -> list[dict]:
    """
    Articles validés du corpus, éventuellement filtrés sur leur date d'extraction.

    `since_iso = None` renvoie tout le corpus validé : c'est le mode « première
    diffusion », utile pour amorcer la veille sur un corpus déjà constitué. En
    exploitation courante on passe la date du dernier run.

    Ce filtre est un bookkeeping OPÉRATIONNEL (« qu'est-ce que ce run n'a pas
    encore vu ») — il ne dit rien sur le contenu. `texte` est inclus dans le
    SELECT précisément pour que `filtrer_changements_reels` puisse comparer ce
    contenu à la version précédente et écarter les republications inchangées.
    """
    conn = sqlite3.connect(corpus_db_path)
    conn.row_factory = sqlite3.Row
    try:
        requete = """
            SELECT a.reference, a.texte, a.source_label, a.date_version, a.date_extraction,
                   a.document_id, d.label AS document_label, d.type AS document_type
            FROM articles a
            LEFT JOIN documents d ON d.id = a.document_id
            WHERE a.statut = 'valide'
        """
        params: tuple = ()
        if since_iso:
            requete += " AND a.date_extraction > ?"
            params = (since_iso,)
        requete += " ORDER BY a.date_extraction DESC"
        return [dict(r) for r in conn.execute(requete, params)]
    finally:
        conn.close()


def _version_precedente(
    conn: sqlite3.Connection,
    reference: str,
    document_id: str | None,
    document_type: str | None,
    date_version: str | None,
) -> dict | None:
    """
    La version validée la plus récente de `reference` portée par un AUTRE
    document DU MÊME TYPE, strictement antérieure en `date_version`.

    Borner sur `date_version` (chronologie légale) et non sur `date_extraction`
    (chronologie du pipeline) est le point qui rend ça correct en cas de
    backfill : ajouter le CGI 2024 après que le CGI 2026 existe déjà lui donne
    un `date_extraction` plus RÉCENT que 2026 alors qu'il est légalement plus
    ANCIEN. Borner sur `date_extraction` ferait comparer 2024 contre 2026 comme
    si 2026 était "avant" 2024 — faux. `date_version < ?` encode directement
    l'invariante voulue, backfill ou pas, et fait que deux documents insérés
    dans le même run se comparent chacun à leur propre prédécesseur légal,
    jamais l'un à l'autre.

    Le filtre `document_type` existe parce qu'un Bulletin Officiel et le CGI
    ne partagent PAS le même espace de numérotation d'articles : vérifié sur
    le corpus réel, le "Article 2" d'un Bulletin Officiel est un article de la
    LOI DE FINANCES elle-même (ses propres dispositions budgétaires), pas
    l'article 2 du CGI qu'elle amende — les deux textes n'ont rien à voir,
    ils partagent juste un numéro par coïncidence. Les comparer produirait un
    "a changé depuis X vers Y" qui affirme un lien causal faux entre deux
    textes sans rapport. Cf. règle d'architecture du projet : CGI et BO sont
    deux couches distinctes, jamais à fusionner — y compris ici, dans la
    comparaison de contenu, pas seulement dans le stockage.

    `None` si aucune version comparable n'existe (référence sans document_id,
    sans date_version, ou véritable première apparition dans le corpus).
    """
    if not document_id or not date_version:
        return None
    ligne = conn.execute(
        """
        SELECT a2.texte, a2.document_id, d2.label AS document_label, a2.date_version
        FROM articles a2
        JOIN documents d2 ON d2.id = a2.document_id
        WHERE a2.reference = ? AND a2.statut = 'valide'
          AND a2.document_id != ? AND d2.type = ? AND a2.date_version IS NOT NULL
          AND a2.date_version < ?
        ORDER BY a2.date_version DESC
        LIMIT 1
        """,
        (reference, document_id, document_type, date_version),
    ).fetchone()
    return dict(ligne) if ligne else None


def _existe_version_plus_recente(
    conn: sqlite3.Connection,
    reference: str,
    document_id: str | None,
    document_type: str | None,
    date_version: str | None,
) -> bool:
    """
    Vrai s'il existe déjà, dans le corpus, une version validée PLUS RÉCENTE de
    cette référence (même type de document, autre document_id).

    Sert à ne jamais traiter un BACKFILL comme un changement à signaler.
    Trouvé en testant contre le vrai corpus : ajouter le CGI 2024 après que
    2025 et 2026 existaient déjà faisait ressortir ses articles comme
    "première apparition" (rien de plus ANCIEN à comparer) et donc "changés"
    — alors que 2025/2026, déjà connus et déjà cités, sont plus récents que ce
    qu'on vient d'ajouter. La veille doit alerter quand le front de la
    chronologie légale AVANCE, jamais quand on complète l'historique derrière.
    """
    if not document_id or not date_version:
        return False
    ligne = conn.execute(
        """
        SELECT 1 FROM articles a2
        JOIN documents d2 ON d2.id = a2.document_id
        WHERE a2.reference = ? AND a2.statut = 'valide'
          AND a2.document_id != ? AND d2.type = ? AND a2.date_version IS NOT NULL
          AND a2.date_version > ?
        LIMIT 1
        """,
        (reference, document_id, document_type, date_version),
    ).fetchone()
    return ligne is not None


def filtrer_changements_reels(corpus_db_path: str, articles: list[dict]) -> tuple[list[dict], int, int]:
    """
    Ne garde que les articles qui représentent une AVANCÉE réelle de la
    chronologie légale — pas juste ceux qui viennent d'être (ré)extraits, ni
    un backfill qui complète l'historique derrière ce qui est déjà connu.

    Sans le premier filtre, réextraire un PDF sans aucune modification
    produirait quand même une notification « a été mis à jour », ce qui
    serait faux : `date_extraction` ne dit que « quand le pipeline a tourné »,
    jamais « si le contenu a bougé ». Sans le second, backfiller une année
    plus ancienne après coup (ex: ajouter le CGI 2024 alors que 2025/2026 sont
    déjà validés) déclencherait des notifications pour des dossiers déjà à
    jour — vérifié sur le corpus réel, c'est exactement ce qui arrivait.

    Comparaison en égalité brute, pas en hash : contrairement à
    `ingest_to_supabase.py::texte_hash`, qui persiste son hash pour éviter de
    re-comparer le texte complet à chaque futur run, cette comparaison est
    éphémère (un seul appel, dans un seul run de diffusion) — un hash n'y
    apporterait rien qu'une égalité de chaînes Python.

    Une référence sans version antérieure comparable (première apparition, et
    rien de plus récent déjà validé) est gardée par défaut : un dossier ne
    peut être ciblé que s'il a déjà cité cette référence, donc ce cas est
    rare, et le choix conservateur est de ne jamais avaler silencieusement un
    changement potentiel plutôt que de risquer un faux négatif.

    Retourne (articles_changes, nb_inchanges, nb_deja_depasses).
    """
    conn = sqlite3.connect(corpus_db_path)
    conn.row_factory = sqlite3.Row
    try:
        changes: list[dict] = []
        nb_inchanges = 0
        nb_deja_depasses = 0
        for article in articles:
            if _existe_version_plus_recente(
                conn, article["reference"], article.get("document_id"),
                article.get("document_type"), article.get("date_version"),
            ):
                nb_deja_depasses += 1
                continue
            precedente = _version_precedente(
                conn, article["reference"], article.get("document_id"),
                article.get("document_type"), article.get("date_version"),
            )
            if precedente is None:
                article["premiere_apparition"] = True
                changes.append(article)
                continue
            if precedente["texte"] == article.get("texte"):
                nb_inchanges += 1
                continue
            article["premiere_apparition"] = False
            article["document_precedent_id"] = precedente["document_id"]
            article["document_precedent_label"] = precedente["document_label"]
            article["date_version_precedente"] = precedente["date_version"]
            changes.append(article)
        return changes, nb_inchanges, nb_deja_depasses
    finally:
        conn.close()


def dossiers_concernes_par_lot(db: Session, references: list[str]) -> dict[str, dict[uuid.UUID, str]]:
    """
    Pour un lot de références, quels dossiers les ont déjà citées et pourquoi.

    Retourne {reference: {dossier_id: "Cité dans 2 alertes de risque, …"}}.

    Le motif n'est pas cosmétique : il est persisté sur la notification, parce
    que la veille doit pouvoir se justifier auprès de l'utilisateur au même
    titre que le reste du produit. « Vous recevez ceci parce que cet article
    fonde 2 alertes sur ce dossier » est vérifiable ; « cet article pourrait
    vous concerner » ne l'est pas.
    """
    if not references:
        return {}

    # {reference: {dossier_id: [morceaux de motif]}}
    brut: dict[str, dict[uuid.UUID, list[str]]] = {}

    for libelle, requete in _SOURCES_CITATION:
        try:
            lignes = db.execute(text(requete), {"refs": references}).fetchall()
        except Exception:
            # Une table de citations absente (migration non appliquée sur un
            # environnement donné) ne doit pas faire échouer toute la diffusion.
            continue
        for ref, dossier_id, n in lignes:
            brut.setdefault(ref, {}).setdefault(dossier_id, []).append(
                f"{n} {libelle}{'s' if n > 1 else ''}"
            )

    return {
        ref: {d: "Cité dans " + ", ".join(parts) for d, parts in par_dossier.items()}
        for ref, par_dossier in brut.items()
    }


def dossiers_concernes(db: Session, reference: str) -> dict[uuid.UUID, str]:
    """Variante à une seule référence, pour lecture et tests."""
    return dossiers_concernes_par_lot(db, [reference]).get(reference, {})


def _niveau_pour(document_type: str | None) -> str:
    """
    Gravité affichée. Un Bulletin Officiel porte une mesure nouvelle et datée ;
    une consolidation du CGI reformule du texte déjà en vigueur. Les deux ne
    méritent pas la même mise en avant.

    La détection cherche « bulletin » ET « bo » : le corpus stocke le type
    `BULLETIN_OFFICIEL`, qu'un `startswith("bo")` manquait silencieusement —
    toutes les notifications de BO se retrouvaient au niveau « moyen », donc
    noyées parmi les consolidations, exactement l'inverse de l'objectif.
    """
    t = (document_type or "").strip().lower()
    if t.startswith("bulletin") or t.startswith("bo_") or t == "bo":
        return "eleve"
    return "moyen"


def _message_pour(article: dict, motif: str) -> str:
    """
    Message statique, construit à partir de faits vérifiables uniquement.

    Aucun LLM n'intervient ici. On pourrait faire rédiger un « impact sur votre
    dossier » par un modèle, mais ce serait une affirmation juridique produite
    sans que personne ne l'ait demandée, sur un article que l'utilisateur n'a
    pas encore lu. La notification dit ce qui a changé et où le lire ; l'analyse
    reste le travail de l'assistant, sur demande, avec ses citations.

    Si une version antérieure a été identifiée (`filtrer_changements_reels`),
    on la nomme explicitement — « a changé depuis X vers Y » est une
    affirmation vérifiable, plus honnête que le générique « a été mis à jour ».
    """
    source = article.get("document_label") or article.get("source_label") or "le corpus fiscal"
    version = f" (version {article['date_version']})" if article.get("date_version") else ""
    if article.get("premiere_apparition") is False and article.get("document_precedent_label"):
        version_precedente = (
            f" (version {article['date_version_precedente']})" if article.get("date_version_precedente") else ""
        )
        origine = f"{article['reference']} a changé depuis {article['document_precedent_label']}{version_precedente} vers {source}{version}."
    else:
        origine = f"{article['reference']} a été mis à jour dans {source}{version}."
    return f"{origine} {motif} sur ce dossier — vérifiez si l'analyse existante reste valable."


def diffuser(
    db: Session,
    corpus_db_path: str,
    since_iso: str | None = None,
    dry_run: bool = False,
    limite_articles: int | None = None,
) -> dict:
    """
    Crée une notification par (dossier, article) concerné.

    Idempotent : l'index unique `ux_veille_unique` (dossier, référence,
    version) empêche les doublons, et on vérifie en amont pour ne pas générer
    d'erreurs d'insertion inutiles. Relancer la diffusion deux fois ne produit
    donc rien la seconde fois.

    `dry_run` calcule tout et n'écrit rien : indispensable pour vérifier le
    ciblage avant d'envoyer des notifications à de vrais cabinets.
    """
    articles_bruts = articles_nouveaux_depuis(corpus_db_path, since_iso)
    if limite_articles:
        articles_bruts = articles_bruts[:limite_articles]
    # Écarte les republications sans changement de texte et les backfills déjà
    # dépassés par une version plus récente, AVANT de solliciter Postgres : ni
    # le ciblage par citation ni l'insertion n'ont de raison de tourner sur
    # une référence dont le contenu n'a pas bougé ou qui est de l'histoire.
    articles, nb_articles_inchanges, nb_articles_deja_depasses = filtrer_changements_reels(
        corpus_db_path, articles_bruts
    )

    references = list({a["reference"] for a in articles})
    cibles_par_reference = dossiers_concernes_par_lot(db, references)

    # Notifications déjà émises, chargées en une fois. Un SELECT par couple
    # (dossier, article) aurait multiplié les allers-retours par le nombre de
    # cibles ; ici c'est une requête, et l'appartenance se teste en mémoire.
    deja = {
        (d, r, v or "")
        for d, r, v in db.execute(
            text("""SELECT dossier_id, article_corpus_reference, COALESCE(date_version, '')
                    FROM notification_veille
                    WHERE article_corpus_reference = ANY(:refs)"""),
            {"refs": references},
        ).fetchall()
    }

    par_dossier: dict[str, int] = {}
    nb_notifications = 0
    nb_deja_notifies = 0
    apercu: list[dict] = []

    for article in articles:
        cibles = cibles_par_reference.get(article["reference"], {})
        if not cibles:
            continue

        for dossier_id, motif in cibles.items():
            # Contrôle explicite plutôt que de compter sur l'IntegrityError :
            # une exception par doublon invaliderait la transaction entière.
            cle = (dossier_id, article["reference"], article.get("date_version") or "")
            if cle in deja:
                nb_deja_notifies += 1
                continue
            # Ajout immédiat : deux articles du corpus peuvent porter la même
            # référence avec la même version (doublons d'extraction), et sans
            # ça on violerait l'index unique dans la même transaction.
            deja.add(cle)

            cle = str(dossier_id)
            par_dossier[cle] = par_dossier.get(cle, 0) + 1
            nb_notifications += 1

            if len(apercu) < 20:
                apercu.append({
                    "dossier_id": cle,
                    "reference": article["reference"],
                    "motif": motif,
                    "source": article.get("document_label"),
                    "premiere_apparition": article.get("premiere_apparition"),
                    "document_precedent_label": article.get("document_precedent_label"),
                })

            if not dry_run:
                db.execute(
                    text("""INSERT INTO notification_veille
                            (id, dossier_id, article_corpus_reference, message, lu,
                             niveau, source_label, document_id, date_version, motif, created_at)
                            VALUES (:id, :d, :r, :m, false, :n, :sl, :doc, :v, :motif, :now)"""),
                    {
                        "id": uuid.uuid4(), "d": dossier_id, "r": article["reference"],
                        "m": _message_pour(article, motif),
                        "n": _niveau_pour(article.get("document_type")),
                        "sl": article.get("source_label") or article.get("document_label"),
                        "doc": article.get("document_id"),
                        "v": article.get("date_version"),
                        "motif": motif,
                        "now": datetime.now(timezone.utc),
                    },
                )

    if not dry_run:
        db.commit()

    return {
        "dry_run": dry_run,
        "nb_articles_examines": len(articles_bruts),
        "nb_articles_inchanges": nb_articles_inchanges,
        "nb_articles_deja_depasses": nb_articles_deja_depasses,
        "nb_notifications": nb_notifications,
        "nb_deja_notifies": nb_deja_notifies,
        "nb_dossiers_touches": len(par_dossier),
        "par_dossier": par_dossier,
        "apercu": apercu,
    }
