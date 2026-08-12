import { LogOut, UserCircle } from 'lucide-react'
import { VIEW_TITLES } from '../../constants/navigation'
import DossierSwitcher from './DossierSwitcher'
import { useAuth } from '../../context/AuthContext'

export default function Topbar({ view, onOpenProfile }) {
  const { user, logout } = useAuth()

  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="topbar-title">{VIEW_TITLES[view]}</span>
        <DossierSwitcher />
      </div>
      <div className="topbar-actions">
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
