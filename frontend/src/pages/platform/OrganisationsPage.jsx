import { useCallback, useEffect, useState } from 'react'
import { Search, ChevronLeft, ChevronRight, X, Building2, Users, FolderKanban } from 'lucide-react'
import Badge from '../../components/ui/Badge'
import { apiFetch } from '../../config/api'

const ROLE_LABELS = {
  collaborateur: 'Collaborateur',
  dirigeant_pme: 'Dirigeant PME',
  admin_cabinet: 'Admin cabinet',
  admin_plateforme: 'Admin plateforme',
}

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

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('fr-MA', { year: 'numeric', month: 'short', day: 'numeric' })
}

export default function OrganisationsPage() {
  const [orgs, setOrgs] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [q, setQ] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [loading, setLoading] = useState(true)

  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const fetchOrgs = useCallback(async (p = 1, query = q, type = typeFilter) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(p), limit: '20' })
      if (query) params.set('q', query)
      if (type) params.set('type_organisation', type)
      const res = await apiFetch(`/admin/platform/organisations?${params.toString()}`)
      if (res.ok) {
        const d = await res.json()
        setOrgs(d.organisations || [])
        setTotal(d.total || 0)
        setPage(d.page || 1)
        setPages(d.pages || 1)
      }
    } finally {
      setLoading(false)
    }
  }, [q, typeFilter])

  useEffect(() => {
    fetchOrgs(1, q, typeFilter)
  }, [typeFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = async (id) => {
    setDetailLoading(true)
    setDetail({ id })
    try {
      const res = await apiFetch(`/admin/platform/organisations/${id}`)
      if (res.ok) setDetail(await res.json())
    } finally {
      setDetailLoading(false)
    }
  }

  const handleSearchSubmit = (e) => {
    e.preventDefault()
    fetchOrgs(1, q, typeFilter)
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-sub">Cabinets comptables et PME clientes, tous tenants confondus ({total} au total).</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <form onSubmit={handleSearchSubmit} style={{ position: 'relative', flex: '1 1 240px', maxWidth: 320 }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: 9, color: 'var(--sourdine)' }} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher une organisation…"
            style={{
              width: '100%', padding: '7px 10px 7px 30px', fontSize: 12.5,
              borderRadius: 8, border: '1px solid var(--bordure)',
            }}
          />
        </form>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          style={{ fontSize: 12, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--bordure)' }}
        >
          <option value="">Tous les types</option>
          <option value="cabinet">Cabinets</option>
          <option value="pme">PME</option>
          <option value="interne">Interne (plateforme)</option>
        </select>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: detail ? '1.3fr 1fr' : '1fr', gap: 16, alignItems: 'start' }}>
        <div className="card">
          <div className="card-body" style={{ padding: 0 }}>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 40 }}><span className="spinner dark" /></div>
            ) : orgs.length === 0 ? (
              <div style={{ padding: 32, textAlign: 'center', fontSize: 12.5, color: 'var(--sourdine)' }}>
                Aucune organisation ne correspond à ces critères.
              </div>
            ) : (
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--bordure)', textAlign: 'left' }}>
                    {['Organisation', 'Type', 'Utilisateurs', 'Dossiers', 'Créée le'].map((h) => (
                      <th key={h} style={{ padding: '8px 16px', fontWeight: 500, color: 'var(--sourdine)', fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {orgs.map((o) => (
                    <tr
                      key={o.id}
                      onClick={() => openDetail(o.id)}
                      style={{
                        borderBottom: '1px solid var(--bordure)', cursor: 'pointer',
                        background: detail?.id === o.id ? 'var(--toile)' : 'transparent',
                      }}
                    >
                      <td style={{ padding: '10px 16px', fontWeight: 600, color: 'var(--encre)' }}>{o.nom}</td>
                      <td style={{ padding: '10px 16px' }}>
                        <Badge cls={orgTypeBadgeCls(o.type_organisation)}>
                          {orgTypeLabel(o.type_organisation)}
                        </Badge>
                      </td>
                      <td style={{ padding: '10px 16px', color: 'var(--ardoise)' }}>{o.nb_users}</td>
                      <td style={{ padding: '10px 16px', color: 'var(--ardoise)' }}>{o.nb_dossiers}</td>
                      <td style={{ padding: '10px 16px', color: 'var(--sourdine)', fontSize: 11 }}>{fmtDate(o.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {pages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', gap: 12, padding: 14, alignItems: 'center' }}>
                <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => fetchOrgs(page - 1)}>
                  <ChevronLeft size={13} />
                </button>
                <span style={{ fontSize: 12, color: 'var(--sourdine)' }}>Page {page} / {pages}</span>
                <button className="btn btn-secondary btn-sm" disabled={page >= pages} onClick={() => fetchOrgs(page + 1)}>
                  <ChevronRight size={13} />
                </button>
              </div>
            )}
          </div>
        </div>

        {detail && (
          <div className="card">
            <div className="card-header">
              <span className="card-title">{detail.nom || 'Chargement…'}</span>
              <X size={15} style={{ cursor: 'pointer', color: 'var(--sourdine)' }} onClick={() => setDetail(null)} />
            </div>
            <div className="card-body">
              {detailLoading ? (
                <div style={{ textAlign: 'center', padding: 24 }}><span className="spinner dark" /></div>
              ) : (
                <>
                  <div style={{ display: 'flex', gap: 10, marginBottom: 18 }}>
                    <Badge cls={orgTypeBadgeCls(detail.type_organisation)}>
                      <Building2 size={11} /> {orgTypeLabel(detail.type_organisation)}
                    </Badge>
                    <Badge cls="neutral"><Users size={11} /> {detail.nb_users} utilisateur(s)</Badge>
                    <Badge cls="neutral"><FolderKanban size={11} /> {detail.nb_dossiers} dossier(s)</Badge>
                  </div>

                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--sourdine)', textTransform: 'uppercase', marginBottom: 8 }}>
                    Utilisateurs
                  </div>
                  {(detail.utilisateurs || []).length === 0 ? (
                    <div style={{ fontSize: 12, color: 'var(--sourdine)', marginBottom: 16 }}>Aucun utilisateur.</div>
                  ) : (
                    <div style={{ marginBottom: 18 }}>
                      {detail.utilisateurs.map((u) => (
                        <div key={u.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--bordure)', fontSize: 12.5 }}>
                          <div>
                            <div style={{ fontWeight: 600, color: 'var(--encre)' }}>{u.nom_complet || '(sans nom)'}</div>
                            <div style={{ fontSize: 11, color: 'var(--sourdine)' }}>{u.email}</div>
                          </div>
                          <Badge cls="neutral">{ROLE_LABELS[u.role] || u.role}</Badge>
                        </div>
                      ))}
                    </div>
                  )}

                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--sourdine)', textTransform: 'uppercase', marginBottom: 8 }}>
                    Dossiers fiscaux
                  </div>
                  {(detail.dossiers || []).length === 0 ? (
                    <div style={{ fontSize: 12, color: 'var(--sourdine)' }}>Aucun dossier.</div>
                  ) : (
                    detail.dossiers.map((d) => (
                      <div key={d.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--bordure)', fontSize: 12.5 }}>
                        <div>
                          <div style={{ fontWeight: 600, color: 'var(--encre)' }}>{d.raison_sociale}</div>
                          <div style={{ fontSize: 11, color: 'var(--sourdine)' }}>{d.secteur_activite || 'Secteur non renseigné'}</div>
                        </div>
                        {d.nb_alertes_ouvertes > 0 ? (
                          <Badge cls="vigilance">{d.nb_alertes_ouvertes} alerte(s)</Badge>
                        ) : (
                          <Badge cls="conforme">Conforme</Badge>
                        )}
                      </div>
                    ))
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
