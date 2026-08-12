import { useState } from 'react'
import { Building2, Plus, ChevronDown } from 'lucide-react'
import { useDossier } from '../../context/DossierContext'
import { useAuth } from '../../context/AuthContext'

export default function DossierSwitcher() {
  const { dossiers, activeDossier, setActiveDossier, createDossier } = useDossier()
  const { user } = useAuth()
  // Créer un dossier = ajouter un nouveau client au cabinet, décision
  // réservée à admin_cabinet (voir require_role sur POST /dossiers).
  const canCreate = user?.role === 'admin_cabinet'
  const [creating, setCreating] = useState(false)
  const [raisonSociale, setRaisonSociale] = useState('')

  const handleSelect = (e) => {
    const dossier = dossiers.find((d) => d.id === e.target.value)
    if (dossier) setActiveDossier(dossier)
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!raisonSociale.trim()) return
    await createDossier({ raison_sociale: raisonSociale.trim() })
    setRaisonSociale('')
    setCreating(false)
  }

  if (creating && canCreate) {
    return (
      <form className="dossier-switcher-create" onSubmit={handleCreate}>
        <input
          autoFocus
          placeholder="Raison sociale du nouveau dossier"
          value={raisonSociale}
          onChange={(e) => setRaisonSociale(e.target.value)}
        />
        <button type="submit" className="btn btn-primary btn-sm">Créer</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setCreating(false)}>Annuler</button>
      </form>
    )
  }

  return (
    <div className="dossier-switcher">
      <Building2 size={14} className="dossier-switcher-icon" />
      <div className="dossier-switcher-select-wrap">
        <select value={activeDossier?.id || ''} onChange={handleSelect}>
          {dossiers.length === 0 && <option value="">Aucun dossier</option>}
          {dossiers.map((d) => (
            <option key={d.id} value={d.id}>{d.raison_sociale}</option>
          ))}
        </select>
        <ChevronDown size={12} className="dossier-switcher-chevron" />
      </div>
      {canCreate && (
        <button type="button" className="dossier-switcher-add" onClick={() => setCreating(true)} title="Nouveau dossier">
          <Plus size={13} />
        </button>
      )}
    </div>
  )
}