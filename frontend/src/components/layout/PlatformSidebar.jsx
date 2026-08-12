import { LayoutGrid, Building2, Users, Database } from 'lucide-react'

export const PLATFORM_NAV = [
  { id: 'overview', label: "Vue d'ensemble", Icon: LayoutGrid },
  { id: 'organisations', label: 'Organisations', Icon: Building2 },
  { id: 'users', label: 'Utilisateurs', Icon: Users },
  { id: 'corpus', label: 'Corpus & Veille', Icon: Database },
]

export default function PlatformSidebar({ view, onChangeView, backendStatus }) {
  return (
    <aside className="platform-admin-sidebar sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">N</div>
        <div className="brand-text">
          <div className="brand-name">Nisab</div>
          <div className="brand-sub">Administration plateforme</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {PLATFORM_NAV.map(({ id, label, Icon }) => (
          <div
            key={id}
            className={`nav-item${view === id ? ' active' : ''}`}
            onClick={() => onChangeView(id)}
          >
            <Icon size={15} />
            {label}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sync-status">
          <span className={`sync-dot${backendStatus === 'offline' ? ' offline' : backendStatus === 'loading' ? ' loading' : ''}`} />
          {backendStatus === 'ok' ? 'API connectée' : backendStatus === 'loading' ? 'Connexion…' : 'API hors ligne'}
        </div>
      </div>
    </aside>
  )
}
