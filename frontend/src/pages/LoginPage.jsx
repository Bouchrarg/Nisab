import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nomOrganisation, setNomOrganisation] = useState('')
  const [typeOrganisation, setTypeOrganisation] = useState('cabinet')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (mode === 'login') {
        await login(email, password)
      } else {
        await register({
          nom_organisation: nomOrganisation,
          type_organisation: typeOrganisation,
          email,
          password,
        })
      }
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
        <p className="auth-subtitle">
          {mode === 'login' ? 'Connexion à votre espace' : 'Créer votre cabinet / dossier PME'}
        </p>

        {mode === 'register' && (
          <>
            <label>
              Nom de l'organisation
              <input value={nomOrganisation} onChange={(e) => setNomOrganisation(e.target.value)} required />
            </label>
            <label>
              Type
              <select value={typeOrganisation} onChange={(e) => setTypeOrganisation(e.target.value)}>
                <option value="cabinet">Cabinet comptable</option>
                <option value="pme">PME</option>
              </select>
            </label>
          </>
        )}

        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Mot de passe
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        </label>

        {error && <div className="auth-error">{error}</div>}

        <button type="submit" disabled={loading}>
          {loading ? 'Patientez…' : mode === 'login' ? 'Se connecter' : 'Créer le compte'}
        </button>

        <button
          type="button"
          className="auth-switch"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
        >
          {mode === 'login' ? "Pas encore de compte ? Créer une organisation" : 'Déjà un compte ? Se connecter'}
        </button>
      </form>
    </div>
  )
}
