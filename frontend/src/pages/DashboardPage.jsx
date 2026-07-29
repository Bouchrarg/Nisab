import { useEffect, useState } from 'react'
import {
  Building2, RefreshCw, ArrowRight, Bell, Newspaper,
} from 'lucide-react'
import { API_URL } from '../config/api'
import Badge from '../components/ui/Badge'
import GaugeSeuil from '../components/ui/GaugeSeuil'
import Indicator from '../components/ui/Indicator'

const TYPE_COLORS = { 'CGI': 'seuil', 'Bulletin Officiel': 'vigilance', 'Circulaire DGI': 'conforme', 'Loi de Finances': 'critique' }

export default function DashboardPage({ summary, onRunAudit, auditLoading, findings, onGoToAudit }) {
  const [lawFeed, setLawFeed] = useState([])
  const [notifOpen, setNotifOpen] = useState(false)
  const [lawLimit, setLawLimit] = useState(5)

  useEffect(() => {
    fetch(`${API_URL}/law/feed?mode=per_label&limit=${encodeURIComponent(lawLimit)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setLawFeed(d.feed || []) })
      .catch(() => {})
  }, [lawLimit])

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
            <Building2 size={22} />
          </div>
          <div className="empty-state-title">Aucune donnée comptable chargée</div>
          <div className="empty-state-sub">
            Connectez-vous à votre instance Odoo ou chargez les données de démonstration pour démarrer l'analyse fiscale.
          </div>
          <button className="btn btn-primary" onClick={() => { }}>
            Synchroniser les données
          </button>
        </div>
      </div>
    )
  }

  const { company, nb_anomalies, risks, total_exposure_dh, compliance_score, executive_summary, top_urgency } = summary
  const scoreCls = compliance_score >= 70 ? 'conforme' : compliance_score >= 50 ? 'vigilance' : 'critique'
  const criticalFindings = (findings || []).filter(f => f.severity === 'rouge')

  const indicators = [
    { label: 'TVA', sub: risks.rouge > 0 ? 'Anomalie détectée' : 'Conforme', cls: risks.rouge > 0 ? 'critique' : 'conforme' },
    { label: 'Impôt sur les Sociétés', sub: 'Acomptes à vérifier', cls: 'vigilance' },
    { label: 'Pièces justificatives', sub: nb_anomalies > 2 ? 'Documents manquants' : 'À jour', cls: nb_anomalies > 2 ? 'vigilance' : 'conforme' },
    { label: 'Retenues à la source', sub: 'IR/Salaires', cls: 'conforme' },
    { label: 'Règlements en espèces', sub: risks.rouge > 1 ? 'Dépassements Art. 193' : 'Dans les limites', cls: risks.rouge > 1 ? 'critique' : 'conforme' },
    { label: 'ICE Fournisseurs', sub: risks.orange > 0 ? 'ICE manquants détectés' : 'Complets', cls: risks.orange > 0 ? 'vigilance' : 'conforme' },
  ]

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">{company}</div>
          <div className="section-sub">Analyse fiscale — données en temps réel</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ position: 'relative' }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setNotifOpen(o => !o)}
              style={{ position: 'relative', padding: '6px 10px' }}
              title="Alertes fiscales"
            >
              <Bell size={14} />
              {criticalFindings.length > 0 && (
                <span className="notif-badge">{criticalFindings.length}</span>
              )}
            </button>
            {notifOpen && (
              <div className="notif-panel">
                <div className="notif-panel-header">
                  <span className="notif-panel-title">Alertes critiques</span>
                  <button className="copilot-icon-btn" onClick={() => setNotifOpen(false)}>✕</button>
                </div>
                {criticalFindings.length === 0 ? (
                  <div style={{ padding: '16px 14px', fontSize: 12, color: 'var(--sourdine)', textAlign: 'center' }}>
                    Aucune alerte critique active
                  </div>
                ) : (
                  criticalFindings.map((f, i) => (
                    <div key={i} className="notif-item" onClick={() => { setNotifOpen(false); onGoToAudit?.() }}>
                      <div className="notif-item-dot critique" />
                      <div>
                        <div className="notif-item-title">{f.title}</div>
                        <div className="notif-item-sub">{f.invoice} · {Number(f.amount_risk).toLocaleString('fr-MA')} DH</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onRunAudit} disabled={auditLoading}>
            {auditLoading ? <span className="spinner dark" /> : <RefreshCw size={13} />}
            Actualiser l'audit
          </button>
        </div>
      </div>

      {executive_summary && (
        <div className={`exec-summary-card exec-summary-card--${scoreCls}`}>
          <div className="exec-summary-left">
            <div className="exec-summary-score-ring">
              <svg viewBox="0 0 40 40" width="56" height="56">
                <circle cx="20" cy="20" r="16" fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="4" />
                <circle
                  cx="20" cy="20" r="16" fill="none"
                  stroke="rgba(255,255,255,0.9)" strokeWidth="4"
                  strokeDasharray={`${(compliance_score / 100) * 100.53} 100.53`}
                  strokeLinecap="round"
                  transform="rotate(-90 20 20)"
                />
              </svg>
              <span className="exec-summary-score-num">{compliance_score}</span>
            </div>
            <div className="exec-summary-text">
              <div className="exec-summary-label">Résumé exécutif</div>
              <div className="exec-summary-body">{executive_summary}</div>
              {top_urgency && (
                <div className="exec-summary-urgency">
                  Urgence: <strong>{top_urgency.title}</strong>
                  {top_urgency.invoice && <span className="mono" style={{ marginLeft: 6, opacity: 0.8 }}>{top_urgency.invoice}</span>}
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
          <div className="kpi-sub">sur 100 — seuil : 70</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Anomalies critiques</div>
          <div className={`kpi-value ${risks.rouge > 0 ? 'critique' : 'conforme'}`}>{risks.rouge}</div>
          <div className="kpi-sub">redressement probable</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Alertes modérées</div>
          <div className={`kpi-value ${risks.orange > 0 ? 'vigilance' : 'conforme'}`}>{risks.orange}</div>
          <div className="kpi-sub">à régulariser</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Exposition estimée</div>
          <div className="kpi-value critique mono" style={{ fontSize: 18 }}>{total_exposure_dh.toLocaleString('fr-MA')}</div>
          <div className="kpi-sub">MAD — redressements + pénalités</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16, marginBottom: 16 }}>
        <div>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Scores de risque</span>
            </div>
            <div className="card-body">
              <GaugeSeuil label="Score de Conformité Globale" score={compliance_score} threshold={70} />
              <GaugeSeuil label="Score de Préparation à l'Audit" score={Math.max(0, compliance_score - 8)} threshold={75} />
              <GaugeSeuil label="Score de Risque Fiscal" score={Math.min(100, nb_anomalies * 12)} threshold={60} />
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <span className="card-title">Indicateurs de conformité</span>
              <span style={{ fontSize: 11, color: 'var(--sourdine)' }}>Par domaine fiscal</span>
            </div>
            <div className="card-body">
              <div className="indicators-grid">
                {indicators.map((ind, i) => <Indicator key={i} {...ind} />)}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Newspaper size={14} style={{ color: 'var(--seuil)' }} />
              Veille légale
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ fontSize: 13, color: 'var(--sourdine)', fontWeight: 600 }}>Par label</div>
              <input type="number" value={lawLimit} min={1} max={50} onChange={e => setLawLimit(Number(e.target.value))} style={{ width: 56, fontSize: 12, padding: '4px 6px' }} />
              <Badge cls="seuil">Corpus actif</Badge>
            </div>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {lawFeed.length === 0 ? (
              <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--sourdine)', textAlign: 'center' }}>
                Chargement de la veille légale…
              </div>
            ) : (
              lawFeed.map((item, i) => (
                <div key={item.id} className="law-feed-item" style={{
                  borderBottom: i < lawFeed.length - 1 ? '1px solid var(--bordure)' : 'none',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <Badge cls={TYPE_COLORS[item.type] || 'neutral'}>{item.type}</Badge>
                    <span style={{ fontSize: 10, color: 'var(--sourdine)', fontFamily: 'var(--font-mono)' }}>{item.date}</span>
                  </div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--encre)', marginBottom: 3, lineHeight: 1.3 }}>{item.title}</div>
                  <div style={{ fontSize: 11.5, color: 'var(--sourdine)', lineHeight: 1.5 }}>{item.summary}</div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
