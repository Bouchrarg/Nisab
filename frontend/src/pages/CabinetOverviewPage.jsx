import { useEffect, useMemo, useState } from 'react'
import { Plus, ArrowRight, Building2, Scale, CalendarClock, AlertOctagon } from 'lucide-react'
import { apiFetch } from '../config/api'
import { useAuth } from '../context/AuthContext'
import { useDossier } from '../context/DossierContext'
import { parseDate } from '../utils/dates'
import Badge from '../components/ui/Badge'

const URGENCY_CLS = { critique: 'critique', urgent: 'vigilance', normal: 'seuil', planifié: 'conforme' }

const LAW_TYPE_CLS = {
  CGI: 'seuil',
  'Bulletin Officiel': 'vigilance',
  'Circulaire DGI': 'conforme',
  'Loi de Finances': 'critique',
}

// Accord au pluriel naturel ("3 anomalies critiques", "1 anomalie critique")
// plutôt que la forme "(s)" — appliqué à tous les mots de la phrase qui
// doivent s'accorder (nom + adjectif/participe).
const plural = (n, ...words) => `${n} ${words.map((w) => `${w}${n > 1 ? 's' : ''}`).join(' ')}`

// Vue cabinet multi-dossiers (Module 7 du cahier des charges) : un dossier
// = une carte avec un feu tricolore résumant sa situation, sans avoir à
// entrer dedans. Le point d'entrée par défaut après connexion.
export default function CabinetOverviewPage({ onOpenDossier, onCriticalAlertsChange }) {
  const { user } = useAuth()
  const { dossiers, createDossier, loading } = useDossier()
  const [summaries, setSummaries] = useState({}) // { [dossierId]: summary | 'loading' | 'error' }
  const [showCreate, setShowCreate] = useState(false)
  const [raisonSociale, setRaisonSociale] = useState('')
  const [secteur, setSecteur] = useState('')
  const [creating, setCreating] = useState(false)
  const [lawFeed, setLawFeed] = useState([])
  const [echeances, setEcheances] = useState({}) // { [dossierId]: events[] | 'loading' | 'error' }
  // Nb de notifications de veille NON LUES par dossier (routes_veille.py,
  // même table que VeillePage.jsx) — pas un comptage d'articles du corpus en
  // général : ne compte que les évolutions déjà ciblées sur un dossier parce
  // qu'il a cité l'article concerné (cf. veille.py, diffusion par citation).
  // "N articles mis à jour" n'existe nulle part côté API sans date fiable à
  // comparer ; ce chiffre-ci est réel, déjà scopé par dossier, et répond à
  // la vraie question ("y a-t-il de la veille à regarder ?").
  const [veilleCounts, setVeilleCounts] = useState({}) // { [dossierId]: nb_non_lues | 'loading' | 'error' }

  useEffect(() => {
    dossiers.forEach((d) => {
      setSummaries((prev) => (prev[d.id] ? prev : { ...prev, [d.id]: 'loading' }))
      apiFetch(`/dossiers/${d.id}/dashboard/summary`)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((s) => setSummaries((prev) => ({ ...prev, [d.id]: s })))
        .catch(() => setSummaries((prev) => ({ ...prev, [d.id]: 'error' })))

      setEcheances((prev) => (prev[d.id] ? prev : { ...prev, [d.id]: 'loading' }))
      apiFetch(`/dossiers/${d.id}/calendar/events`)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((data) => setEcheances((prev) => ({ ...prev, [d.id]: data.events || [] })))
        .catch(() => setEcheances((prev) => ({ ...prev, [d.id]: 'error' })))

      setVeilleCounts((prev) => (prev[d.id] !== undefined ? prev : { ...prev, [d.id]: 'loading' }))
      apiFetch(`/dossiers/${d.id}/veille?non_lues_seulement=true`)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((data) => setVeilleCounts((prev) => ({ ...prev, [d.id]: data.nb_non_lues || 0 })))
        .catch(() => setVeilleCounts((prev) => ({ ...prev, [d.id]: 'error' })))
    })
  }, [dossiers])

  // Résumé portefeuille : purement dérivé de summaries (déjà chargé pour les
  // cartes dossier ci-dessous) — pas d'appel réseau supplémentaire.
  //
  // Les dossiers non analysés sont EXCLUS des totaux et comptés à part. Les
  // inclure les ferait contribuer 0 anomalie et 0 DH, donc baisser
  // mécaniquement l'exposition affichée du cabinet à mesure qu'on ajoute des
  // dossiers qu'on n'a pas encore audités : le tableau paraîtrait d'autant
  // plus rassurant qu'il couvre moins de choses. `nbNonAnalyses` est affiché
  // à côté du total pour que celui-ci se lise avec son périmètre.
  const loadedSummaries = Object.values(summaries).filter(
    (s) => s && s !== 'loading' && s !== 'error' && s.status !== 'no_data'
  )
  const analysedSummaries = loadedSummaries.filter((s) => s.audit_status !== 'jamais_lance')
  const portfolioStats = {
    totalAnomalies: analysedSummaries.reduce((sum, s) => sum + (s.nb_anomalies || 0), 0),
    totalExposure: analysedSummaries.reduce((sum, s) => sum + (s.total_exposure_dh || 0), 0),
    nbEnAlerte: analysedSummaries.filter((s) => (s.risks?.rouge || 0) > 0).length,
    nbNonAnalyses: loadedSummaries.length - analysedSummaries.length,
  }

  const today = new Date().toISOString().slice(0, 10)
  const upcomingEcheances = Object.entries(echeances)
    .flatMap(([dossierId, events]) =>
      Array.isArray(events)
        ? events.map((e) => ({ ...e, dossierName: dossiers.find((d) => d.id === dossierId)?.raison_sociale || '' }))
        : []
    )
    .filter((e) => e.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 6)

  // Prochaine échéance PAR dossier — dérivée de `echeances`, déjà chargé
  // dossier par dossier ci-dessus (pas de nouvel appel réseau). Réutilisée
  // à la fois par les cartes dossier et par la table "À traiter maintenant".
  const nextEcheanceFor = (dossierId) => {
    const events = echeances[dossierId]
    if (!Array.isArray(events)) return null
    return events.filter((e) => e.date >= today).sort((a, b) => a.date.localeCompare(b.date))[0] || null
  }

  useEffect(() => {
    apiFetch('/law/feed?mode=latest&limit=8')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setLawFeed(d.feed || []))
      .catch(() => setLawFeed([]))
  }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!raisonSociale.trim()) return
    setCreating(true)
    try {
      const dossier = await createDossier({ raison_sociale: raisonSociale.trim(), secteur_activite: secteur.trim() })
      setRaisonSociale('')
      setSecteur('')
      setShowCreate(false)
      onOpenDossier(dossier)
    } finally {
      setCreating(false)
    }
  }

  // `jamais_lance` doit rester NEUTRE, jamais "Conforme". Avec des risks à
  // {0,0,0}, un dossier non analysé retombait sinon sur la branche finale et
  // s'affichait "Conforme" dans la vue d'ensemble du cabinet — le seul écran
  // où un associé balaye 20 dossiers d'un coup d'œil sans ouvrir aucun.
  const feuFor = (dossierId) => {
    const s = summaries[dossierId]
    if (s === 'loading') return { cls: 'neutral', label: 'Chargement…' }
    if (s === 'error') return { cls: 'neutral', label: 'Erreur de chargement' }
    // « Données non importées » plutôt que « Aucune donnée chargée » : décrit
    // l'action manquante (importer), pas juste l'état — la carte propose
    // explicitement cette action plus bas (voir dossier-card-open ci-dessous).
    if (!s || s.status === 'no_data') return { cls: 'neutral', label: 'Données non importées' }
    if (s.audit_status === 'jamais_lance') return { cls: 'neutral', label: 'Non analysé' }
    if ((s.risks?.rouge || 0) > 0) return { cls: 'critique', label: plural(s.risks.rouge, 'anomalie', 'critique') }
    if ((s.risks?.orange || 0) > 0) return { cls: 'vigilance', label: plural(s.risks.orange, 'alerte') }
    return { cls: 'conforme', label: 'Conforme' }
  }

  // useMemo (pas un simple const) : la référence ne doit changer que quand
  // dossiers/summaries changent vraiment, pas à chaque rendu — sinon l'effet
  // qui la remonte à App.jsx (pour la cloche du Topbar, juste en dessous)
  // se redéclencherait en boucle.
  const criticalAlerts = useMemo(
    () =>
      dossiers
        .map((d) => ({ dossier: d, s: summaries[d.id] }))
        .filter(({ s }) => s && s !== 'loading' && s !== 'error' && (s.risks?.rouge || 0) > 0),
    [dossiers, summaries]
  )

  // La cloche de notifications vit dans le Topbar (header persistant), pas
  // dans cette page — on ne fait ici que calculer la donnée et la remonter.
  useEffect(() => {
    onCriticalAlertsChange?.(criticalAlerts)
  }, [criticalAlerts, onCriticalAlertsChange])

  // Table "À traiter maintenant" : dossiers analysés avec au moins une
  // alerte (critique OU modérée), triés par urgence puis par exposition —
  // c'est la question qu'un associé pose réellement ("lesquels EN PREMIER ?"),
  // pas juste "combien d'anomalies au total". Purement dérivé de summaries/
  // echeances déjà chargés, aucun nouvel appel. Les dossiers "Conforme" ou
  // "Non analysé" n'y figurent jamais : cette table n'est PAS un inventaire,
  // c'est une file d'action.
  const priorityDossiers = useMemo(
    () =>
      dossiers
        .map((d) => ({ dossier: d, s: summaries[d.id], echeance: nextEcheanceFor(d.id) }))
        .filter(({ s }) => s && s !== 'loading' && s !== 'error' && s.status !== 'no_data' && ((s.risks?.rouge || 0) > 0 || (s.risks?.orange || 0) > 0))
        .sort((a, b) => {
          const ra = a.s.risks?.rouge || 0, rb = b.s.risks?.rouge || 0
          if (rb !== ra) return rb - ra
          const oa = a.s.risks?.orange || 0, ob = b.s.risks?.orange || 0
          if (ob !== oa) return ob - oa
          return (b.s.total_exposure_dh || 0) - (a.s.total_exposure_dh || 0)
        }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dossiers, summaries, echeances]
  )
  // Limité aux 3 plus critiques : au-delà, cette table et la grille "Vos
  // dossiers" juste en dessous (qui liste TOUS les dossiers, y compris
  // ceux-ci) finissaient par répéter deux fois la même information sur un
  // même écran — la table doit rester "les urgences", pas un 2e inventaire.
  const topPriorityDossiers = priorityDossiers.slice(0, 3)

  // Prochaine échéance tous dossiers confondus — réutilisée dans la synthèse
  // ci-dessous, pas un nouvel appel (upcomingEcheances existe déjà).
  const nextEcheance = upcomingEcheances[0]
  const nextEcheanceDate = nextEcheance ? parseDate(nextEcheance.date) : null
  const todayLabel = new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })

  // Total veille non lue, tous dossiers — somme simple, pas de nouvel appel
  // (veilleCounts déjà chargé ci-dessus). Object.values sur un state qui
  // peut contenir 'loading'/'error' avant que tout ait répondu : filtré au
  // typeof, pas sommé tel quel (une chaîne concaténée casserait le total).
  const totalVeilleNonLues = Object.values(veilleCounts).reduce((sum, v) => sum + (typeof v === 'number' ? v : 0), 0)

  // Dossier à ouvrir si on clique sur le total : celui qui contribue le
  // plus de non-lues, pas le premier de la liste — sur un cabinet à
  // plusieurs dossiers, cliquer doit amener sur la veille qui a le plus de
  // retard, pas sur un dossier choisi arbitrairement par son ordre d'ajout.
  const topVeilleDossier = dossiers
    .map((d) => ({ dossier: d, count: veilleCounts[d.id] }))
    .filter(({ count }) => typeof count === 'number' && count > 0)
    .sort((a, b) => b.count - a.count)[0]?.dossier || null

  // Salutation — chaleur par la personnalisation plutôt que par la couleur
  // (cf. commentaire .cabinet-hero dans App.css, option A retenue sur
  // maquette). Prénom = premier mot de nom_complet (rempli à l'inscription),
  // retombe sur la partie locale de l'email si nom_complet est vide (compte
  // créé avant que ce champ existe), puis sur la salutation elle-même si
  // même l'email manque (ne devrait pas arriver, mais le médaillon a besoin
  // d'une lettre quoi qu'il arrive).
  const prenom = (user?.nom_complet || '').trim().split(/\s+/)[0] || user?.email?.split('@')[0] || ''
  const heureActuelle = new Date().getHours()
  const salutation = heureActuelle < 12 ? 'Bonjour' : heureActuelle < 18 ? 'Bon après-midi' : 'Bonsoir'
  const greeting = prenom ? `${salutation}, ${prenom}` : salutation
  const initiale = (prenom || salutation).charAt(0).toUpperCase()

  // Phrase de synthèse : un fait direct, pas un jugement enrobé ("évolue en
  // position de conformité à surveiller" ne voulait rien dire de précis) ni
  // un score inventé — Nisab n'a pas de note globale sur 100 pour le cabinet
  // (aucune API ne la calcule). Rendue en JSX plutôt qu'en simple chaîne
  // pour pouvoir sortir le chiffre-clé (nb de dossiers en alerte) en plus
  // grand + bordeaux dans le texte — seule la branche "il y a des alertes"
  // a un chiffre à mettre en avant, les deux autres restent du texte plat.
  const cabinetHeadline =
    criticalAlerts.length > 0 ? (
      <>
        <span className="num">{criticalAlerts.length}</span> {criticalAlerts.length > 1 ? 'dossiers' : 'dossier'} nécessite
        {criticalAlerts.length > 1 ? 'nt' : ''} une attention immédiate, sur {plural(analysedSummaries.length, 'dossier', 'analysé')}.
      </>
    ) : analysedSummaries.length > 0 ? (
      `Aucun dossier ne nécessite d'attention immédiate, sur ${plural(analysedSummaries.length, 'dossier', 'analysé')}.`
    ) : (
      "Aucun dossier n'a encore été analysé."
    )

  return (
    <div>
      {/* Synthèse — Option A retenue sur maquette (cf. commentaire .cabinet-hero
          dans App.css) : fond clair inchangé, différenciation par la
          typographie + une touche de bordeaux localisée (eyebrow, médaillon,
          chiffre-clé), jamais un aplat plein. Purement dérivée de données
          déjà chargées sur cette page (+ user via useAuth pour la
          salutation). */}
      {dossiers.length > 0 && (
        <div className="cabinet-hero">
          <div className="cabinet-hero-greeting-row">
            <span className="cabinet-hero-medal">{initiale}</span>
            <span className="cabinet-hero-greeting">{greeting}</span>
          </div>
          <div className="cabinet-hero-eyebrow">Synthèse du cabinet</div>
          <div className="cabinet-hero-headline">{cabinetHeadline}</div>
          <div className="cabinet-hero-meta">
            {/* Décomposition explicite suivis/analysés/en attente — un
                simple "8 dossiers suivis" lu juste après "5 sur 7 analysés"
                dans la phrase de synthèse au-dessus posait la question "8 ?
                7 ? 5 ?". Le total et son périmètre vivent maintenant sur la
                même ligne, dans l'ordre où on les recompose mentalement. */}
            Actualisé le {todayLabel} · {plural(dossiers.length, 'dossier')} suivi{dossiers.length > 1 ? 's' : ''}
            {portfolioStats.nbNonAnalyses > 0
              ? ` (${plural(analysedSummaries.length, 'analysé')}, ${plural(portfolioStats.nbNonAnalyses, 'en attente de données')})`
              : ''}
            {nextEcheance && (
              <>
                {' '}· Prochaine échéance : {nextEcheance.title}
                {nextEcheanceDate ? ` le ${nextEcheanceDate.day} ${nextEcheanceDate.month}` : ''}
              </>
            )}
            {/* Interactif seulement quand il y a réellement une action
                derrière (des non-lues → un dossier précis à ouvrir sur son
                onglet Veille) — le cas "corpus à jour" reste du texte, il
                n'y a rien de dossier-spécifique à cliquer. Repli sur
                `lawFeed`, déjà chargé plus bas sur cette page pour le widget
                Veille légale (aucun nouvel appel). */}
            {totalVeilleNonLues > 0 ? (
              <>
                {' '}·{' '}
                <button
                  type="button"
                  className="cabinet-hero-inline-link"
                  onClick={() => topVeilleDossier && onOpenDossier(topVeilleDossier, 'veille')}
                >
                  {totalVeilleNonLues} {totalVeilleNonLues > 1 ? 'notifications de veille non lues' : 'notification de veille non lue'}
                </button>
              </>
            ) : (
              lawFeed[0] && (
                <> · Corpus à jour — dernier texte suivi : {lawFeed[0].reference || lawFeed[0].title}</>
              )
            )}
          </div>
        </div>
      )}

      {/* Sommaire cliquable essayé 2 fois (dans la carte, puis en rangée de
          puces séparée) — retiré complètement sur demande explicite après
          le 2e essai ("où sont posés" + "trop présent"). Retour à l'état
          d'avant : on scrolle. Les id de section (priorite-section,
          dossiers-section, echeances-section, veille-section) posés plus
          bas sont laissés en place — inertes sans lien qui les cible, mais
          réutilisables directement si une navigation reprend un jour sous
          une forme différente. */}

      {dossiers.length > 0 && (
        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-label">Dossiers</div>
            <div className="kpi-value">{dossiers.length}</div>
            <div className="kpi-sub">au cabinet</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Anomalies actives</div>
            <div className={`kpi-value ${portfolioStats.totalAnomalies > 0 ? 'critique' : 'conforme'}`}>
              {portfolioStats.totalAnomalies}
            </div>
            {/* Le périmètre est affiché avec le chiffre, pas à côté : un
                total « tous dossiers confondus » qui n'en couvre que la
                moitié est un chiffre faux. */}
            <div className="kpi-sub">
              {portfolioStats.nbNonAnalyses > 0
                ? `sur ${plural(analysedSummaries.length, 'dossier', 'analysé')}`
                : 'tous dossiers confondus'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Exposition cumulée</div>
            {/* Rouge uniquement si l'exposition est réellement > 0 — pas de
                rouge en dur qui surchargerait l'écran sans information réelle
                derrière. */}
            <div className={`kpi-value mono ${portfolioStats.totalExposure > 0 ? 'critique' : 'conforme'}`}>
              {portfolioStats.totalExposure.toLocaleString('fr-MA')} DH
            </div>
            <div className="kpi-sub">
              {portfolioStats.nbNonAnalyses > 0
                ? `${plural(portfolioStats.nbNonAnalyses, 'dossier', 'non analysé')}, hors total`
                : 'estimation, tous dossiers'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Dossiers en alerte</div>
            <div className={`kpi-value ${portfolioStats.nbEnAlerte > 0 ? 'vigilance' : 'conforme'}`}>
              {portfolioStats.nbEnAlerte}
            </div>
            <div className="kpi-sub">sur {plural(analysedSummaries.length, 'dossier', 'analysé')}</div>
          </div>
        </div>
      )}

      {/* Bloc ROI retiré des deux vues (dossier + cabinet) sur demande
          explicite — "on verra après où le mettre". Le composant existe
          toujours côté backend (routes_roi.py, roi.py) et le CSS .roi-*
          n'a pas été supprimé (réutilisable tel quel le jour où ce bloc
          revient ailleurs), seul l'affichage ici a été enlevé. */}

      {/* Titre nu, pas de carte autour : la version encartée (icône + badge
          compteur + padding de card-header) prenait trop de place pour un
          bloc qui n'est qu'un sous-ensemble des dossiers déjà visibles plus
          bas en cartes — "grand titre" demandé explicitement, pas un
          conteneur de plus. Le tableau lui-même garde son propre filet
          (.data-table a déjà sa bordure), donc la limite reste lisible sans
          boîte englobante. */}
      {topPriorityDossiers.length > 0 && (
        <>
          <div id="priorite-section" className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, scrollMarginTop: 20 }}>
            <AlertOctagon size={17} style={{ color: 'var(--critique)' }} />
            À traiter maintenant
          </div>
          <div style={{ overflowX: 'auto', marginBottom: 20 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Dossier</th><th>Risque</th><th>Exposition</th><th>Échéance</th><th></th>
                </tr>
              </thead>
              <tbody>
                {topPriorityDossiers.map(({ dossier: d, s, echeance }) => {
                  const feu = feuFor(d.id)
                  const echeanceDate = echeance ? parseDate(echeance.date) : null
                  return (
                    <tr key={d.id}>
                      <td style={{ fontWeight: 600 }}>{d.raison_sociale}</td>
                      <td><Badge cls={feu.cls} small>{feu.label}</Badge></td>
                      <td className="mono">
                        {s.total_exposure_dh > 0 ? `${s.total_exposure_dh.toLocaleString('fr-MA')} DH` : '—'}
                      </td>
                      <td>
                        {echeance ? `${echeance.title}${echeanceDate ? ` (${echeanceDate.day} ${echeanceDate.month})` : ''}` : '—'}
                      </td>
                      <td>
                        <button className="btn btn-secondary btn-sm" onClick={() => onOpenDossier(d)}>
                          Examiner <ArrowRight size={12} />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* alignItems: center (au lieu du défaut flex-start de .section-header,
          pensé pour titre+sous-titre) : sans sous-titre, un titre sur une
          seule ligne calé en haut à côté du bouton paraissait décentré.
          Scopé à cette page, pas touché ailleurs. La cloche d'alertes a
          déménagé dans le Topbar (voir plus haut dans ce fichier). */}
      <div id="dossiers-section" className="section-header" style={{ alignItems: 'center', scrollMarginTop: 20 }}>
        <div>
          <div className="section-title">Vos dossiers</div>
          {/* Sous-titre réintroduit : contrairement à avant, il dit quelque
              chose que rien d'autre sur la page ne dit au même endroit —
              le total portefeuille juste au-dessus de la grille qu'il
              décrit, demandé explicitement ("vue portefeuille : 8 dossiers
              · 31 anomalies · 177k DH"). */}
          {dossiers.length > 0 && (
            <div className="section-sub">
              {plural(dossiers.length, 'dossier')} · {plural(portfolioStats.totalAnomalies, 'anomalie')} · {portfolioStats.totalExposure.toLocaleString('fr-MA')} DH d'exposition
            </div>
          )}
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate((v) => !v)}>
          <Plus size={14} /> Nouveau dossier
        </button>
      </div>

      {showCreate && (
        <form className="dossier-create-card" onSubmit={handleCreate}>
          <label>
            Raison sociale
            <input
              autoFocus
              value={raisonSociale}
              onChange={(e) => setRaisonSociale(e.target.value)}
              placeholder="Ex : SARL Atlas Industrie"
              required
            />
          </label>
          <label>
            Secteur d'activité (optionnel)
            <input
              value={secteur}
              onChange={(e) => setSecteur(e.target.value)}
              placeholder="Ex : transformation industrielle"
            />
          </label>
          <div className="dossier-create-actions">
            <button type="submit" className="btn btn-primary btn-sm" disabled={creating}>
              {creating ? 'Création…' : 'Créer le dossier'}
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowCreate(false)}>
              Annuler
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <span className="spinner dark" style={{ width: 22, height: 22 }} />
        </div>
      ) : dossiers.length === 0 && !showCreate ? (
        <div className="empty-state">
          <Building2 size={28} />
          <p>Vous n'avez encore aucun dossier.</p>
          <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>
            <Plus size={14} /> Créer votre premier dossier
          </button>
        </div>
      ) : (
        <div className="dossier-cards-grid">
          {dossiers.map((d) => {
            const feu = feuFor(d.id)
            const s = summaries[d.id]
            // Nombre d'anomalies TOTAL (déjà chargé pour ce dossier, pas un
            // nouvel appel) — distinct du libellé du statut, qui ne compte
            // que les critiques/vigilance selon le cas. N'affiche rien tant
            // que le résumé n'est pas exploitable (chargement/erreur/jamais
            // analysé) plutôt que d'inventer un 0.
            const hasCount = s && s !== 'loading' && s !== 'error' && s.status !== 'no_data' && s.audit_status !== 'jamais_lance'
            const noData = s && s !== 'loading' && s !== 'error' && s.status === 'no_data'
            const meta = [
              d.secteur_activite,
              hasCount ? plural(s.nb_anomalies, 'anomalie') : null,
            ].filter(Boolean)
            // Échéance/exposition : deux lignes de contexte supplémentaires
            // pour qu'un scan de 2 secondes suffise à savoir "il y a quelque
            // chose à faire ici, et à peu près quoi" — sans ouvrir le
            // dossier. Données déjà chargées (summaries/echeances), aucun
            // nouvel appel réseau. Le statut (Badge) reste la SEULE couleur
            // de la carte, cf. règle Direction D sur .dossier-card.
            const echeance = nextEcheanceFor(d.id)
            const echeanceDate = echeance ? parseDate(echeance.date) : null
            return (
              <div key={d.id} className="dossier-card" onClick={() => onOpenDossier(d)}>
                <div className="dossier-card-top">
                  <span className="dossier-card-name">{d.raison_sociale}</span>
                  <Badge cls={feu.cls}>{feu.label}</Badge>
                </div>
                {meta.length > 0 && <div className="dossier-card-meta">{meta.join(' · ')}</div>}
                {hasCount && s.total_exposure_dh > 0 && (
                  <div className="dossier-card-stat critique">
                    Exposition : {s.total_exposure_dh.toLocaleString('fr-MA')} DH
                  </div>
                )}
                {echeance && (
                  <div className="dossier-card-stat">
                    Prochaine échéance : {echeance.title}
                    {echeanceDate ? ` le ${echeanceDate.day} ${echeanceDate.month}` : ''}
                  </div>
                )}
                {/* Toute la carte est cliquable ; ce lien est un rappel
                    visuel de l'action, pas un second élément interactif
                    distinct (même onClick que la carte). Le libellé change
                    pour un dossier sans données : "Ouvrir" ne voulait rien
                    dire sur un dossier vide, l'action réelle est d'importer. */}
                <div className="dossier-card-open">
                  {noData ? 'Importer les données' : 'Ouvrir'} <ArrowRight size={12} aria-hidden="true" />
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="overview-widgets-grid" style={{ marginTop: 24 }}>
        <div id="echeances-section" className="card widget" style={{ scrollMarginTop: 20 }}>
          <div className="card-header">
            <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <CalendarClock size={14} style={{ color: 'var(--seuil)' }} />
              Prochaines échéances
            </span>
            <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>tous dossiers</span>
          </div>
          <div className="card-body" style={{ padding: 0, height: 420, overflowY: 'auto' }}>
            {dossiers.length === 0 ? (
              <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--sourdine)', textAlign: 'center' }}>
                Aucun dossier au cabinet.
              </div>
            ) : upcomingEcheances.length === 0 ? (
              <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--sourdine)', textAlign: 'center' }}>
                Aucune échéance à venir dans les prochains mois.
              </div>
            ) : (
              upcomingEcheances.map((e, i) => {
                const dt = parseDate(e.date)
                return (
                  // La date est le premier repère scanné dans cette liste
                  // (un chip net), le titre porte le poids visuel principal,
                  // le badge de catégorie passe en second plan (badge-sm).
                  <div key={`${e.dossierName}-${e.date}-${i}`} className="list-row">
                    {dt && (
                      <div className="list-date">
                        <div className="list-date-day">{dt.day}</div>
                        <div className="list-date-month">{dt.month}</div>
                      </div>
                    )}
                    <div className="list-body">
                      <div className="list-title">{e.title}</div>
                      <div className="list-sub">{e.dossierName}</div>
                    </div>
                    <Badge cls={URGENCY_CLS[e.urgency] || 'neutral'} small>{e.category}</Badge>
                  </div>
                )
              })
            )}
          </div>
        </div>

        <div id="veille-section" className="card widget" style={{ scrollMarginTop: 20 }}>
          <div className="card-header">
            <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Scale size={14} style={{ color: 'var(--seuil)' }} />
              Veille légale
            </span>
            <Badge cls="seuil">Corpus actif</Badge>
          </div>
          <div className="card-body" style={{ padding: 0, height: 420, overflowY: 'auto' }}>
            {lawFeed.length === 0 ? (
              <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--sourdine)', textAlign: 'center' }}>
                Chargement de la veille légale…
              </div>
            ) : (
              // Le titre/référence de l'article est ce qu'on doit reconnaître
              // en premier ; l'extrait reste lisible mais recule (plus petit,
              // plus clair, un seul repère de ligne) pour ne pas concurrencer
              // le titre à l'œil — aucune information supprimée.
              lawFeed.map((item, i) => (
                <div
                  key={item.id || i}
                  className="law-feed-item"
                  style={{ borderBottom: i < lawFeed.length - 1 ? '1px solid var(--bordure)' : 'none' }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <Badge cls={LAW_TYPE_CLS[item.type] || 'neutral'} small>{item.type}</Badge>
                    <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--encre)' }}>
                      {item.reference || item.title}
                    </span>
                  </div>
                  {item.reference && (
                    <div style={{ fontSize: 10.5, color: 'var(--sourdine)', marginBottom: 4 }}>{item.title}</div>
                  )}
                  <div
                    style={{
                      fontSize: 11, color: 'var(--sourdine)', opacity: 0.85, lineHeight: 1.5,
                      display: '-webkit-box', WebkitLineClamp: 1, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                    }}
                  >
                    {item.summary}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
