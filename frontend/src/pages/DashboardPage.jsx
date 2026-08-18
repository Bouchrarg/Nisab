import { useEffect, useState } from 'react'
import { RefreshCw, ArrowRight, Database, CalendarClock, PiggyBank } from 'lucide-react'
import GaugeSeuil from '../components/ui/GaugeSeuil'
import Indicator from '../components/ui/Indicator'
import Badge from '../components/ui/Badge'
import { dossierFetch } from '../config/api'
import { parseDate } from '../utils/dates'

export default function DashboardPage({
  summary,
  onRunAudit,
  auditLoading,
  findings,
  auditDate = null,
  resultatPerime = false,
  onGoToAudit,
  onGoToCalendar,
}) {
  const [upcomingEvents, setUpcomingEvents] = useState([])
  const [eventsLoading, setEventsLoading] = useState(true)
  const [roi, setRoi] = useState(null) // GET /dossiers/{id}/roi

  useEffect(() => {
    if (!summary || summary.status === 'no_data') return
    setEventsLoading(true)
    dossierFetch('/calendar/events')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setUpcomingEvents((d.events || []).slice(0, 4)))
      .catch(() => setUpcomingEvents([]))
      .finally(() => setEventsLoading(false))
  }, [summary])

  useEffect(() => {
    // audit_status === 'done' : inutile d'interroger le ROI d'un dossier
    // jamais analysé, /roi renvoie de toute façon "indisponible" dans ce cas.
    if (!summary || summary.status === 'no_data' || summary.audit_status !== 'done') {
      setRoi(null)
      return
    }
    dossierFetch('/roi')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setRoi(d.status === 'ok' ? d : null))
      .catch(() => setRoi(null))
  }, [summary])

  if (!summary || summary.status === 'no_data') {
    return (
      <div>
        <div className="section-header">
          <div>
            <div className="section-title">Tableau de bord</div>
            <div className="section-sub">Conformité fiscale consolidée</div>
          </div>
        </div>

        <div className="empty-state">
          <div className="empty-state-icon">
            <Database size={22} />
          </div>

          <div className="empty-state-title">
            Aucune donnée comptable chargée
          </div>

          <div className="empty-state-sub">
            Connectez-vous à votre instance Odoo ou chargez les données de
            démonstration pour démarrer l'analyse fiscale.
          </div>
        </div>
      </div>
    )
  }

  const {
    company,
    nb_moves,
    nb_partners,
    source,
    audit_status,
    nb_anomalies,
    risks,
    total_exposure_dh,
    compliance_score,
    executive_summary,
    top_urgency,
  } = summary

  // Dossier chargé mais jamais analysé. Cet écran affichait auparavant un
  // spinner et « Analyse des anomalies en cours... » — un mensonge par
  // omission devenu franc depuis que l'audit ne part plus tout seul : rien
  // ne tourne, et sans clic rien ne tournera. On décrit l'état réel et on
  // donne l'action.
  if (audit_status === 'jamais_lance' || nb_anomalies === undefined) {
    return (
      <div>
        <div className="section-header">
          <div>
            <div className="section-title">{company}</div>
            <div className="section-sub">
              <span className="mono">{nb_moves}</span> écriture(s), <span className="mono">{nb_partners}</span> tiers
              {' '}· Source {source === 'demo' ? 'démonstration' : source || 'inconnue'}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={onRunAudit}
              disabled={auditLoading}
            >
              {auditLoading ? <span className="spinner" /> : <RefreshCw size={13} />}
              Lancer l'audit
            </button>
          </div>
        </div>

        <div className="card">
          <div className="card-body" style={{ textAlign: 'center', padding: '32px 20px' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--encre)', marginBottom: 6 }}>
              {auditLoading ? 'Analyse en cours…' : 'Aucune analyse lancée sur ce dossier'}
            </div>
            <div style={{ fontSize: 13, color: 'var(--sourdine)', lineHeight: 1.6, maxWidth: 520, margin: '0 auto' }}>
              {auditLoading
                ? "Chaque écriture est confrontée au corpus fiscal — comptez quelques minutes sur un gros dossier."
                : "Les données comptables sont chargées mais n'ont pas encore été confrontées au corpus fiscal. Tant qu'aucune analyse n'a tourné, aucun chiffre de conformité ne peut être affiché."}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const scoreCls =
    compliance_score >= 70
      ? 'conforme'
      : compliance_score >= 50
      ? 'vigilance'
      : 'critique'

  const indicators = [
    {
      label: 'TVA',
      sub: risks.rouge > 0 ? 'Anomalie détectée' : 'Conforme',
      cls: risks.rouge > 0 ? 'critique' : 'conforme',
    },
    {
      label: 'Impôt sur les Sociétés',
      sub: 'Acomptes à vérifier',
      cls: 'vigilance',
    },
    {
      label: 'Pièces justificatives',
      sub: nb_anomalies > 2 ? 'Documents manquants' : 'À jour',
      cls: nb_anomalies > 2 ? 'vigilance' : 'conforme',
    },
    {
      label: 'Retenues à la source',
      sub: 'IR/Salaires',
      cls: 'conforme',
    },
    {
      label: 'Règlements en espèces',
      sub: risks.rouge > 1 ? 'Dépassements Art.193' : 'Dans les limites',
      cls: risks.rouge > 1 ? 'critique' : 'conforme',
    },
    {
      label: 'ICE Fournisseurs',
      sub: risks.orange > 0 ? 'ICE manquants détectés' : 'Complets',
      cls: risks.orange > 0 ? 'vigilance' : 'conforme',
    },
  ]

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">{company}</div>
          {/* « données en temps réel » était faux : ces chiffres viennent
              d'un audit enregistré, pas d'un calcul continu. On affiche sa
              date — c'est ce qui permet de savoir si on regarde un état
              récent ou un état oublié. */}
          <div className="section-sub">
            {auditDate
              ? `Analyse du ${new Date(auditDate).toLocaleString('fr-MA', { dateStyle: 'long', timeStyle: 'short' })}`
              : 'Analyse fiscale enregistrée'}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={onRunAudit}
            disabled={auditLoading}
          >
            {auditLoading ? (
              <span className="spinner dark" />
            ) : (
              <RefreshCw size={13} />
            )}
            Actualiser l'audit
          </button>
        </div>
      </div>

      {auditLoading && (
        <div className="alert info" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div>
            Actualisation de l'audit en cours — les chiffres ci-dessous datent encore de la précédente analyse.
          </div>
        </div>
      )}

      {!auditLoading && resultatPerime && (
        <div className="alert info" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div>
            <strong>Ces chiffres ne sont plus à jour</strong> — les données comptables ont changé depuis la dernière
            analyse. Cliquez sur « Actualiser l'audit » pour les recalculer.
          </div>
        </div>
      )}

      {executive_summary && (
        <div className={`exec-summary-card exec-summary-card--${scoreCls}`}>
          <div className="exec-summary-left">
            {/* Carré plein, pas un anneau SVG : même langage que le reste du
                design (statut = carré coloré), et compliance_score est une
                vraie donnée mesurée par l'audit — contrairement au score
                cabinet global, qui lui n'existe pas côté API. */}
            <div className={`exec-summary-score-box ${scoreCls}`}>{compliance_score}</div>

            <div className="exec-summary-text">
              <div className="exec-summary-label">Résumé exécutif</div>
              <div className="exec-summary-body">{executive_summary}</div>

              {top_urgency && (
                <div className="exec-summary-urgency">
                  Urgence : <strong>{top_urgency.title}</strong>

                  {top_urgency.invoice && (
                    <span
                      className="mono"
                      style={{ marginLeft: 6, opacity: 0.8 }}
                    >
                      {top_urgency.invoice}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          <button
            className="exec-summary-cta"
            onClick={() => onGoToAudit?.()}
          >
            Voir les anomalies <ArrowRight size={13} />
          </button>
        </div>
      )}

      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Score de conformité</div>
          <div className={`kpi-value ${scoreCls}`}>{compliance_score}</div>
          <div className="kpi-sub">sur 100</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Anomalies critiques</div>
          <div
            className={`kpi-value ${
              risks.rouge ? 'critique' : 'conforme'
            }`}
          >
            {risks.rouge}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Alertes modérées</div>
          <div
            className={`kpi-value ${
              risks.orange ? 'vigilance' : 'conforme'
            }`}
          >
            {risks.orange}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Exposition estimée</div>
          <div className="kpi-value critique mono">
            {total_exposure_dh.toLocaleString('fr-MA')}
          </div>
        </div>
      </div>

      {/* Deux chiffres MESURÉS (exposition détectée / régularisée) et un
          chiffre ESTIMÉ (temps épargné) — l'hypothèse du temps est affichée
          à côté du chiffre, jamais cachée derrière : même exigence que le
          reste du produit ("zéro affirmation sans source"). */}
      {roi && (
        <div className="card roi-card" style={{ marginTop: 16 }}>
          <div className="card-header">
            <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <PiggyBank size={14} style={{ color: 'var(--seuil)' }} />
              Valeur générée sur ce dossier
            </span>
          </div>
          <div className="roi-grid">
            <div className="roi-item">
              <div
                className="roi-item-label"
                title={`Sur ${roi.exposition_detectee_dh.toLocaleString('fr-MA')} DH détectés au total.`}
              >
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
            {/* Échéances À VENIR, jamais mélangé aux anomalies déjà
                détectées ci-dessus — seule la TVA a une base chiffrable
                (TVA facturée - déductible dans les écritures). */}
            {roi.nb_echeances_suivies > 0 && (
              <div className="roi-item">
                <div
                  className="roi-item-label"
                  title={`${roi.nb_echeances_base_connue}/${roi.nb_echeances_suivies} échéance(s) chiffrable(s) (TVA uniquement).`}
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

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 340px',
          gap: 16,
          marginTop: 16,
        }}
      >
        <div>
          <div className="card">
            <div className="card-header">
              <span className="card-title">Scores de risque</span>
            </div>

            <div className="card-body">
              <GaugeSeuil
                label="Score de Conformité Globale"
                score={compliance_score}
                threshold={70}
              />

              <GaugeSeuil
                label="Score de Préparation à l'Audit"
                score={Math.max(0, compliance_score - 8)}
                threshold={75}
              />

              <GaugeSeuil
                label="Score de Risque Fiscal"
                score={Math.min(100, nb_anomalies * 12)}
                threshold={60}
              />
            </div>
          </div>

          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-header">
              <span className="card-title">
                Indicateurs de conformité
              </span>
            </div>

            <div className="card-body">
              <div className="indicators-grid">
                {indicators.map((indicator, i) => (
                  <Indicator key={i} {...indicator} />
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <CalendarClock size={14} style={{ color: 'var(--seuil)' }} />
              Prochaines échéances
            </span>
            <span
              style={{ fontSize: 11, color: 'var(--seuil)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3 }}
              onClick={() => onGoToCalendar?.()}
            >
              Tout voir <ArrowRight size={11} />
            </span>
          </div>

          <div className="card-body" style={{ padding: 0 }}>
            {eventsLoading ? (
              <div style={{ padding: '20px 16px', textAlign: 'center' }}>
                <span className="spinner dark" style={{ width: 18, height: 18 }} />
              </div>
            ) : upcomingEvents.length === 0 ? (
              <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--sourdine)', textAlign: 'center' }}>
                Aucune échéance dans les 6 prochains mois.
              </div>
            ) : (
              upcomingEvents.map((e, i) => {
                const dt = parseDate(e.date)
                const urgencyCls = e.urgency === 'critique' ? 'critique' : e.urgency === 'urgent' ? 'vigilance' : 'conforme'
                return (
                  <div key={i} className="list-row">
                    {dt && (
                      <div className="list-date">
                        <div className="list-date-day">{dt.day}</div>
                        <div className="list-date-month">{dt.month}</div>
                      </div>
                    )}
                    <div className="list-body">
                      <div className="list-title" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {e.title}
                      </div>
                      <div className="list-sub">{e.category}</div>
                    </div>
                    <Badge cls={urgencyCls} small>{e.urgency}</Badge>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </div>
    </div>
  )
}