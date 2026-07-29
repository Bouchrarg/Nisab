import { NAV } from '../../constants/navigation'

export default function Sidebar({ view, onChangeView, backendStatus }) {
  let lastSection = null

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">N</div>
        <div className="brand-text">
          <div className="brand-name">Nisab</div>
          <div className="brand-sub">Copilote fiscal IA</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV.map(({ id, label, Icon, section }) => {
          const showSection = section && section !== lastSection
          if (section) lastSection = section
          return (
            <div key={id}>
              {showSection && <div className="nav-section">{section}</div>}
              <div
                className={`nav-item${view === id ? ' active' : ''}`}
                onClick={() => onChangeView(id)}
              >
                <Icon size={15} />
                {label}
              </div>
            </div>
          )
        })}
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
