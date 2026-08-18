import { useState } from 'react'
import { API_URL, setAccessToken } from '../config/api'

export default function AcceptInvitePage({ token, onAccepted }) {
  const [nomComplet, setNomComplet] = useState('')
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState({})
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const touch = (field) => setTouched((t) => ({ ...t, [field]: true }))

  // Même pattern "touched" que LoginPage (cf. sa note) : le message serveur
  // (`error`) reste distinct de la validation locale (`fieldErrors`).
  const fieldErrors = {
    nomComplet: !nomComplet ? 'Champ requis.' : null,
    password: !password ? 'Champ requis.' : password.length < 8 ? '8 caractères minimum.' : null,
  }
  const hasErrors = Object.values(fieldErrors).some(Boolean)

  const submit = async (e) => {
    e.preventDefault()
    setTouched({ nomComplet: true, password: true })
    if (hasErrors) return
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
      <div className="auth-split">
        <aside className="auth-aside">
          <p className="auth-wordmark">Nisab</p>
          <p className="auth-statement">
            Copilote fiscal IA pour cabinets comptables et PME marocains.
            Chaque alerte et chaque proposition de correction est sourcée
            sur le CGI — jamais une affirmation sans citation.
          </p>

          {/* Même carte, même contenu que le hero de la landing et que
              LoginPage : une seule DNA visuelle pour tous les écrans
              d'entrée dans le produit. */}
          <div className="citation-demo">
            <div className="citation-demo-alert"><span className="dot" />Anomalie repérée</div>
            <p className="citation-demo-text">
              Un règlement en espèces de 6 200 DH dépasse la limite autorisée pour ce fournisseur.
            </p>
            <span className="citation-demo-pill">Art. 11-II du CGI</span>
            <p className="citation-demo-excerpt">
              « … règlement en espèces supérieur à 5 000 dirhams par jour et par fournisseur … »
            </p>
          </div>
        </aside>

        <div className="auth-panel">
          <form className="auth-form" onSubmit={submit} noValidate>
            <h2 className="auth-heading">Finalisez votre compte</h2>

            <div className="auth-field">
              <label htmlFor="nomComplet">Nom complet</label>
              <input
                id="nomComplet"
                className={`auth-input${touched.nomComplet && fieldErrors.nomComplet ? ' is-invalid' : ''}`}
                value={nomComplet}
                onChange={(e) => setNomComplet(e.target.value)}
                onBlur={() => touch('nomComplet')}
                aria-invalid={touched.nomComplet && !!fieldErrors.nomComplet}
                aria-describedby="nomComplet-error"
              />
              {touched.nomComplet && fieldErrors.nomComplet && (
                <p className="auth-field-error" id="nomComplet-error">{fieldErrors.nomComplet}</p>
              )}
            </div>

            <div className="auth-field">
              <label htmlFor="password">Mot de passe</label>
              <input
                id="password"
                type="password"
                className={`auth-input${touched.password && fieldErrors.password ? ' is-invalid' : ''}`}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onBlur={() => touch('password')}
                aria-invalid={touched.password && !!fieldErrors.password}
                aria-describedby="password-error"
              />
              {touched.password && fieldErrors.password && (
                <p className="auth-field-error" id="password-error">{fieldErrors.password}</p>
              )}
            </div>

            {error && (
              <div className="auth-alert" role="alert">
                <span className="dot" />
                {error}
              </div>
            )}

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading && <span className="auth-spinner" aria-hidden="true" />}
              {loading ? 'Patientez…' : 'Créer mon compte'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
