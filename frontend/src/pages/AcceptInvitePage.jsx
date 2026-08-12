import { useState } from 'react'
import { API_URL, setAccessToken } from '../config/api'

export default function AcceptInvitePage({ token, onAccepted }) {
  const [nomComplet, setNomComplet] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/invitations/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, nom_complet: nomComplet, password }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail
        throw new Error(detail || "Impossible d'accepter cette invitation.")
      }
      const data = await res.json()
      setAccessToken(data.access_token)
      localStorage.setItem('nisab_refresh_token', data.refresh_token)
      onAccepted()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>Nisab</h1>
        <p className="auth-subtitle">Finalisez la création de votre compte</p>
        <label>
          Nom complet
          <input value={nomComplet} onChange={(e) => setNomComplet(e.target.value)} required />
        </label>
        <label>
          Mot de passe
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        </label>
        {error && <div className="auth-error">{error}</div>}
        <button type="submit" disabled={loading}>{loading ? 'Patientez…' : 'Créer mon compte'}</button>
      </form>
    </div>
  )
}
