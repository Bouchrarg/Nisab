import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function LoginPage() {
  const { login, register } = useAuth()
  // La landing page (frontend/landing/) renvoie vers /#creer pour ouvrir
  // directement le formulaire d'inscription — évite un clic de bascule
  // supplémentaire depuis un lien marketing. N'affecte personne d'autre :
  // sans ce hash, le comportement par défaut ('login') est inchangé.
  const [mode, setMode] = useState(window.location.hash === '#creer' ? 'register' : 'login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nomOrganisation, setNomOrganisation] = useState('')
  const [typeOrganisation, setTypeOrganisation] = useState('cabinet')
  const [touched, setTouched] = useState({})
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const touch = (field) => setTouched((t) => ({ ...t, [field]: true }))

  // Validation locale (format, champs requis) — distincte de `error`, qui
  // porte uniquement la réponse du backend (identifiants refusés, etc.).
  // Pattern "touched" : on n'affiche rien tant que l'utilisateur n'a pas
  // quitté le champ une première fois (cf. interaction-and-states.md).
  const fieldErrors = {
    email: !email ? 'Champ requis.' : !EMAIL_RE.test(email) ? "Format d'e-mail invalide." : null,
    password: !password ? 'Champ requis.' : password.length < 8 ? '8 caractères minimum.' : null,
    nomOrganisation: mode === 'register' && !nomOrganisation ? 'Champ requis.' : null,
  }
  const hasErrors = Object.values(fieldErrors).some(Boolean)

  const submit = async (e) => {
    e.preventDefault()
    setTouched({ email: true, password: true, nomOrganisation: true })
    if (hasErrors) return
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
      <div className="auth-split">
        <aside className="auth-aside">
          <p className="auth-wordmark">Nisab</p>
          <p className="auth-statement">
            Copilote fiscal IA pour cabinets comptables et PME marocains.
            Chaque alerte et chaque proposition de correction est sourcée
            sur le CGI — jamais une affirmation sans citation.
          </p>

          {/* Même carte, même contenu que le hero de la landing (frontend/landing/) :
              continuité pour qui vient de cliquer "Créer mon espace cabinet". */}
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
            <h2 className="auth-heading">
              {mode === 'login' ? 'Connexion à votre espace' : 'Créer votre cabinet ou dossier PME'}
            </h2>

            <div className="auth-reveal" data-open={mode === 'register'}>
              <div className="auth-reveal-inner">
                <div className="auth-field">
                  <label htmlFor="nomOrganisation">Nom de l'organisation</label>
                  <input
                    id="nomOrganisation"
                    className={`auth-input${touched.nomOrganisation && fieldErrors.nomOrganisation ? ' is-invalid' : ''}`}
                    value={nomOrganisation}
                    onChange={(e) => setNomOrganisation(e.target.value)}
                    onBlur={() => touch('nomOrganisation')}
                    aria-invalid={mode === 'register' && touched.nomOrganisation && !!fieldErrors.nomOrganisation}
                    aria-describedby="nomOrganisation-error"
                  />
                  {mode === 'register' && touched.nomOrganisation && fieldErrors.nomOrganisation && (
                    <p className="auth-field-error" id="nomOrganisation-error">{fieldErrors.nomOrganisation}</p>
                  )}
                </div>
                <div className="auth-field">
                  <label htmlFor="typeOrganisation">Type</label>
                  <select
                    id="typeOrganisation"
                    className="auth-input"
                    value={typeOrganisation}
                    onChange={(e) => setTypeOrganisation(e.target.value)}
                  >
                    <option value="cabinet">Cabinet comptable</option>
                    <option value="pme">PME</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="auth-field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                className={`auth-input${touched.email && fieldErrors.email ? ' is-invalid' : ''}`}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={() => touch('email')}
                aria-invalid={touched.email && !!fieldErrors.email}
                aria-describedby="email-error"
              />
              {touched.email && fieldErrors.email && (
                <p className="auth-field-error" id="email-error">{fieldErrors.email}</p>
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
              {loading ? 'Patientez…' : mode === 'login' ? 'Se connecter' : 'Créer le compte'}
            </button>

            <button
              type="button"
              className="auth-switch"
              onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
            >
              {mode === 'login' ? 'Pas de compte ? Créer une organisation' : 'Déjà un compte ? Se connecter'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
