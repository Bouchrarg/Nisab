import { useEffect, useState } from 'react'
import { apiFetch } from '../config/api'
import { useAuth } from '../context/AuthContext'
import Badge from '../components/ui/Badge'

const ROLE_LABELS = {
  collaborateur: 'Collaborateur',
  dirigeant_pme: 'Dirigeant PME',
  admin_cabinet: 'Administrateur du cabinet',
  admin_plateforme: 'Administrateur plateforme',
}

// Une phrase, pas un paragraphe : ce que le rôle change concrètement pour
// CE compte, dans la section "Mes accès" — plutôt que de laisser deviner
// la différence entre les 4 rôles à partir du seul libellé.
const ROLE_DESCRIPTIONS = {
  admin_cabinet: 'Accès complet à tous les dossiers du cabinet, y compris la gestion de l’équipe.',
  admin_plateforme: 'Accès plateforme (tous cabinets et PME), séparé des dossiers d’un cabinet en particulier.',
  collaborateur: 'Accès limité aux dossiers assignés ci-dessous, chacun à son propre niveau.',
  dirigeant_pme: 'Accès en lecture seule au(x) dossier(s) de votre entreprise, assigné(s) ci-dessous.',
}

const NIVEAU_LABELS = { lecture: 'Lecture', ecriture: 'Lecture + audit/simulation', admin: 'Lecture + audit/simulation + synchro données' }

export default function ProfilePage() {
  const { user, logout, refreshUser } = useAuth()
  const [nomComplet, setNomComplet] = useState(user?.nom_complet || '')
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileMsg, setProfileMsg] = useState(null)

  const [current, setCurrent] = useState('')
  const [nextPwd, setNextPwd] = useState('')
  const [savingPwd, setSavingPwd] = useState(false)
  const [pwdMsg, setPwdMsg] = useState(null)

  // L'accès "tous les dossiers" d'un admin_cabinet vient de son rôle
  // (tenant_guard.py), pas de la table Acces — inutile d'appeler l'API
  // pour afficher une liste qui sera de toute façon vide pour ce rôle.
  const [acces, setAcces] = useState([])
  const [accesLoading, setAccesLoading] = useState(false)
  const showsAccesList = user && user.role !== 'admin_cabinet' && user.role !== 'admin_plateforme'

  useEffect(() => {
    if (!showsAccesList) return
    setAccesLoading(true)
    apiFetch('/auth/me/acces')
      .then((r) => (r.ok ? r.json() : []))
      .then(setAcces)
      .catch(() => setAcces([]))
      .finally(() => setAccesLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id])

  const saveProfile = async (e) => {
    e.preventDefault()
    setSavingProfile(true)
    setProfileMsg(null)
    try {
      const res = await apiFetch('/auth/me', { method: 'PATCH', body: JSON.stringify({ nom_complet: nomComplet }) })
      if (!res.ok) throw new Error('Échec de la mise à jour.')
      await refreshUser()
      setProfileMsg({ type: 'ok', text: 'Profil mis à jour.' })
    } catch (err) {
      setProfileMsg({ type: 'error', text: err.message })
    } finally {
      setSavingProfile(false)
    }
  }

  const savePassword = async (e) => {
    e.preventDefault()
    setSavingPwd(true)
    setPwdMsg(null)
    try {
      const res = await apiFetch('/auth/me/password', {
        method: 'POST',
        body: JSON.stringify({ mot_de_passe_actuel: current, nouveau_mot_de_passe: nextPwd }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail
        throw new Error(detail || 'Échec du changement de mot de passe.')
      }
      setCurrent('')
      setNextPwd('')
      setPwdMsg({ type: 'ok', text: 'Mot de passe mis à jour.' })
    } catch (err) {
      setPwdMsg({ type: 'error', text: err.message })
    } finally {
      setSavingPwd(false)
    }
  }

  if (!user) return null

  const membreDepuis = user.created_at
    ? new Date(user.created_at).toLocaleDateString('fr-FR')
    : null

  return (
    <div className="profile-page">
      <div className="section-header">
        <div>
          <div className="section-sub">Gérez vos informations personnelles et les paramètres de votre compte.</div>
        </div>
      </div>
      <div className="profile-meta">
        {user.organisation_nom} · {ROLE_LABELS[user.role] || user.role}
        {membreDepuis && <> · Membre depuis le {membreDepuis}</>}
      </div>

      <div className="settings-grid">
        <form className="card settings-card-primary" onSubmit={saveProfile}>
          <div className="card-header" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
            <span className="card-title">Informations personnelles</span>
          </div>
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <label className="settings-field">
              Email
              <input value={user.email} disabled />
            </label>
            <label className="settings-field">
              Nom complet
              <input value={nomComplet} onChange={(e) => setNomComplet(e.target.value)} />
            </label>
            {profileMsg && <div className={`profile-msg ${profileMsg.type}`}>{profileMsg.text}</div>}
            <button type="submit" className="btn btn-primary btn-sm" disabled={savingProfile} style={{ alignSelf: 'flex-start' }}>
              {savingProfile ? 'Enregistrement…' : 'Enregistrer'}
            </button>
          </div>
        </form>

        {/* Légèrement plus discrète que "Informations personnelles" : cette
            carte reste plate (pas de --shadow-entity comme sur la carte
            de gauche), seule différence de traitement entre les deux. */}
        <form className="card" onSubmit={savePassword}>
          <div className="card-header" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
            <span className="card-title">Mot de passe</span>
            <span className="card-sub">Modifiez régulièrement votre mot de passe pour sécuriser votre compte.</span>
          </div>
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <label className="settings-field">
              Mot de passe actuel
              <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </label>
            <label className="settings-field">
              Nouveau mot de passe
              <input type="password" value={nextPwd} onChange={(e) => setNextPwd(e.target.value)} required minLength={8} />
            </label>
            {pwdMsg && <div className={`profile-msg ${pwdMsg.type}`}>{pwdMsg.text}</div>}
            <button type="submit" className="btn btn-secondary btn-sm" disabled={savingPwd} style={{ alignSelf: 'flex-start' }}>
              {savingPwd ? 'Enregistrement…' : 'Changer le mot de passe'}
            </button>
          </div>
        </form>
      </div>

      <div className="card" style={{ marginTop: 20 }}>
        <div className="card-header">
          <span className="card-title">Accès au cabinet</span>
          <Badge cls="neutral" small>{ROLE_LABELS[user.role] || user.role}</Badge>
        </div>
        <div className="card-body">
          <div className="profile-role-desc">{ROLE_DESCRIPTIONS[user.role] || ''}</div>
          {showsAccesList && (
            accesLoading ? (
              <div style={{ fontSize: 12, color: 'var(--sourdine)', marginTop: 10 }}>Chargement…</div>
            ) : acces.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--sourdine)', marginTop: 10 }}>Aucun dossier assigné pour l'instant.</div>
            ) : (
              <div className="calendar-list" style={{ marginTop: 12 }}>
                {acces.map((a) => (
                  <div key={a.dossier_id} className="list-row">
                    <div className="list-body">
                      <div className="list-title">{a.raison_sociale}</div>
                    </div>
                    <span className="citation-source-tag">{NIVEAU_LABELS[a.niveau_droit] || a.niveau_droit}</span>
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      </div>

      {/* Action secondaire, pas une alerte : un lien discret qui ne prend
          la couleur d'accent qu'au survol, pas un bouton plein en rouge vif
          — se déconnecter n'est pas une action destructive. */}
      <div className="card" style={{ marginTop: 20 }}>
        <div className="card-header">
          <span className="card-title">Session</span>
        </div>
        <div className="card-body">
          <button className="logout-link" onClick={logout}>
            Se déconnecter <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </div>
  )
}
