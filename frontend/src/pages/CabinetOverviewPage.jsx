import { useEffect, useMemo, useState } from 'react'
import { Plus, ArrowRight, Building2, Scale, CalendarClock, PiggyBank } from 'lucide-react'
import { apiFetch } from '../config/api'
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
  const { dossiers, createDossier, loading } = useDossier()
  const [summaries, setSummaries] = useState({}) // { [dossierId]: summary | 'loading' | 'error' }
  const [showCreate, setShowCreate] = useState(false)
  const [raisonSociale, setRaisonSociale] = useState('')
  const [secteur, setSecteur] = useState('')
  const [creating, setCreating] = useState(false)
  const [lawFeed, setLawFeed] = useState([])
  const [echeances, setEcheances] = useState({}) // { [dossierId]: events[] | 'loading' | 'error' }
  const [roi, setRoi] = useState(null) // GET /roi/portefeuille — null tant que non chargé

  useEffect(() => {
    apiFetch('/roi/portefeuille')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setRoi)
      .catch(() => setRoi(null))
  }, [dossiers])

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
    if (s === 'error' || !s || s.status === 'no_data') return { cls: 'neutral', label: 'Aucune donnée chargée' }
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

  // Prochaine échéance tous dossiers confondus — réutilisée dans la synthèse
  // ci-dessous, pas un nouvel appel (upcomingEcheances existe déjà).
  const nextEcheance = upcomingEcheances[0]
  const nextEcheanceDate = nextEcheance ? parseDate(nextEcheance.date) : null
  const todayLabel = new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })

  // Phrase de synthèse : un fait direct, pas un jugement enrobé ("évolue en
  // position de conformité à surveiller" ne voulait rien dire de précis) ni
  // un score inventé — Nisab n'a pas de note globale sur 100 pour le cabinet
  // (aucune API ne la calcule). Juste ce qui est réellement mesuré, avec le
  // même repère "sur X analysés" que la bande KPI juste en dessous.
  const cabinetHeadline =
    criticalAlerts.length > 0
      ? `${plural(criticalAlerts.length, 'dossier')} nécessite${criticalAlerts.length > 1 ? 'nt' : ''} une attention immédiate, sur ${plural(analysedSummaries.length, 'dossier', 'analysé')}.`
      : analysedSummaries.length > 0
        ? `Aucun dossier ne nécessite d'attention immédiate, sur ${plural(analysedSummaries.length, 'dossier', 'analysé')}.`
        : "Aucun dossier n'a encore été analysé."

  return (
    <div>
      {/* Synthèse : carte encadrée neutre (pas de bandeau coloré) — le ton
          donne le cadre, la bande KPI juste en dessous donne le détail
          chiffré. Purement dérivée de données déjà chargées sur cette page. */}
      {dossiers.length > 0 && (
        <div className="cabinet-hero">
          <div className="cabinet-hero-eyebrow">Synthèse du cabinet</div>
          <div className="cabinet-hero-headline">{cabinetHeadline}</div>
          <div className="cabinet-hero-meta">
            Actualisé le {todayLabel} · {plural(dossiers.length, 'dossier')} suivi{dossiers.length > 1 ? 's' : ''}
            {nextEcheance && (
              <>
                {' '}· Prochaine échéance : {nextEcheance.title}
                {nextEcheanceDate ? ` le ${nextEcheanceDate.day} ${nextEcheanceDate.month}` : ''}
              </>
            )}
          </div>
        </div>
      )}

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

      {/* Valeur générée : deux chiffres MESURÉS (exposition détectée /
          régularisée, sommées depuis les alertes réellement chiffrables —
          jamais un "non_calculable" compté comme 0 DH) et un chiffre ESTIMÉ
          (temps épargné). Les hypothèses/méthodologie passent en title
          (infobulle native au survol) plutôt qu'en texte permanent — la
          donnée reste disponible, juste pas imposée à la lecture. */}
      {roi && roi.status === 'ok' && roi.nb_dossiers > 0 && (
        <div className="card roi-card" style={{ marginTop: 16 }}>
          <div className="card-header">
            <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <PiggyBank size={14} style={{ color: 'var(--seuil)' }} />
              Valeur générée par Nisab
            </span>
            <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>
              {plural(roi.nb_dossiers, 'dossier', 'analysé')}
              {roi.nb_dossiers_non_analyses > 0 ? ` · ${plural(roi.nb_dossiers_non_analyses, 'non analysé')}` : ''}
            </span>
          </div>
          {/* Grille (pas flex-wrap) : le nombre de colonnes s'ajuste au
              nombre de métriques réellement présentes (3 ou 4 selon que les
              échéances TVA sont suivies), donc jamais une métrique isolée
              seule sur sa ligne. */}
          <div className="roi-grid">
            <div className="roi-item">
              <div className="roi-item-label" title="Mesuré à partir des alertes chiffrables, dossiers analysés uniquement.">
                Exposition détectée
              </div>
              <div className="roi-item-value critique">
                {roi.exposition_detectee_dh.toLocaleString('fr-MA')} <span className="unit">DH</span>
              </div>
              <div className="roi-item-tag">mesuré</div>
            </div>
            <div className="roi-item">
              <div className="roi-item-label" title="Mesuré sur les anomalies marquées « traitée ».">
                Exposition régularisée
              </div>
              <div className="roi-item-value conforme">
                {roi.exposition_regularisee_dh.toLocaleString('fr-MA')} <span className="unit">DH</span>
              </div>
              <div className="roi-item-tag">mesuré</div>
            </div>
            <div className="roi-item">
              <div
                className="roi-item-label"
                title={
                  roi.hypotheses?.[0]
                    ? `Estimé — hypothèse : ${roi.hypotheses[0].valeur} ${roi.hypotheses[0].unite}/pièce sans Nisab.`
                    : 'Estimé.'
                }
              >
                Temps épargné
              </div>
              <div className="roi-item-value">
                {roi.temps_estime_h.toLocaleString('fr-MA')} <span className="unit">h</span>
              </div>
              <div className="roi-item-tag">estimé</div>
            </div>
            {/* Distinct de "Exposition détectée" : celle-ci vient d'anomalies
                déjà commises (le passé), celle-ci d'échéances À VENIR (le
                futur) — jamais additionnées. Seule la TVA a une base
                chiffrable depuis les écritures (TVA facturée - déductible) ;
                IS/IR/CNSS/Taxe Professionnelle restent comptés, pas chiffrés
                (`nb_echeances_base_connue` le dit explicitement, en infobulle). */}
            {roi.nb_echeances_suivies > 0 && (
              <div className="roi-item">
                <div
                  className="roi-item-label"
                  title={
                    `${roi.nb_echeances_base_connue}/${roi.nb_echeances_suivies} échéance(s) chiffrable(s) (TVA uniquement)` +
                    (roi.hypotheses?.[1] ? ` — plancher ${roi.hypotheses[1].valeur}% (Art. 208 CGI)` : '')
                  }
                >
                  Échéances suivies
                </div>
                <div className="roi-item-value vigilance">
                  {roi.exposition_echeances_dh.toLocaleString('fr-MA')} <span className="unit">DH</span>
                </div>
                <div className="roi-item-tag">TVA uniquement</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* alignItems: center (au lieu du défaut flex-start de .section-header,
          pensé pour titre+sous-titre) : sans sous-titre, un titre sur une
          seule ligne calé en haut à côté du bouton paraissait décentré.
          Scopé à cette page, pas touché ailleurs. La cloche d'alertes a
          déménagé dans le Topbar (voir plus haut dans ce fichier). */}
      <div className="section-header" style={{ alignItems: 'center' }}>
        {/* Pas de sous-titre : "vue globale du cabinet" est déjà dit par la
            synthèse en haut de page, et "cliquez pour ouvrir" est une
            évidence une fois les cartes sous les yeux — la répéter ici
            n'ajoutait rien, juste une ligne de plus à lire. */}
        <div className="section-title">Vos dossiers</div>
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
            const meta = [
              d.secteur_activite,
              hasCount ? plural(s.nb_anomalies, 'anomalie') : null,
            ].filter(Boolean)
            return (
              <div key={d.id} className="dossier-card" onClick={() => onOpenDossier(d)}>
                <div className="dossier-card-top">
                  <span className="dossier-card-name">{d.raison_sociale}</span>
                  <Badge cls={feu.cls}>{feu.label}</Badge>
                </div>
                {meta.length > 0 && <div className="dossier-card-meta">{meta.join(' · ')}</div>}
                {/* Toute la carte est cliquable ; ce lien est un rappel
                    visuel de l'action, pas un second élément interactif
                    distinct (même onClick que la carte). */}
                <div className="dossier-card-open">
                  Ouvrir <ArrowRight size={12} aria-hidden="true" />
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="overview-widgets-grid" style={{ marginTop: 24 }}>
        <div className="card widget">
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

        <div className="card widget">
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
