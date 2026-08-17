import { useState } from 'react'
import { Bell, LogOut, UserCircle } from 'lucide-react'
import { VIEW_TITLES } from '../../constants/navigation'
import DossierSwitcher from './DossierSwitcher'
import { useAuth } from '../../context/AuthContext'

// `criticalAlerts` est calculée par CabinetOverviewPage (seule à charger le
// résumé de chaque dossier) et remontée via App.jsx — la cloche vit ici,
// dans le header persistant, pas dans le contenu d'une page en particulier.
// Reste vide (donc silencieuse) tant que la vue d'ensemble n'a pas encore
// chargé au moins une fois dans la session.
export default function Topbar({ view, onOpenProfile, criticalAlerts = [], onOpenDossier }) {
  const { user, logout } = useAuth()
  const [notifOpen, setNotifOpen] = useState(false)

  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="topbar-title">{VIEW_TITLES[view]}</span>
        <DossierSwitcher />
      </div>
      <div className="topbar-actions">
        <div style={{ position: 'relative' }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setNotifOpen((v) => !v)}
            style={{ position: 'relative', padding: '6px 10px' }}
            title="Alertes fiscales"
          >
            <Bell size={14} />
            {criticalAlerts.length > 0 && (
              <span className="notif-badge">{criticalAlerts.length}</span>
            )}
          </button>
          {notifOpen && (
            <div className="notif-panel">
              <div className="notif-panel-header">
                <span className="notif-panel-title">Alertes critiques</span>
                <button
                  onClick={() => setNotifOpen(false)}
                  style={{
                    width: 20, height: 20, border: 'none', background: 'transparent',
                    color: 'var(--sourdine)', cursor: 'pointer', fontSize: 12,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  ✕
                </button>
              </div>
              {criticalAlerts.length === 0 ? (
                <div style={{ padding: '16px 14px', fontSize: 12, color: 'var(--sourdine)', textAlign: 'center' }}>
                  Aucune alerte critique active
                </div>
              ) : (
                criticalAlerts.map(({ dossier, s }) => (
                  <div
                    key={dossier.id}
                    className="notif-item"
                    onClick={() => {
                      setNotifOpen(false)
                      onOpenDossier?.(dossier)
                    }}
                  >
                    <div className="notif-item-dot critique" />
                    <div>
                      <div className="notif-item-title">{dossier.raison_sociale}</div>
                      <div className="notif-item-sub">
                        {s.top_urgency?.title || `${s.risks.rouge} anomalie(s) critique(s)`}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        {user && (
          <button className="btn btn-secondary btn-sm" onClick={onOpenProfile} title="Mon profil">
            <UserCircle size={13} />
            {user.nom_complet || user.email}
          </button>
        )}
        <button className="btn btn-secondary btn-sm" onClick={logout} title="Se déconnecter">
          <LogOut size={13} />
        </button>
      </div>
    </header>
  )
}
