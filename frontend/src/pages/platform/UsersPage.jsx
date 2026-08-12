import { useCallback, useEffect, useState } from 'react'
import { Search, ChevronLeft, ChevronRight, Plus, Copy, Ban, RotateCcw } from 'lucide-react'
import Badge from '../../components/ui/Badge'
import { apiFetch } from '../../config/api'

const INVITABLE_ROLE_LABELS = {
  collaborateur: 'Collaborateur',
  dirigeant_pme: 'Dirigeant PME',
  admin_cabinet: 'Admin cabinet',
}

const ROLE_LABELS = {
  collaborateur: 'Collaborateur',
  dirigeant_pme: 'Dirigeant PME',
  admin_cabinet: 'Admin cabinet',
  admin_plateforme: 'Admin plateforme',
}

const ROLE_BADGE_CLS = {
  collaborateur: 'neutral',
  dirigeant_pme: 'neutral',
  admin_cabinet: 'seuil',
  admin_plateforme: 'critique',
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

function initials(name, email) {
  const src = (name || '').trim() || email || '?'
  const parts = src.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return src.slice(0, 2).toUpperCase()
}

export default function UsersPage() {
  const [users, setUsers] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [q, setQ] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [actingId, setActingId] = useState(null)

  const [showInvite, setShowInvite] = useState(false)
  const [organisations, setOrganisations] = useState([])
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('collaborateur')
  const [inviteOrgId, setInviteOrgId] = useState('')
  const [inviting, setInviting] = useState(false)
  const [inviteError, setInviteError] = useState(null)
  const [inviteLink, setInviteLink] = useState(null)

  const fetchUsers = useCallback(async (p = 1, query = q, role = roleFilter) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(p), limit: '25' })
      if (query) params.set('q', query)
      if (role) params.set('role', role)
      const res = await apiFetch(`/admin/platform/users?${params.toString()}`)
      if (res.ok) {
        const d = await res.json()
        setUsers(d.users || [])
        setTotal(d.total || 0)
        setPage(d.page || 1)
        setPages(d.pages || 1)
      }
    } finally {
      setLoading(false)
    }
  }, [q, roleFilter])

  useEffect(() => {
    fetchUsers(1, q, roleFilter)
  }, [roleFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSearchSubmit = (e) => {
    e.preventDefault()
    fetchUsers(1, q, roleFilter)
  }

  const toggleStatus = async (user) => {
    const activating = !user.actif
    if (!activating && !window.confirm(`Désactiver le compte de ${user.email} ? Il ne pourra plus se connecter (réversible).`)) return
    setActingId(user.id)
    try {
      const res = await apiFetch(`/admin/platform/users/${user.id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ actif: activating }),
      })
      if (res.ok) fetchUsers(page, q, roleFilter)
    } finally {
      setActingId(null)
    }
  }

  const openInvite = async () => {
    setShowInvite((v) => !v)
    setInviteLink(null)
    setInviteError(null)
    if (organisations.length === 0) {
      const res = await apiFetch('/admin/platform/organisations?limit=100')
      if (res.ok) {
        const d = await res.json()
        setOrganisations(d.organisations || [])
        if (d.organisations?.length > 0) setInviteOrgId(d.organisations[0].id)
      }
    }
  }

  const handleInvite = async (e) => {
    e.preventDefault()
    setInviting(true)
    setInviteError(null)
    setInviteLink(null)
    try {
      const res = await apiFetch('/admin/platform/users/invite', {
        method: 'POST',
        body: JSON.stringify({ email: inviteEmail, role: inviteRole, organisation_id: inviteOrgId }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail
        throw new Error(detail || "Échec de l'invitation.")
      }
      const data = await res.json()
      setInviteLink(`${window.location.origin}${data.lien}`)
      setInviteEmail('')
    } catch (err) {
      setInviteError(err.message)
    } finally {
      setInviting(false)
    }
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Utilisateurs</div>
          <div className="section-sub">Tous les comptes de la plateforme, cabinets et PME confondus ({total} au total).</div>
        </div>
        <button className="btn btn-primary btn-sm" onClick={openInvite}>
          <Plus size={14} /> Inviter un utilisateur
        </button>
      </div>

      {showInvite && (
        <form className="dossier-create-card" onSubmit={handleInvite} style={{ marginBottom: 16 }}>
          <label>
            Email
            <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required />
          </label>
          <label>
            Rôle
            <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
              {Object.entries(INVITABLE_ROLE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
          <label>
            Organisation
            <select value={inviteOrgId} onChange={(e) => setInviteOrgId(e.target.value)} required>
              {organisations.length === 0 && <option value="">Chargement…</option>}
              {organisations.map((o) => (
                <option key={o.id} value={o.id}>{o.nom} ({o.type_organisation === 'cabinet' ? 'Cabinet' : o.type_organisation === 'pme' ? 'PME' : 'Interne'})</option>
              ))}
            </select>
          </label>
          <div className="dossier-create-actions">
            <button type="submit" className="btn btn-primary btn-sm" disabled={inviting || !inviteOrgId}>
              {inviting ? 'Envoi…' : 'Inviter'}
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowInvite(false)}>
              Fermer
            </button>
          </div>
          {inviteError && (
            <div className="alert critique" style={{ marginTop: 12 }}>{inviteError}</div>
          )}
          {inviteLink && (
            <div className="alert info" style={{ marginTop: 12, alignItems: 'center' }}>
              <div style={{ fontSize: 12, flex: 1 }}>
                Lien à transmettre manuellement (pas d'envoi d'e-mail automatique pour l'instant) :<br />
                <code>{inviteLink}</code>
              </div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigator.clipboard.writeText(inviteLink)}>
                <Copy size={13} /> Copier
              </button>
            </div>
          )}
        </form>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <form onSubmit={handleSearchSubmit} style={{ position: 'relative', flex: '1 1 240px', maxWidth: 320 }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: 9, color: 'var(--sourdine)' }} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher par nom ou e-mail…"
            style={{
              width: '100%', padding: '7px 10px 7px 30px', fontSize: 12.5,
              borderRadius: 8, border: '1px solid var(--bordure)',
            }}
          />
        </form>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          style={{ fontSize: 12, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--bordure)' }}
        >
          <option value="">Tous les rôles</option>
          {Object.entries(ROLE_LABELS).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
      </div>

      <div className="card">
        <div className="card-body" style={{ padding: 0 }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 40 }}><span className="spinner dark" /></div>
          ) : users.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', fontSize: 12.5, color: 'var(--sourdine)' }}>
              Aucun utilisateur ne correspond à ces critères.
            </div>
          ) : (
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--bordure)', textAlign: 'left' }}>
                  {['Utilisateur', 'Organisation', 'Rôle', 'Statut', 'Membre depuis', ''].map((h) => (
                    <th key={h} style={{ padding: '8px 16px', fontWeight: 500, color: 'var(--sourdine)', fontSize: 11 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} style={{ borderBottom: '1px solid var(--bordure)' }}>
                    <td style={{ padding: '10px 16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{
                          width: 28, height: 28, borderRadius: '50%', background: 'var(--seuil-soft)',
                          color: 'var(--seuil)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 11, fontWeight: 700, flexShrink: 0,
                        }}>
                          {initials(u.nom_complet, u.email)}
                        </div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600, color: 'var(--encre)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {u.nom_complet || '(sans nom)'}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--sourdine)' }}>{u.email}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: '10px 16px', color: 'var(--ardoise)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span>{u.organisation_nom}</span>
                        <Badge cls={orgTypeBadgeCls(u.organisation_type)}>
                          {orgTypeLabel(u.organisation_type)}
                        </Badge>
                      </div>
                    </td>
                    <td style={{ padding: '10px 16px' }}>
                      <Badge cls={ROLE_BADGE_CLS[u.role] || 'neutral'}>{ROLE_LABELS[u.role] || u.role}</Badge>
                    </td>
                    <td style={{ padding: '10px 16px' }}>
                      <Badge cls={u.actif ? 'conforme' : 'neutral'} dot>{u.actif ? 'Actif' : 'Désactivé'}</Badge>
                    </td>
                    <td style={{ padding: '10px 16px', color: 'var(--sourdine)', fontSize: 11 }}>{fmtDate(u.created_at)}</td>
                    <td style={{ padding: '10px 16px' }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => toggleStatus(u)}
                        disabled={actingId === u.id}
                        title={u.actif ? 'Désactiver ce compte' : 'Réactiver ce compte'}
                      >
                        {actingId === u.id ? (
                          <span className="spinner" />
                        ) : u.actif ? (
                          <Ban size={13} />
                        ) : (
                          <RotateCcw size={13} />
                        )}
                        {u.actif ? 'Désactiver' : 'Réactiver'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {pages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 12, padding: 14, alignItems: 'center' }}>
              <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => fetchUsers(page - 1)}>
                <ChevronLeft size={13} />
              </button>
              <span style={{ fontSize: 12, color: 'var(--sourdine)' }}>Page {page} / {pages}</span>
              <button className="btn btn-secondary btn-sm" disabled={page >= pages} onClick={() => fetchUsers(page + 1)}>
                <ChevronRight size={13} />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
