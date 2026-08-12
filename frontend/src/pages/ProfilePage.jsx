import { useState } from 'react'
import { apiFetch } from '../config/api'
import { useAuth } from '../context/AuthContext'

const ROLE_LABELS = {
  collaborateur: 'Collaborateur',
  dirigeant_pme: 'Dirigeant PME',
  admin_cabinet: 'Administrateur du cabinet',
  admin_plateforme: 'Administrateur plateforme',
}

export default function ProfilePage() {
  const { user, logout, refreshUser } = useAuth()
  const [nomComplet, setNomComplet] = useState(user?.nom_complet || '')
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileMsg, setProfileMsg] = useState(null)

  const [current, setCurrent] = useState('')
  const [nextPwd, setNextPwd] = useState('')
  const [savingPwd, setSavingPwd] = useState(false)
  const [pwdMsg, setPwdMsg] = useState(null)

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

  return (
    <div className="profile-page">
      <div className="section-header">
        <div>
          <div className="section-title">Mon profil</div>
          <div className="section-sub">{user.organisation_nom} — {ROLE_LABELS[user.role] || user.role}</div>
        </div>
      </div>

      <div className="profile-cards">
        <form className="profile-card" onSubmit={saveProfile}>
          <h3>Informations</h3>
          <label>
            Email
            <input value={user.email} disabled />
          </label>
          <label>
            Nom complet
            <input value={nomComplet} onChange={(e) => setNomComplet(e.target.value)} />
          </label>
          {profileMsg && <div className={`profile-msg ${profileMsg.type}`}>{profileMsg.text}</div>}
          <button type="submit" className="btn btn-primary btn-sm" disabled={savingProfile}>
            {savingProfile ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </form>

        <form className="profile-card" onSubmit={savePassword}>
          <h3>Mot de passe</h3>
          <label>
            Mot de passe actuel
            <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
          </label>
          <label>
            Nouveau mot de passe
            <input type="password" value={nextPwd} onChange={(e) => setNextPwd(e.target.value)} required minLength={8} />
          </label>
          {pwdMsg && <div className={`profile-msg ${pwdMsg.type}`}>{pwdMsg.text}</div>}
          <button type="submit" className="btn btn-primary btn-sm" disabled={savingPwd}>
            {savingPwd ? 'Enregistrement…' : 'Changer le mot de passe'}
          </button>
        </form>
      </div>

      <button className="btn btn-secondary btn-sm" onClick={logout} style={{ marginTop: 16 }}>
        Se déconnecter
      </button>
    </div>
  )
}
