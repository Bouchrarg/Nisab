import { useState } from 'react'
import { Link2, Zap, CheckCircle2 } from 'lucide-react'
import { apiFetch } from '../config/api'
import { useDossier } from '../context/DossierContext'
import { useAuth } from '../context/AuthContext'
import ImportFichierCard from '../components/ingestion/ImportFichierCard'
import OcrExtractionCard from '../components/ingestion/OcrExtractionCard'



const DEMO_SCENARIOS = {
  commerce: {
    dossierName: 'Atlas Négoce SARL',
    secteur: 'Négoce',
    badge: 'Commerce',
    description: "Jeu de données simulé reproduisant les écritures comptables d'une PME marocaine avec des anomalies fiscales typiques, pour explorer les fonctionnalités d'audit sans connexion ERP.",
    features: [
      'Anomalies fiscales CGI variées (espèces, ICE, amortissement)',
      '7 écritures comptables représentatives',
      'Montants calculés par règle déterministe, pas estimés',
      'Aucune connexion Odoo requise',
    ],
  },
  conforme: {
    dossierName: 'Rif Distribution SARL',
    secteur: 'Distribution',
    badge: 'Conforme',
    description: "Jeu de données 100% conforme (tous les tiers avec ICE, aucun paiement en espèces) — le seul moyen de voir l'état « audit propre » sans données Odoo réelles déjà nettoyées.",
    features: [
      '0 anomalie fiscale attendue',
      '4 écritures comptables représentatives',
      'Tous les tiers avec ICE renseigné',
      'Aucune connexion Odoo requise',
    ],
  },
  services: {
    dossierName: 'Maroc Digital Services SARL',
    secteur: 'Services',
    badge: 'Services',
    description: 'Société de services avec des anomalies différentes du scénario commerce (retenue à la source, facturation irrégulière), pour varier les thèmes testés en audit/simulation.',
    features: [
      'Anomalies ciblant Article 151 et Article 146',
      '3 écritures comptables représentatives',
      'Thèmes différents du scénario commerce',
      'Aucune connexion Odoo requise',
    ],
  },
}

// Un chargement (démo ou connexion Odoo) ne doit resynchroniser le dossier
// actif QUE s'il s'agit bien de la même entreprise (même nom) — sinon on
// écraserait silencieusement les données d'un autre dossier juste parce
// qu'il se trouvait être actif. Nom différent (ou aucun dossier actif) =
// nouveau dossier.
function isSameDossier(dossier, candidateName) {
  if (!dossier) return false
  return dossier.raison_sociale.trim().toLowerCase() === candidateName.trim().toLowerCase()
}


const ODOO_DB_MAP_KEY = 'nisab_odoo_dossier_par_db'

function litMappingOdooDb() {
  try {
    return JSON.parse(localStorage.getItem(ODOO_DB_MAP_KEY) || '{}')
  } catch {
    return {}
  }
}

function memoriserDossierPourDb(dbName, dossierId) {
  const mapping = litMappingOdooDb()
  mapping[dbName.trim().toLowerCase()] = dossierId
  localStorage.setItem(ODOO_DB_MAP_KEY, JSON.stringify(mapping))
}

// Ne renvoie l'id retenu que s'il correspond encore à un dossier existant
// (accès révoqué, dossier supprimé côté backend...) — sinon on retombe sur
// la création normale plutôt que de viser un id mort.
function dossierConnuPourDb(dbName, dossiers) {
  const id = litMappingOdooDb()[dbName.trim().toLowerCase()]
  if (!id) return null
  return dossiers.some((d) => d.id === id) ? id : null
}

export default function OdooPage({ onConnected, onDemoLoaded }) {
  const [form, setForm] = useState({ url: '', db: '', username: '', password: '', memoriser: false })
  const [loading, setLoading] = useState(false)
  const [demoLoading, setDemoLoading] = useState(false)
  const [demoScenario, setDemoScenario] = useState('commerce')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  // Distinct de `error` : la synchronisation a réussi, seul le renommage
  // automatique du dossier a échoué — un avertissement, pas un échec.
  const [renameWarning, setRenameWarning] = useState(null)
  const { activeDossier, dossiers, createDossier, renameDossier } = useDossier()
  const { user } = useAuth()
  const scenario = DEMO_SCENARIOS[demoScenario]
  // Seul admin_cabinet peut créer un dossier (POST /dossiers, voir
  // require_role côté backend) : pour tout autre rôle, "nom différent =
  // nouveau dossier" est impossible à honorer — il faut toujours charger
  // dans le dossier actif, celui que le cabinet lui a assigné, quel que
  // soit son nom.
  const canCreateDossier = user?.role === 'admin_cabinet'

  const alignDossierName = async (dossierId, usedName, realCompanyName) => {
    if (!realCompanyName || realCompanyName.trim().toLowerCase() === usedName.trim().toLowerCase()) return true
    try {
      await renameDossier(dossierId, realCompanyName)
      return true
    } catch {
      return false
    }
  }


  const resolveDossierId = async (candidateName, secteur) => {
    if (!canCreateDossier) {
      if (!activeDossier) {
        throw new Error("Aucun dossier ne vous est assigné — demandez à votre admin_cabinet de vous en attribuer un (onglet Équipe).")
      }
      return activeDossier.id
    }
    if (isSameDossier(activeDossier, candidateName)) return activeDossier.id
    return (await createDossier({ raison_sociale: candidateName, secteur_activite: secteur })).id
  }


  const confirmerRemplacement = (candidateName) => {
    const ciblera = canCreateDossier ? isSameDossier(activeDossier, candidateName) : !!activeDossier
    if (!ciblera) return true
    return window.confirm(
      `Ceci va REMPLACER entièrement les données comptables déjà présentes dans « ${activeDossier.raison_sociale} ». `
      + "Les écritures actuelles seront perdues si vous n'avez pas de moyen de les réimporter. Continuer ?"
    )
  }

  const handleConnect = async () => {
    const candidateName = form.db || 'Connexion Odoo'
    const dossierConnuId = dossierConnuPourDb(candidateName, dossiers)
    const dossierCible = dossierConnuId
      ? dossiers.find((d) => d.id === dossierConnuId)
      : (canCreateDossier ? (isSameDossier(activeDossier, candidateName) ? activeDossier : null) : activeDossier)
    if (dossierCible) {
      const confirme = window.confirm(
        `Ceci va REMPLACER entièrement les données comptables déjà présentes dans « ${dossierCible.raison_sociale} ». `
        + "Les écritures actuelles seront perdues si vous n'avez pas de moyen de les réimporter. Continuer ?"
      )
      if (!confirme) return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setRenameWarning(null)
    try {
      const dossierId = dossierCible ? dossierCible.id : await resolveDossierId(candidateName, '')
      const res = await apiFetch(`/dossiers/${dossierId}/odoo/connect`, {
        method: 'POST',
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || 'Échec de connexion')
      }
      const data = await res.json()
      // Mémorisé APRÈS succès seulement : un échec de connexion ne doit pas
      // river ce nom de base à un dossier qui n'a en réalité jamais reçu ces
      // données comptables.
      if (canCreateDossier) memoriserDossierPourDb(candidateName, dossierId)
      const aligned = await alignDossierName(dossierId, candidateName, data.company)
      if (!aligned) {
        setRenameWarning(
          `Données chargées, mais le renommage automatique du dossier vers « ${data.company} » a échoué — `
          + `renommez-le manuellement (Profil du dossier), sinon la prochaine connexion à cette même entreprise créera un doublon.`
        )
      }
      setResult(data)
      onConnected?.(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleDemo = async () => {
    if (!confirmerRemplacement(scenario.dossierName)) return
    setDemoLoading(true)
    setError(null)
    setResult(null)
    setRenameWarning(null)
    try {
      const dossierId = await resolveDossierId(scenario.dossierName, scenario.secteur)
      const res = await apiFetch(`/dossiers/${dossierId}/odoo/demo?scenario=${demoScenario}`, { method: 'POST' })
      if (!res.ok) {
        const d = await res.json().catch(() => null)
        throw new Error(d?.detail || 'Erreur serveur')
      }
      const data = await res.json()
      const aligned = await alignDossierName(dossierId, scenario.dossierName, data.company)
      if (!aligned) {
        setRenameWarning(
          `Données chargées, mais le renommage automatique du dossier vers « ${data.company} » a échoué — `
          + `renommez-le manuellement (Profil du dossier), sinon la prochaine connexion à cette même entreprise créera un doublon.`
        )
      }
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
          <div className="section-title">Sources de données</div>
          <div className="section-sub">Connexion ERP, jeu de démonstration ou import de fichier comptable</div>
        </div>
      </div>

      <div className="alert info" style={{ marginBottom: 16 }}>
        <div className="alert-dot" />
        <div>
          {activeDossier
            ? <>Dossier actif : <strong>{activeDossier.raison_sociale}</strong> — une entreprise de même nom
                resynchronise ce dossier, un nom différent crée un nouveau dossier.</>
            : <>Aucun dossier actif — un chargement en créera un nouveau.</>}
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
            {/* Opt-in explicite : on ne conserve pas le mot de passe de la
                comptabilite d'un client sans qu'il l'ait demande. Chiffre en
                base (Fernet), jamais renvoye par aucune route. */}
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 14, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={form.memoriser}
                onChange={(e) => setForm((f) => ({ ...f, memoriser: e.target.checked }))}
                style={{ marginTop: 2 }}
              />
              <span style={{ fontSize: 12.5, color: 'var(--ardoise)', lineHeight: 1.5 }}>
                Mémoriser les identifiants.
              </span>
            </label>
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
            <span className="badge neutral">{scenario.dossierName}</span>
          </div>
          <div className="card-body">
            <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
              {Object.entries(DEMO_SCENARIOS).map(([key, s]) => (
                <button
                  key={key}
                  type="button"
                  className={`btn btn-sm ${demoScenario === key ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setDemoScenario(key)}
                >
                  {s.badge}
                </button>
              ))}
            </div>
            <p style={{ fontSize: 13, color: 'var(--ardoise)', lineHeight: 1.6, marginBottom: 16 }}>
              {scenario.description}
            </p>
            <ul className="feature-list">
              {scenario.features.map((f) => (
                <li key={f}><CheckCircle2 size={13} /> {f}</li>
              ))}
            </ul>
            <button className="btn btn-secondary" onClick={handleDemo} disabled={demoLoading}>
              {demoLoading ? <span className="spinner dark" /> : <Zap size={13} />}
              Charger les données de démonstration
            </button>
          </div>
        </div>
      </div>

      {/* Troisième source, en pleine largeur sous la grille à 2 colonnes :
          un import de fichier ne se compare pas à une connexion ERP, il la
          remplace pour les cabinets qui n'en ont pas. */}
      <ImportFichierCard
        dossierId={activeDossier?.id}
        dossierNom={activeDossier?.raison_sociale}
        onImported={onConnected}
      />

      {/* Quatrième source, mais pas vraiment une source : elle n'alimente
          rien automatiquement (voir OcrExtractionCard.jsx). Sous l'import de
          fichier plutôt qu'à côté, pour ne pas laisser croire que c'est une
          alternative de même niveau. */}
      <OcrExtractionCard dossierId={activeDossier?.id} />

      {error && (
        <div className="alert critique" style={{ marginTop: 16 }}>
          <div className="alert-dot" />
          <div><strong>Erreur de connexion</strong> — {error}</div>
        </div>
      )}
      {renameWarning && (
        <div className="alert vigilance" style={{ marginTop: 16 }}>
          <div className="alert-dot" />
          <div>{renameWarning}</div>
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
      {/* La synchro peut réussir SANS que les identifiants soient mémorisés
          (case décochée, ou NISAB_SECRET_KEY absente côté serveur : le backend
          n'échoue pas pour autant, cf. odoo_connect). Sans ce retour, l'échec
          de mémorisation était invisible et ne se manifestait que bien plus
          tard, au moment de pousser un brouillon — là où c'est le plus coûteux. */}
      {result && result.identifiants_memorises === false && (
        <div className="alert vigilance" style={{ marginTop: 16 }}>
          <div className="alert-dot" />
          <div>
            Identifiants Odoo <strong>non mémorisés</strong> — la synchronisation a bien eu lieu,
            mais vous ne pourrez pas pousser de brouillon de correction depuis ce dossier.
            Reconnectez-vous en cochant « Mémoriser les identifiants ».
          </div>
        </div>
      )}
      {result && result.identifiants_memorises === true && (
        <div className="alert conforme" style={{ marginTop: 16 }}>
          <div className="alert-dot" />
          <div>Identifiants mémorisés (chiffrés) — le push de brouillon Odoo est disponible sur ce dossier.</div>
        </div>
      )}
    </div>
  )
}
