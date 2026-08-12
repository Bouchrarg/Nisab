import { useEffect, useState } from 'react'
import { LogOut } from 'lucide-react'
import PlatformSidebar from '../components/layout/PlatformSidebar'
import AdminPage from './AdminPage'
import PlatformOverviewPage from './platform/PlatformOverviewPage'
import OrganisationsPage from './platform/OrganisationsPage'
import UsersPage from './platform/UsersPage'
import { useAuth } from '../context/AuthContext'
import { API_URL } from '../config/api'

const VIEW_TITLES = {
  overview: "Vue d'ensemble de la plateforme",
  organisations: 'Organisations',
  users: 'Utilisateurs',
  corpus: 'Administration du corpus',
}

// Espace séparé du shell "cabinet" : réservé aux comptes admin_plateforme
// (équipe Nisab/IAAI). Multi-pages : vue d'ensemble globale, organisations,
// utilisateurs (tous tenants confondus), et corpus fiscal / veille
// réglementaire .
export default function PlatformAdminShell() {
  const { user, logout } = useAuth()
  const [view, setView] = useState(() => localStorage.getItem('nisab_platform_view') || 'overview')
  const [backendStatus, setBackendStatus] = useState('loading')

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(() => setBackendStatus('ok'))
      .catch(() => setBackendStatus('offline'))
  }, [])

  const changeView = (v) => {
    setView(v)
    localStorage.setItem('nisab_platform_view', v)
  }

  return (
    <div className="platform-admin-shell">
      <PlatformSidebar view={view} onChangeView={changeView} backendStatus={backendStatus} />

      <div className="platform-admin-main">
        <header className="platform-admin-header">
          <h1>{VIEW_TITLES[view] || 'Nisab — Administration plateforme'}</h1>
          <button className="btn btn-secondary btn-sm" onClick={logout} title={user?.email}>
            <LogOut size={13} />
            {user?.nom_complet || user?.email}
          </button>
        </header>

        <div className="platform-admin-body">
          <div className="platform-admin-body-inner">
            {view === 'overview' && <PlatformOverviewPage onNavigate={changeView} />}
            {view === 'organisations' && <OrganisationsPage />}
            {view === 'users' && <UsersPage />}
            {view === 'corpus' && <AdminPage />}
          </div>
        </div>
      </div>
    </div>
  )
}
