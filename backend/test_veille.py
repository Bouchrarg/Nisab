"""
Verifie le ciblage de la veille personnalisee (bloc 3).

Ce qui doit etre prouve, et qui est la seule chose interessante du module :
un article n'est notifie QU'AUX dossiers qui l'ont deja cite. Un dossier
temoin, qui n'a jamais cite l'article, ne doit rien recevoir — sinon ce n'est
plus de la veille personnalisee, c'est une newsletter.

Utilise ADMIN_DATABASE_URL (role proprietaire) parce que la diffusion ecrit
pour toutes les organisations, ce que le contexte RLS interdit par
construction. C'est la meme raison qui fait que /admin/veille/diffuser est la
seule route du produit a ne pas utiliser get_tenant_db.

Lancer depuis backend/ :  python test_veille.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv(".env")

from app.models import (
    AlerteRisque, Citation, CitationRisque, Dossier, NiveauRisque,
    Organisation, TypeOrganisation,
)
from app.veille import articles_nouveaux_depuis, diffuser, dossiers_concernes, filtrer_changements_reels

ok = True


def check(label, cond, det=""):
    global ok
    print(("  OK   " if cond else "  ECHEC") + f" {label}" + (f"  [{det}]" if det else ""))
    ok = ok and bool(cond)


corpus = os.environ["CORPUS_DB_PATH"]
db = sessionmaker(bind=create_engine(os.environ["ADMIN_DATABASE_URL"]))()

# Reference reellement presente dans le corpus : le test doit porter sur une
# vraie donnee, pas sur une reference inventee qui ne remonterait jamais.
c = sqlite3.connect(corpus)
REF = c.execute("SELECT reference FROM articles WHERE statut='valide' LIMIT 1").fetchone()[0]
# Combien de documents du corpus portent cette reference ? Une meme reference
# peut exister dans le Bulletin Officiel ET dans le CGI consolide : ce sont
# deux couches distinctes (regle d'architecture), donc deux notifications
# legitimes. On ne code pas "2" en dur, on lit la realite du corpus.
nb_docs_avec_ref = c.execute(
    "SELECT count(DISTINCT document_id) FROM articles WHERE reference=? AND statut='valide'", (REF,)
).fetchone()[0]
c.close()
print(f"\nArticle temoin du corpus : {REF}")

org = Organisation(id=uuid.uuid4(), nom="ZZ_TEST_veille", type_organisation=TypeOrganisation.cabinet)
d_cite = Dossier(id=uuid.uuid4(), organisation_id=org.id, raison_sociale="ZZ Cite l'article", secteur_activite="test")
d_temoin = Dossier(id=uuid.uuid4(), organisation_id=org.id, raison_sociale="ZZ Temoin", secteur_activite="test")
# Commit en trois temps : aucune relation SQLAlchemy n'est declaree entre
# Dossier et AlerteRisque, donc l'ORM ne sait pas ordonner les INSERT et
# tenterait d'inserer l'alerte avant son dossier.
db.add_all([org, d_cite, d_temoin])
db.commit()

alerte = AlerteRisque(id=uuid.uuid4(), dossier_id=d_cite.id, titre="ZZ alerte", description="",
                      niveau_risque=NiveauRisque.eleve, cle_metier=f"ZZTEST|{uuid.uuid4()}", actif=True)
db.add(alerte)
db.commit()

db.add(CitationRisque(id=uuid.uuid4(), alerte_id=alerte.id, article_reference=REF, version_corpus="CGI 2026"))
db.commit()

tmp_corpus_path = None  # nettoye dans le finally, cree en section 6

try:
    print("\n-- 1. Lecture du corpus ----------------------------------------")
    arts = articles_nouveaux_depuis(corpus, None)
    check("articles valides lus", len(arts) > 0, f"{len(arts)} articles")
    check("champs de provenance presents",
          all(k in arts[0] for k in ("reference", "document_id", "document_label", "document_type")),
          ", ".join(sorted(arts[0])))
    futur = articles_nouveaux_depuis(corpus, "2099-01-01T00:00:00+00:00")
    check("filtre since fonctionnel", len(futur) == 0, f"{len(futur)} depuis 2099")

    print("\n-- 2. Ciblage : qui a deja cite cet article ? -------------------")
    cibles = dossiers_concernes(db, REF)
    check("le dossier qui cite est cible", d_cite.id in cibles)
    check("le dossier temoin n'est PAS cible", d_temoin.id not in cibles,
          "sinon ce serait une newsletter, pas de la veille personnalisee")
    check("motif explicite", "alerte de risque" in cibles.get(d_cite.id, ""), cibles.get(d_cite.id))
    check("reference inconnue -> personne", dossiers_concernes(db, "Article inexistant 99999") == {})

    print("\n-- 3. Diffusion en simulation (rien n'est ecrit) ----------------")
    sec = diffuser(db, corpus, dry_run=True)
    avant = db.execute(text("SELECT count(*) FROM notification_veille WHERE dossier_id=:d"),
                       {"d": d_cite.id}).scalar()
    check("dry_run ne cree rien", avant == 0, f"{avant} notification(s)")
    check("dry_run annonce des notifications", sec["nb_notifications"] > 0, str(sec["nb_notifications"]))
    check("apercu fourni pour verification", len(sec["apercu"]) > 0)

    print("\n-- 4. Diffusion reelle -----------------------------------------")
    res = diffuser(db, corpus, dry_run=False)
    n_cite = db.execute(text("SELECT count(*) FROM notification_veille WHERE dossier_id=:d"),
                        {"d": d_cite.id}).scalar()
    n_temoin = db.execute(text("SELECT count(*) FROM notification_veille WHERE dossier_id=:d"),
                          {"d": d_temoin.id}).scalar()
    lignes = db.execute(text("""SELECT article_corpus_reference, niveau, source_label, document_id, motif, lu
                                FROM notification_veille WHERE dossier_id=:d
                                ORDER BY document_id"""), {"d": d_cite.id}).fetchall()
    bo = [l for l in lignes if "bulletin" in (l[2] or "").lower()]
    cgi = [l for l in lignes if l not in bo]
    # PAS "n_cite == nb_docs_avec_ref" : ce serait l'ancienne hypothese, fausse
    # depuis le filtrage par contenu reel (section 6 en fait la preuve isolee
    # et deterministe). Sur les vraies donnees du corpus, on ne peut garantir
    # qu'une reference precise ait effectivement change d'une annee a l'autre
    # ni deviner combien d'editions CGI seront filtrees comme deja depassees
    # — seules les bornes et les invariants structurels sont verifiables ici.
    check("le dossier qui cite ne recoit jamais plus de notifications que de documents reels",
          0 <= n_cite <= nb_docs_avec_ref, f"{n_cite} notification(s) pour {nb_docs_avec_ref} document(s) du corpus")
    check("le dossier temoin ne recoit rien", n_temoin == 0, f"{n_temoin}")
    check("toutes portent la bonne reference", all(l[0] == REF for l in lignes))
    check("au plus une consolidation CGI notifiee (les editions CGI anterieures deja depassees sont filtrees)",
          len(cgi) <= 1, [l[3] for l in cgi])
    check("un Bulletin Officiel remonte en niveau eleve", all(l[1] == "eleve" for l in bo),
          ", ".join(f"{l[3]}={l[1]}" for l in lignes))
    check("une consolidation CGI reste en niveau moyen", all(l[1] == "moyen" for l in cgi))
    check("motif persiste", all(l[4] for l in lignes), lignes[0][4] if lignes else "")
    check("creees en non-lues", all(l[5] is False for l in lignes))

    print("\n-- 5. Idempotence ----------------------------------------------")
    res2 = diffuser(db, corpus, dry_run=False)
    n_apres = db.execute(text("SELECT count(*) FROM notification_veille WHERE dossier_id=:d"),
                         {"d": d_cite.id}).scalar()
    check("relancer ne cree pas de doublon", n_apres == n_cite, f"{n_apres}")
    check("les deja-notifies sont comptes", res2["nb_deja_notifies"] > 0, str(res2["nb_deja_notifies"]))
    check("aucune notification neuve au 2e passage", res2["nb_notifications"] == 0, str(res2["nb_notifications"]))

    print("\n-- 6. Vraie veille : republication identique VS changement reel -")
    # Copie temporaire : cette section ecrit des documents synthetiques dans
    # le corpus, jamais dans le vrai corpus-pipeline/data/corpus.db.
    #
    # Les deux cas sont testes en DEUX PHASES SEQUENTIELLES (pas dans le meme
    # lot) : si les deux documents synthetiques coexistaient des le depart,
    # le plus ancien des deux serait filtre comme "deja depasse" par l'autre
    # (meme mecanisme que le backfill, section 4) AVANT meme la comparaison
    # de texte — ca prouverait la mauvaise chose. En les inserant l'un apres
    # l'autre, chaque phase isole exactement le mecanisme qu'elle teste.
    tmp_fd, tmp_corpus_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)  # sinon le fichier reste verrouille (Windows) et le nettoyage final echoue
    shutil.copyfile(corpus, tmp_corpus_path)
    print(f"  Corpus de travail (copie) : {tmp_corpus_path}")

    # Type='CGI' pour le synthetique, et texte_original PRIS DANS UNE EDITION
    # CGI explicitement (pas "la plus recente version, tout type confondu") :
    # comparer un synthetique typé CGI contre le texte d'un VRAI Bulletin
    # Officiel (article différent, même numéro par coïncidence — cf. section
    # 4) casserait ce test exactement comme ça a cassé la vraie diffusion.
    ct = sqlite3.connect(tmp_corpus_path)
    texte_original = ct.execute(
        "SELECT a.texte FROM articles a JOIN documents d ON d.id = a.document_id "
        "WHERE a.reference=? AND a.statut='valide' AND d.type='CGI' "
        "ORDER BY (a.date_version IS NULL), a.date_version DESC LIMIT 1",
        (REF,),
    ).fetchone()[0]

    def inserer_zz(doc_id, date_version, texte):
        ct.execute(
            "INSERT INTO documents (id, label, type, url, date_version, statut) "
            "VALUES (?, ?, 'CGI', 'zztest://local', ?, 'valide')",
            (doc_id, f"ZZ CGI test ({date_version})", date_version),
        )
        ct.execute(
            "INSERT INTO articles (document_id, reference, texte, source_label, date_version, statut, date_extraction) "
            "VALUES (?, ?, ?, ?, ?, 'valide', ?)",
            (doc_id, REF, texte, f"ZZ CGI test ({date_version})", date_version,
             datetime.now(timezone.utc).isoformat()),
        )
        ct.commit()

    print("\n  Phase A - republication a texte identique (ne doit RIEN declencher)")
    since_a = datetime.now(timezone.utc).isoformat()
    inserer_zz("ZZ_TEST_cgi_2027_A", "2027-06-01", texte_original)

    arts_a = articles_nouveaux_depuis(tmp_corpus_path, since_a)
    check("1 nouvel article detecte brut (phase A)", len(arts_a) == 1, f"{len(arts_a)} article(s)")
    changes_a, nb_inchanges_a, nb_deja_depasses_a = filtrer_changements_reels(tmp_corpus_path, arts_a)
    check("texte identique -> filtre comme inchange (pas 'deja depasse')",
          nb_inchanges_a == 1 and nb_deja_depasses_a == 0 and len(changes_a) == 0,
          f"inchanges={nb_inchanges_a} deja_depasses={nb_deja_depasses_a} changes={len(changes_a)}")

    res_a = diffuser(db, tmp_corpus_path, since_iso=since_a, dry_run=False)
    check("aucune notification pour une republication a l'identique", res_a["nb_notifications"] == 0, str(res_a["nb_notifications"]))
    ligne_a = db.execute(
        text("SELECT 1 FROM notification_veille WHERE dossier_id=:d AND document_id=:doc"),
        {"d": d_cite.id, "doc": "ZZ_TEST_cgi_2027_A"},
    ).fetchone()
    check("le dossier n'est PAS notifie pour la republication a l'identique", ligne_a is None)

    print("\n  Phase B - republication avec un texte modifie (DOIT declencher)")
    since_b = datetime.now(timezone.utc).isoformat()
    inserer_zz("ZZ_TEST_cgi_2027_B", "2027-06-02", texte_original + "\n[MODIFICATION TEST]")

    arts_b = articles_nouveaux_depuis(tmp_corpus_path, since_b)
    check("1 nouvel article detecte brut (phase B)", len(arts_b) == 1, f"{len(arts_b)} article(s)")
    changes_b, nb_inchanges_b, nb_deja_depasses_b = filtrer_changements_reels(tmp_corpus_path, arts_b)
    check("texte modifie -> reconnu comme un changement reel",
          len(changes_b) == 1 and changes_b[0]["document_id"] == "ZZ_TEST_cgi_2027_B",
          [c["document_id"] for c in changes_b])

    res_b = diffuser(db, tmp_corpus_path, since_iso=since_b, dry_run=False)
    check("nb_articles_inchanges reporte dans les stats", res_b["nb_articles_inchanges"] == 0, str(res_b["nb_articles_inchanges"]))
    check("une notification reelle emise pour le vrai changement", res_b["nb_notifications"] >= 1, str(res_b["nb_notifications"]))

    ligne_b = db.execute(
        text("SELECT message FROM notification_veille WHERE dossier_id=:d AND document_id=:doc"),
        {"d": d_cite.id, "doc": "ZZ_TEST_cgi_2027_B"},
    ).fetchone()
    check("le dossier est notifie pour le VRAI changement", ligne_b is not None)
    if ligne_b:
        check("le message nomme la version precedente", "changé depuis" in ligne_b[0], ligne_b[0])

    ct.close()

    print("\n-- 7. Une citation de l'assistant compte aussi ------------------")
    db.add(Citation(id=uuid.uuid4(), dossier_id=d_temoin.id, question="q", reponse="r",
                    article_reference=REF, version_corpus="CGI 2026"))
    db.commit()
    cibles2 = dossiers_concernes(db, REF)
    check("le temoin devient cible apres avoir cite", d_temoin.id in cibles2)
    check("motif mentionne l'assistant", "assistant" in cibles2.get(d_temoin.id, ""), cibles2.get(d_temoin.id))

finally:
    # Filet de securite independant du dossier_id : diffuser() cible TOUS les
    # dossiers reels qui ont deja cite REF, pas seulement d_cite/d_temoin — si
    # un autre dossier reel citait par coincidence la meme REF, il recevrait
    # aussi une notification pointant vers un document_id ZZ_TEST_*, jamais
    # nettoyee par les DELETE scopes dossier_id ci-dessous.
    db.execute(text("DELETE FROM notification_veille WHERE document_id LIKE 'ZZ_TEST_%'"))
    for t in ("notification_veille", "citation", "citation_risque"):
        if t == "citation_risque":
            db.execute(text("DELETE FROM citation_risque WHERE alerte_id IN "
                            "(SELECT id FROM alerte_risque WHERE dossier_id IN (:a,:b))"),
                       {"a": d_cite.id, "b": d_temoin.id})
        else:
            db.execute(text(f"DELETE FROM {t} WHERE dossier_id IN (:a,:b)"), {"a": d_cite.id, "b": d_temoin.id})
    db.execute(text("DELETE FROM alerte_risque WHERE dossier_id IN (:a,:b)"), {"a": d_cite.id, "b": d_temoin.id})
    db.execute(text("DELETE FROM dossier WHERE id IN (:a,:b)"), {"a": d_cite.id, "b": d_temoin.id})
    db.execute(text("DELETE FROM organisation WHERE id=:o"), {"o": org.id})
    db.commit()
    db.close()
    if tmp_corpus_path and os.path.exists(tmp_corpus_path):
        os.remove(tmp_corpus_path)
    print("\nDonnees de test nettoyees.")

print("\n" + ("=> TOUT PASSE" if ok else "=> DES VERIFICATIONS ONT ECHOUE"))
sys.exit(0 if ok else 1)
