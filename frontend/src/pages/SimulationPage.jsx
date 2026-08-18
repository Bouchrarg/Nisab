import { useState } from 'react'
import { Gavel, ChevronDown, ChevronUp, ShieldAlert, Download, History, Eye } from 'lucide-react'
import Badge from '../components/ui/Badge'

function ThemeCard({ theme }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div
        className="card-body"
        style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        onClick={() => setOpen((o) => !o)}
      >
        <div>
          <div style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--encre)', marginBottom: 4 }}>{theme.theme}</div>
          <div style={{ fontSize: 11.5, color: 'var(--sourdine)' }}>
            {theme.nb_alertes} anomalie(s) liée(s)
            {theme.articles_cites?.length > 0 && ` · ${theme.articles_cites.join(', ')}`}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {theme.exposition_totale_mad > 0 && (
            <span className="mono" style={{ color: 'var(--critique)', fontSize: 12.5, fontWeight: 600 }}>
              −{Number(theme.exposition_totale_mad).toLocaleString('fr-MA')} DH
            </span>
          )}
          {open ? <ChevronUp size={14} color="var(--sourdine)" /> : <ChevronDown size={14} color="var(--sourdine)" />}
        </div>
      </div>

      {open && (
        <div style={{ padding: '0 16px 16px' }}>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--sourdine)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
              Argumentaire de défense
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
              {theme.argumentaire}
            </div>
          </div>
          {theme.plan_remediation && (
            <div style={{
              background: 'color-mix(in srgb, var(--seuil) 6%, transparent)',
              border: '1px solid color-mix(in srgb, var(--seuil) 20%, transparent)',
              borderRadius: 6, padding: '10px 14px',
            }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--seuil)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
                Plan de remédiation
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {theme.plan_remediation}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SimulationHistory({ history, activeId, onView, onExport }) {
  const [open, setOpen] = useState(false)
  if (!history || history.length === 0) return null

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div
        className="card-body"
        style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        onClick={() => setOpen((o) => !o)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <History size={14} color="var(--sourdine)" />
          <span style={{ fontWeight: 600, fontSize: 13 }}>Historique des simulations</span>
          <span style={{ fontSize: 11.5, color: 'var(--sourdine)' }}>({history.length})</span>
        </div>
        {open ? <ChevronUp size={14} color="var(--sourdine)" /> : <ChevronDown size={14} color="var(--sourdine)" />}
      </div>

      {open && (
        <div style={{ padding: '0 16px 12px' }}>
          {history.map((s) => (
            <div
              key={s.id}
              style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 0', borderTop: '1px solid var(--bordure)',
              }}
            >
              <div>
                <div style={{ fontSize: 12.5, fontWeight: s.id === activeId ? 600 : 400, color: 'var(--encre)' }}>
                  {new Date(s.created_at).toLocaleDateString('fr-MA', { day: 'numeric', month: 'short', year: 'numeric' })}
                  {' '}
                  {new Date(s.created_at).toLocaleTimeString('fr-MA', { hour: '2-digit', minute: '2-digit' })}
                  {s.id === activeId && (
                    <span style={{ marginLeft: 8 }}>
                      <Badge cls="seuil">Affichée</Badge>
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 11, color: 'var(--sourdine)' }}>
                  {s.nb_themes} theme(s) · {Number(s.exposition_totale_mad || 0).toLocaleString('fr-MA')} DH d'exposition
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => onView(s.id)} disabled={s.id === activeId}>
                  <Eye size={13} />
                  Voir
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => onExport(s.id)}>
                  <Download size={13} />
                  PDF
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SimulationPage({ simulation, history, onRunSimulation, onExportPdf, onViewSimulation, loading, hasData }) {
  if (!hasData) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon"><Gavel size={22} /></div>
        <div className="empty-state-title">Aucune donnée à analyser</div>
        <div className="empty-state-sub">Chargez d'abord des données comptables via l'onglet Synchronisation ERP, puis lancez l'audit fiscal.</div>
      </div>
    )
  }

  const rapport = simulation?.rapport || null
  const themes = rapport?.themes || []
  // plan_remediation est stocké séparément (simulation_controle.plan_remediation_json)
  // mais indexé par thème dans le même ordre — on le fusionne pour l'affichage.
  const planByTheme = Object.fromEntries(
    (simulation?.plan_remediation?.themes || []).map((t) => [t.theme, t.plan_remediation])
  )
  const themesWithPlan = themes.map((t) => ({ ...t, plan_remediation: planByTheme[t.theme] }))

  return (
    <div>
      <div className="section-header" style={{ alignItems: 'center' }}>
        <div>
          <div className="section-sub">
            Rejoue les points qu'un inspecteur DGI examinerait, à partir des alertes actives du dossier.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {themes.length > 0 && (
            <button className="btn btn-secondary btn-sm" onClick={() => onExportPdf()}>
              <Download size={13} />
              Exporter en PDF
            </button>
          )}
          <button className="btn btn-primary btn-sm" onClick={onRunSimulation} disabled={loading}>
            {loading ? <span className="spinner" /> : <Gavel size={13} />}
            Lancer la simulation de contrôle
          </button>
        </div>
      </div>

      <div className="alert vigilance" style={{ marginBottom: 16 }}>
        <ShieldAlert size={14} />
        <div>
          <strong>Usage interne uniquement</strong> — ce rapport reste dans votre cabinet, rien n'est transmis à la DGI.
        </div>
      </div>

      <SimulationHistory
        history={history}
        activeId={simulation?.id}
        onView={onViewSimulation}
        onExport={onExportPdf}
      />

      {!simulation ? (
        <div className="empty-state">
          <div className="empty-state-icon"><Gavel size={22} /></div>
          <div className="empty-state-title">Aucune simulation lancée pour ce dossier</div>
          <div className="empty-state-sub">Cliquez sur « Lancer la simulation de contrôle » pour générer un rapport à partir des alertes actives.</div>
        </div>
      ) : themes.length === 0 ? (
        <div className="alert conforme">
          <div className="alert-dot" />
          <div>
            <strong>{rapport?.message || "Aucune alerte de risque ouverte — rien à simuler pour le moment."}</strong>
          </div>
        </div>
      ) : (
        <>
          <div className="kpi-grid" style={{ marginBottom: 16 }}>
            <div className="kpi-card">
              <div className="kpi-label">Thèmes examinés</div>
              <div className="kpi-value">{themes.length}</div>
              <div className="kpi-sub">points de contrôle</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Exposition totale</div>
              <div className="kpi-value critique mono">
                {themes.reduce((s, t) => s + (t.exposition_totale_mad || 0), 0).toLocaleString('fr-MA')} DH
              </div>
              <div className="kpi-sub">cumul des thèmes</div>
            </div>
            {simulation.created_at && (
              <div className="kpi-card">
                <div className="kpi-label">Dernière simulation</div>
                <div className="kpi-value" style={{ fontSize: 13 }}>
                  {new Date(simulation.created_at).toLocaleDateString('fr-MA', { day: 'numeric', month: 'short', year: 'numeric' })}
                </div>
                <div className="kpi-sub">{new Date(simulation.created_at).toLocaleTimeString('fr-MA', { hour: '2-digit', minute: '2-digit' })}</div>
              </div>
            )}
          </div>

          {themesWithPlan.map((t, i) => <ThemeCard key={i} theme={t} />)}
        </>
      )}
    </div>
  )
}
