import { Fragment, useEffect, useState } from 'react'
import { Copy, Plus, Trash2, Ban, RotateCcw } from 'lucide-react'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import Badge from '../components/ui/Badge'

const ROLE_LABELS = { collaborateur: 'Collaborateur', dirigeant_pme: 'Dirigeant PME', admin_cabinet: 'Admin cabinet' }
const STATUT_LABELS = { en_attente: 'En attente', acceptee: 'Acceptée', revoquee: 'Révoquée' }
const NIVEAU_LABELS = { lecture: 'Lecture', ecriture: 'Lecture + audit/simulation', admin: 'Lecture + audit/simulation + synchro données' }

export default function InvitationsPage() {
  const { dossiers } = useDossier()
  const [invitations, setInvitations] = useState([])
  const [membres, setMembres] = useState([])
  const [loading, setLoading] = useState(true)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('collaborateur')
  const [dossierId, setDossierId] = useState('')
  const [niveauDroit, setNiveauDroit] = useState('ecriture')
  const [creating, setCreating] = useState(false)
  const [lastLink, setLastLink] = useState(null)
  const [error, setError] = useState(null)
  const [revokingId, setRevokingId] = useState(null)
  const [togglingId, setTogglingId] = useState(null)
  const [assigningMembreId, setAssigningMembreId] = useState(null)
  const [assignDossierId, setAssignDossierId] = useState('')
  const [assignNiveau, setAssignNiveau] = useState('ecriture')
  const [grantingId, setGrantingId] = useState(null)

  const load = () => {
    setLoading(true)
    Promise.all([
      apiFetch('/invitations').then((r) => r.json()),
      apiFetch('/invitations/membres').then((r) => r.json()),
    ])
      .then(([inv, mem]) => {
        setInvitations(inv)
        setMembres(mem)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const toggleMembre = async (membre) => {
    const activating = !membre.actif
    if (!activating && !window.confirm(`Désactiver le compte de ${membre.email} ? Il ne pourra plus se connecter (réversible).`)) return
    setTogglingId(membre.id)
    setError(null)
    try {
      const res = await apiFetch(`/invitations/membres/${membre.id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ actif: activating }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail
        throw new Error(detail || 'Échec de la mise à jour.')
      }
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setTogglingId(null)
    }
  }

  const openAssign = (membreId) => {
    setAssigningMembreId(assigningMembreId === membreId ? null : membreId)
    setAssignDossierId('')
    setAssignNiveau('ecriture')
    setError(null)
  }

  const grantAcces = async (membreId) => {
    if (!assignDossierId) return
    setGrantingId(membreId)
    setError(null)
    try {
      const res = await apiFetch(`/invitations/membres/${membreId}/acces`, {
        method: 'POST',
        body: JSON.stringify({ dossier_id: assignDossierId, niveau_droit: assignNiveau }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail
        throw new Error(detail || "Échec de l'attribution.")
      }
      setAssigningMembreId(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setGrantingId(null)
    }
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    setCreating(true)
    setError(null)
    setLastLink(null)
    try {
      const res = await apiFetch('/invitations', {
        method: 'POST',
        body: JSON.stringify({ email, role, dossier_id: dossierId || null, niveau_droit: niveauDroit }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail
        throw new Error(detail || "Échec de l'invitation.")
      }
      const data = await res.json()
      setLastLink(`${window.location.origin}${data.lien}`)
      setEmail('')
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setCreating(false)
    }
  }

  const revoke = async (id) => {
    if (!window.confirm('Révoquer cette invitation ? Le lien deviendra inutilisable.')) return
    setRevokingId(id)
    setError(null)
    try {
      const res = await apiFetch(`/invitations/${id}`, { method: 'DELETE' })
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail
        throw new Error(detail || 'Échec de la révocation.')
      }
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setRevokingId(null)
    }
  }

  // Historique complet gardé (une invitation acceptée reste dans la liste :
  // la cacher a fait disparaître des lignes que le cabinet s'attendait à
  // retrouver). Seule différence pour une ligne acceptée : plus discrète
  // (elle est déjà, en vrai, dans "Membres" juste au-dessus) et sans
  // colonne d'action puisqu'il n'y a plus rien à faire dessus.
  const initiale = (str) => (str || '?').trim().charAt(0).toUpperCase()

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-sub">Invitez des collaborateurs ou des dirigeants PME dans votre cabinet.</div>
        </div>
      </div>

      <form className="dossier-create-card" onSubmit={handleCreate}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Rôle
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="collaborateur">Collaborateur</option>
            <option value="dirigeant_pme">Dirigeant PME</option>
          </select>
        </label>
        <label>
          Dossier associé (optionnel)
          <select value={dossierId} onChange={(e) => setDossierId(e.target.value)}>
            <option value="">— Aucun —</option>
            {dossiers.map((d) => (
              <option key={d.id} value={d.id}>{d.raison_sociale}</option>
            ))}
          </select>
        </label>
        <label>
          Niveau d'accès
          {role === 'dirigeant_pme' ? (
            <select value="lecture" disabled>
              <option value="lecture">Lecture (fixe — client final en lecture seule)</option>
            </select>
          ) : (
            <select value={niveauDroit} onChange={(e) => setNiveauDroit(e.target.value)}>
              <option value="lecture">{NIVEAU_LABELS.lecture}</option>
              <option value="ecriture">{NIVEAU_LABELS.ecriture}</option>
              <option value="admin">{NIVEAU_LABELS.admin}</option>
            </select>
          )}
        </label>
        <div className="dossier-create-actions">
          <button type="submit" className="btn btn-primary btn-sm" disabled={creating}>
            <Plus size={14} /> {creating ? 'Envoi…' : 'Inviter'}
          </button>
        </div>
      </form>

      {error && <div className="alert critique" style={{ marginBottom: 16 }}>{error}</div>}

      {lastLink && (
        <div className="alert info" style={{ marginBottom: 16, alignItems: 'center' }}>
          <div style={{ fontSize: 12, flex: 1 }}>
            Lien à transmettre manuellement (pas d'envoi d'e-mail automatique pour l'instant) :<br />
            <code>{lastLink}</code>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={() => navigator.clipboard.writeText(lastLink)}>
            <Copy size={13} /> Copier
          </button>
        </div>
      )}

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <span className="spinner dark" style={{ width: 22, height: 22 }} />
        </div>
      ) : (
        <>
          <h3 style={{ fontSize: 13, margin: '24px 0 8px' }}>Membres (comptes actifs)</h3>
          <table className="invitations-table">
            <thead>
              <tr>
                <th>Email</th><th>Rôle</th><th>Dossiers assignés</th><th>Statut</th><th>Membre depuis</th><th></th>
              </tr>
            </thead>
            <tbody>
              {membres.map((m) => (
                <Fragment key={m.id}>
                  <tr>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="member-avatar">{initiale(m.email)}</span>
                        {m.email}
                      </div>
                    </td>
                    <td>{ROLE_LABELS[m.role] || m.role}</td>
                    <td style={{ fontSize: 11.5 }}>
                      {m.role === 'admin_cabinet' ? (
                        <span style={{ color: 'var(--sourdine)' }}>Tous (admin_cabinet)</span>
                      ) : m.acces.length === 0 ? (
                        <span style={{ color: 'var(--sourdine)' }}>Aucun</span>
                      ) : (
                        m.acces.map((a) => `${a.raison_sociale} (${NIVEAU_LABELS[a.niveau_droit] || a.niveau_droit})`).join(', ')
                      )}
                    </td>
                    <td><Badge cls={m.actif ? 'conforme' : 'critique'} small>{m.actif ? 'Actif' : 'Désactivé'}</Badge></td>
                    <td>{new Date(m.created_at).toLocaleDateString('fr-FR')}</td>
                    <td style={{ display: 'flex', gap: 6 }}>
                      {m.role !== 'admin_cabinet' && (
                        <>
                          <button className="btn btn-secondary btn-sm" onClick={() => openAssign(m.id)} title="Assigner un dossier">
                            <Plus size={13} /> Assigner
                          </button>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => toggleMembre(m)}
                            disabled={togglingId === m.id}
                            title={m.actif ? 'Désactiver ce compte' : 'Réactiver ce compte'}
                          >
                            {togglingId === m.id ? <span className="spinner" /> : m.actif ? <Ban size={13} /> : <RotateCcw size={13} />}
                            {m.actif ? 'Désactiver' : 'Réactiver'}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                  {assigningMembreId === m.id && (
                    <tr>
                      <td colSpan={6} style={{ background: 'var(--toile)', padding: 12 }}>
                        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                          <label style={{ fontSize: 11.5 }}>
                            Dossier
                            <select value={assignDossierId} onChange={(e) => setAssignDossierId(e.target.value)}>
                              <option value="">— Choisir —</option>
                              {dossiers.map((d) => (
                                <option key={d.id} value={d.id}>{d.raison_sociale}</option>
                              ))}
                            </select>
                          </label>
                          {m.role === 'dirigeant_pme' ? (
                            <span style={{ fontSize: 11.5, color: 'var(--sourdine)' }}>Niveau : Lecture (fixe)</span>
                          ) : (
                            <label style={{ fontSize: 11.5 }}>
                              Niveau
                              <select value={assignNiveau} onChange={(e) => setAssignNiveau(e.target.value)}>
                                <option value="lecture">{NIVEAU_LABELS.lecture}</option>
                                <option value="ecriture">{NIVEAU_LABELS.ecriture}</option>
                                <option value="admin">{NIVEAU_LABELS.admin}</option>
                              </select>
                            </label>
                          )}
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => grantAcces(m.id)}
                            disabled={!assignDossierId || grantingId === m.id}
                          >
                            {grantingId === m.id ? <span className="spinner" /> : 'Confirmer'}
                          </button>
                          <button className="btn btn-secondary btn-sm" onClick={() => setAssigningMembreId(null)}>Annuler</button>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {membres.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--ardoise)' }}>Aucun membre pour l'instant.</td></tr>
              )}
            </tbody>
          </table>

          <h3 style={{ fontSize: 13, margin: '24px 0 8px' }}>Invitations envoyées</h3>
          <table className="invitations-table">
            <thead>
              <tr>
                <th>Email</th><th>Rôle</th><th>Niveau</th><th>Statut</th><th>Expire le</th><th></th>
              </tr>
            </thead>
            <tbody>
              {invitations.map((i) => (
                <tr key={i.id} style={i.statut === 'acceptee' ? { opacity: 0.55 } : undefined}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="member-avatar">{initiale(i.email)}</span>
                      {i.email}
                    </div>
                  </td>
                  <td>{ROLE_LABELS[i.role] || i.role}</td>
                  <td style={{ fontSize: 11.5, color: 'var(--sourdine)' }}>{NIVEAU_LABELS[i.niveau_droit] || i.niveau_droit}</td>
                  <td><Badge cls={i.statut === 'acceptee' ? 'conforme' : i.statut === 'revoquee' ? 'critique' : 'vigilance'} small>{STATUT_LABELS[i.statut]}</Badge></td>
                  <td>{new Date(i.expires_at).toLocaleDateString('fr-FR')}</td>
                  <td>
                    {i.statut === 'en_attente' && (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => revoke(i.id)}
                        disabled={revokingId === i.id}
                      >
                        {revokingId === i.id ? <span className="spinner" /> : <Trash2 size={13} />} Révoquer
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {invitations.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--ardoise)' }}>Aucune invitation envoyée.</td></tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
