import { RefreshCw } from 'lucide-react'
import { VIEW_TITLES } from '../../constants/navigation'

export default function Topbar({ view, hasData, auditLoading, onRunAudit }) {
  return (
    <header className="topbar">
      <span className="topbar-title">{VIEW_TITLES[view]}</span>
      <div className="topbar-actions">
        {hasData && view !== 'odoo' && view !== 'chat' && view !== 'calendar' && (
          <button className="btn btn-secondary btn-sm" onClick={onRunAudit} disabled={auditLoading}>
            {auditLoading ? <span className="spinner dark" /> : <RefreshCw size={13} />}
            Actualiser
          </button>
        )}
      </div>
    </header>
  )
}
