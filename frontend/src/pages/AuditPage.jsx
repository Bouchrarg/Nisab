import { Search } from 'lucide-react'
import FindingCard from '../components/audit/FindingCard'
import { severityToCls } from '../utils/severity'

export default function AuditPage({ findings, onRunAudit, loading, hasData }) {
  if (!hasData) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon"><Search size={22} /></div>
        <div className="empty-state-title">Aucune donnée à analyser</div>
        <div className="empty-state-sub">Chargez d'abord des données comptables via l'onglet Synchronisation ERP.</div>
      </div>
    )
  }
  const total = findings.reduce((s, f) => s + (f.amount_risk || 0), 0)
  const byLevel = { critique: 0, vigilance: 0, conforme: 0 }
  findings.forEach(f => { byLevel[severityToCls(f.severity)]++ })

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Rapport d'audit fiscal</div>
          <div className="section-sub">
            <span className="mono">{findings.length}</span> anomalie(s) détectée(s) — Exposition totale :{' '}
            <span className="mono" style={{ color: 'var(--critique)' }}>{total.toLocaleString('fr-MA')} DH</span>
          </div>
        </div>
        <button className="btn btn-primary btn-sm" onClick={onRunAudit} disabled={loading}>
          {loading ? <span className="spinner" /> : <Search size={13} />}
          Relancer l'analyse
        </button>
      </div>

      <div className="kpi-grid" style={{ marginBottom: 16 }}>
        {[
          { label: 'Critique', value: byLevel.critique, cls: 'critique' },
          { label: 'Modéré', value: byLevel.vigilance, cls: 'vigilance' },
          { label: 'Faible', value: byLevel.conforme, cls: 'conforme' },
        ].map(({ label, value, cls }) => (
          <div className="kpi-card" key={label}>
            <div className="kpi-label">Niveau {label}</div>
            <div className={`kpi-value ${cls}`}>{value}</div>
            <div className="kpi-sub">anomalie(s)</div>
          </div>
        ))}
      </div>

      {findings.length === 0 ? (
        <div className="alert conforme">
          <div className="alert-dot" />
          <div>
            <strong>Aucune anomalie fiscale détectée</strong> — Le dossier présente une bonne conformité au regard des règles du CGI 2026 analysées.
          </div>
        </div>
      ) : (
        <div className="findings-list">
          {findings.map((f, i) => <FindingCard key={i} f={f} />)}
        </div>
      )}
    </div>
  )
}
