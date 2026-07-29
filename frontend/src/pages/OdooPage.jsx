import { useState } from 'react'
import { Link2, Zap, CheckCircle2 } from 'lucide-react'
import { API_URL } from '../config/api'

export default function OdooPage({ onConnected, onDemoLoaded }) {
  const [form, setForm] = useState({ url: '', db: '', username: '', password: '' })
  const [loading, setLoading] = useState(false)
  const [demoLoading, setDemoLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const handleConnect = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API_URL}/odoo/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || 'Échec de connexion')
      }
      const data = await res.json()
      setResult(data)
      onConnected?.(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleDemo = async () => {
    setDemoLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API_URL}/odoo/demo`)
      if (!res.ok) throw new Error('Erreur serveur')
      const data = await res.json()
      setResult(data)
      onDemoLoaded?.(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setDemoLoading(false)
    }
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Synchronisation ERP</div>
          <div className="section-sub">Connexion à Odoo pour l'extraction des données comptables</div>
        </div>
      </div>

      <div className="connect-grid">
        <div className="card">
          <div className="card-header">
            <span className="card-title">Connexion Odoo</span>
            <span className="badge seuil" style={{ display: 'inline-flex', alignItems: 'center' }}>
              <span className="badge-dot" style={{ background: 'currentColor' }} />XML-RPC
            </span>
          </div>
          <div className="card-body">
            {[
              { key: 'url', label: 'URL de l\'instance', placeholder: 'https://monentreprise.odoo.com' },
              { key: 'db', label: 'Base de données', placeholder: 'nom-de-la-base' },
              { key: 'username', label: 'Identifiant', placeholder: 'admin@entreprise.ma' },
              { key: 'password', label: 'Mot de passe ou clé API', placeholder: '••••••••', type: 'password' },
            ].map(({ key, label, placeholder, type = 'text' }) => (
              <div className="form-group" key={key}>
                <label className="form-label">{label}</label>
                <input
                  type={type}
                  className="form-input"
                  placeholder={placeholder}
                  value={form[key]}
                  onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                />
              </div>
            ))}
            <button
              className="btn btn-primary"
              onClick={handleConnect}
              disabled={loading || !form.url || !form.db || !form.username}
            >
              {loading ? <span className="spinner" /> : <Link2 size={13} />}
              Se connecter
            </button>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Mode démonstration</span>
            <span className="badge neutral">Atlas Négoce SARL</span>
          </div>
          <div className="card-body">
            <p style={{ fontSize: 13, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 16 }}>
              Chargez un jeu de données simulé reproduisant les écritures comptables d'une PME marocaine avec des anomalies fiscales typiques, pour explorer les fonctionnalités d'audit sans connexion ERP.
            </p>
            <ul className="feature-list">
              <li><CheckCircle2 size={13} /> 4 anomalies fiscales CGI pré-configurées</li>
              <li><CheckCircle2 size={13} /> 7 écritures comptables représentatives</li>
              <li><CheckCircle2 size={13} /> Exposition estimée : 15 000 MAD</li>
              <li><CheckCircle2 size={13} /> Aucune connexion Odoo requise</li>
            </ul>
            <button className="btn btn-secondary" onClick={handleDemo} disabled={demoLoading}>
              {demoLoading ? <span className="spinner dark" /> : <Zap size={13} />}
              Charger les données de démonstration
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="alert critique" style={{ marginTop: 16 }}>
          <div className="alert-dot" />
          <div><strong>Erreur de connexion</strong> — {error}</div>
        </div>
      )}
      {result && (
        <div className="alert conforme" style={{ marginTop: 16 }}>
          <div className="alert-dot" />
          <div>
            Données chargées — <strong>{result.company}</strong> ·{' '}
            <span className="mono">{result.nb_moves}</span> écriture(s),{' '}
            <span className="mono">{result.nb_partners}</span> tiers.
            Rendez-vous dans <strong>Audit</strong> pour lancer l'analyse.
          </div>
        </div>
      )}
    </div>
  )
}
