import { useCallback, useEffect, useState } from 'react'
import {
  RefreshCw, Building2, Users, FolderKanban, ShieldAlert, CalendarClock,
  FileSearch2, ArrowRight, Landmark,
} from 'lucide-react'
import Badge from '../../components/ui/Badge'
import { apiFetch } from '../../config/api'

const ROLE_LABELS = {
  collaborateur: 'Collaborateurs',
  dirigeant_pme: 'Dirigeants PME',
  admin_cabinet: 'Admins cabinet',
  admin_plateforme: 'Admins plateforme',
}

const NIVEAU_CLS = { faible: 'conforme', moyen: 'vigilance', eleve: 'critique' }

function orgTypeLabel(type) {
  if (type === 'cabinet') return 'Cabinet'
  if (type === 'interne') return 'Interne'
  return 'PME'
}

function orgTypeBadgeCls(type) {
  if (type === 'cabinet') return 'seuil'
  if (type === 'interne') return 'vigilance'
  return 'neutral'
}

function formatMAD(n) {
  return new Intl.NumberFormat('fr-MA', { maximumFractionDigits: 0 }).format(n || 0) + ' MAD'
}

function timeAgo(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const diffMs = Date.now() - d.getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return "à l'instant"
  if (mins < 60) return `il y a ${mins} min`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `il y a ${hrs} h`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `il y a ${days} j`
  return d.toLocaleDateString('fr-MA')
}

export default function PlatformOverviewPage({ onNavigate }) {
  const [data, setData] = useState(null)
  const [corpusStats, setCorpusStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [ov, cs] = await Promise.all([
        apiFetch('/admin/platform/overview'),
        apiFetch('/admin/corpus/stats'),
      ])
      if (ov.ok) {
        setData(await ov.json())
      } else {
        const detail = (await ov.json().catch(() => null))?.detail
        setError(detail || `Impossible de charger les statistiques plateforme (HTTP ${ov.status}).`)
      }
      if (cs.ok) setCorpusStats(await cs.json())
    } catch {
      setError('Impossible de contacter le serveur.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  if (loading && !data) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <span className="spinner dark" style={{ width: 22, height: 22 }} />
      </div>
    )
  }

  const roleEntries = Object.entries(data?.utilisateurs?.par_role || {}).filter(([, n]) => n > 0)
  const validArticles = corpusStats?.arts
    ? corpusStats.arts.find?.((a) => a.statut === 'valide')?.n
    : null

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-sub">
            Tous les cabinets et PME confondus — organisations, utilisateurs, dossiers et risques suivis par Nisab.
          </div>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={fetchAll} disabled={loading}>
          {loading ? <span className="spinner dark" /> : <RefreshCw size={13} />}
          Actualiser
        </button>
      </div>

      {error && (
        <div className="alert critique" style={{ marginBottom: 16 }}>
          <div className="alert-dot" />
          <div style={{ fontSize: 12 }}>{error}</div>
        </div>
      )}

      {/* ── KPIs principaux ─────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 12, marginBottom: 20 }}>
        <div className="kpi-card">
          <div className="kpi-label"><Building2 size={12} style={{ verticalAlign: -2, marginRight: 4 }} />Organisations</div>
          <div className="kpi-value seuil">{data?.organisations?.total ?? '—'}</div>
          <div className="kpi-sub">{data?.organisations?.cabinets ?? 0} cabinets · {data?.organisations?.pme ?? 0} PME</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><Users size={12} style={{ verticalAlign: -2, marginRight: 4 }} />Utilisateurs</div>
          <div className="kpi-value">{data?.utilisateurs?.total ?? '—'}</div>
          <div className="kpi-sub">
            {roleEntries.slice(0, 2).map(([r, n]) => `${n} ${ROLE_LABELS[r] || r}`).join(' · ') || 'Aucun'}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><FolderKanban size={12} style={{ verticalAlign: -2, marginRight: 4 }} />Dossiers fiscaux</div>
          <div className="kpi-value">{data?.dossiers?.total ?? '—'}</div>
          <div className="kpi-sub">Toutes organisations confondues</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><ShieldAlert size={12} style={{ verticalAlign: -2, marginRight: 4 }} />Alertes ouvertes</div>
          <div className={`kpi-value ${(data?.alertes?.ouvertes ?? 0) > 0 ? 'vigilance' : 'conforme'}`}>
            {data?.alertes?.ouvertes ?? '—'}
          </div>
          <div className="kpi-sub">sur {data?.alertes?.total ?? 0} au total</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><Landmark size={12} style={{ verticalAlign: -2, marginRight: 4 }} />Exposition financière</div>
          <div className="kpi-value critique" style={{ fontSize: 20 }}>
            {formatMAD(data?.alertes?.exposition_totale_mad)}
          </div>
          <div className="kpi-sub">Cumul des alertes ouvertes</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><CalendarClock size={12} style={{ verticalAlign: -2, marginRight: 4 }} />Échéances à venir</div>
          <div className="kpi-value">{data?.echeances?.a_venir ?? '—'}</div>
          <div className="kpi-sub">sur {data?.echeances?.total ?? 0} suivies</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><FileSearch2 size={12} style={{ verticalAlign: -2, marginRight: 4 }} />Simulations de contrôle</div>
          <div className="kpi-value">{data?.simulations?.total ?? '—'}</div>
          <div className="kpi-sub">Réalisées à ce jour</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Corpus fiscal validé</div>
          <div className="kpi-value conforme">{corpusStats?.valid_articles ?? '—'}</div>
          <div className="kpi-sub" onClick={() => onNavigate?.('corpus')} style={{ cursor: 'pointer', color: 'var(--seuil)' }}>
            Voir le corpus <ArrowRight size={10} style={{ verticalAlign: -1 }} />
          </div>
        </div>
      </div>

      {/* ── Répartition des rôles + alertes par niveau ──────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Répartition des utilisateurs par rôle</span>
          </div>
          <div className="card-body">
            {roleEntries.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--sourdine)' }}>Aucun utilisateur enregistré.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {roleEntries.map(([role, n]) => {
                  const pct = data.utilisateurs.total ? Math.round((n / data.utilisateurs.total) * 100) : 0
                  return (
                    <div key={role}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                        <span style={{ color: 'var(--ardoise)' }}>{ROLE_LABELS[role] || role}</span>
                        <span className="mono" style={{ color: 'var(--encre)', fontWeight: 600 }}>{n} ({pct}%)</span>
                      </div>
                      <div style={{ height: 6, borderRadius: 4, background: 'var(--toile)', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${pct}%`, background: 'var(--seuil)', borderRadius: 4 }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Alertes de risque ouvertes par niveau</span>
            <Badge cls="vigilance">{data?.alertes?.ouvertes ?? 0} ouvertes</Badge>
          </div>
          <div className="card-body">
            {['eleve', 'moyen', 'faible'].map((niveau) => {
              const n = data?.alertes?.par_niveau?.[niveau] ?? 0
              const total = data?.alertes?.ouvertes || 1
              const pct = Math.round((n / total) * 100)
              return (
                <div key={niveau} style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                    <Badge cls={NIVEAU_CLS[niveau]} dot>{niveau === 'eleve' ? 'Élevé' : niveau === 'moyen' ? 'Moyen' : 'Faible'}</Badge>
                    <span className="mono" style={{ color: 'var(--encre)', fontWeight: 600 }}>{n}</span>
                  </div>
                  <div style={{ height: 6, borderRadius: 4, background: 'var(--toile)', overflow: 'hidden' }}>
                    <div style={{
                      height: '100%', width: `${pct}%`, borderRadius: 4,
                      background: niveau === 'eleve' ? 'var(--critique)' : niveau === 'moyen' ? 'var(--vigilance)' : 'var(--conforme)',
                    }} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* ── Activité récente ─────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Organisations récentes</span>
            <span
              style={{ fontSize: 11, color: 'var(--seuil)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3 }}
              onClick={() => onNavigate?.('organisations')}
            >
              Tout voir <ArrowRight size={11} />
            </span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {(data?.recent_organisations || []).length === 0 ? (
              <div style={{ padding: 20, fontSize: 12, color: 'var(--sourdine)' }}>Aucune organisation pour l'instant.</div>
            ) : (
              data.recent_organisations.map((o, i) => (
                <div key={o.id} style={{
                  padding: '11px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  borderBottom: i < data.recent_organisations.length - 1 ? '1px solid var(--bordure)' : 'none',
                }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--encre)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {o.nom}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--sourdine)' }}>
                      {o.nb_users} utilisateur(s) · {o.nb_dossiers} dossier(s) · {timeAgo(o.created_at)}
                    </div>
                  </div>
                  <Badge cls={orgTypeBadgeCls(o.type_organisation)}>
                    {orgTypeLabel(o.type_organisation)}
                  </Badge>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Utilisateurs récents</span>
            <span
              style={{ fontSize: 11, color: 'var(--seuil)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3 }}
              onClick={() => onNavigate?.('users')}
            >
              Tout voir <ArrowRight size={11} />
            </span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {(data?.recent_users || []).length === 0 ? (
              <div style={{ padding: 20, fontSize: 12, color: 'var(--sourdine)' }}>Aucun utilisateur pour l'instant.</div>
            ) : (
              data.recent_users.map((u, i) => (
                <div key={u.id} style={{
                  padding: '11px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  borderBottom: i < data.recent_users.length - 1 ? '1px solid var(--bordure)' : 'none',
                }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--encre)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {u.nom_complet || u.email}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--sourdine)' }}>
                      {u.organisation_nom} · {timeAgo(u.created_at)}
                    </div>
                  </div>
                  <Badge cls="neutral">{ROLE_LABELS[u.role] || u.role}</Badge>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Alertes de risque récentes (tous dossiers)</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {(data?.recent_alertes || []).length === 0 ? (
            <div style={{ padding: 20, fontSize: 12, color: 'var(--sourdine)' }}>Aucune alerte détectée pour l'instant.</div>
          ) : (
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--bordure)', textAlign: 'left' }}>
                  {['Alerte', 'Dossier', 'Organisation', 'Niveau', 'Détectée'].map((h) => (
                    <th key={h} style={{ padding: '8px 16px', fontWeight: 500, color: 'var(--sourdine)', fontSize: 11 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.recent_alertes.map((a) => (
                  <tr key={a.id} style={{ borderBottom: '1px solid var(--bordure)' }}>
                    <td style={{ padding: '8px 16px', color: 'var(--encre)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.titre}</td>
                    <td style={{ padding: '8px 16px', color: 'var(--ardoise)' }}>{a.dossier_raison_sociale}</td>
                    <td style={{ padding: '8px 16px', color: 'var(--ardoise)' }}>{a.organisation_nom}</td>
                    <td style={{ padding: '8px 16px' }}>
                      <Badge cls={NIVEAU_CLS[a.niveau_risque] || 'neutral'} dot>
                        {a.niveau_risque === 'eleve' ? 'Élevé' : a.niveau_risque === 'moyen' ? 'Moyen' : 'Faible'}
                      </Badge>
                    </td>
                    <td style={{ padding: '8px 16px', color: 'var(--sourdine)', fontSize: 11 }}>{timeAgo(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
