import { useState } from 'react'
import { useDossier } from '../../context/DossierContext'

/** Sélecteur de dossier actif + création rapide — placé dans Topbar.jsx. */
export default function DossierSwitcher() {
  const { dossiers, activeDossier, setActiveDossier, createDossier } = useDossier()
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

  if (creating) {
    return (
      <form className="dossier-switcher-create" onSubmit={handleCreate}>
        <input
          autoFocus
          placeholder="Raison sociale du nouveau dossier"
          value={raisonSociale}
          onChange={(e) => setRaisonSociale(e.target.value)}
        />
        <button type="submit">Créer</button>
        <button type="button" onClick={() => setCreating(false)}>Annuler</button>
      </form>
    )
  }

  return (
    <div className="dossier-switcher">
      <select value={activeDossier?.id || ''} onChange={handleSelect}>
        {dossiers.length === 0 && <option value="">Aucun dossier</option>}
        {dossiers.map((d) => (
          <option key={d.id} value={d.id}>{d.raison_sociale}</option>
        ))}
      </select>
      <button type="button" onClick={() => setCreating(true)} title="Nouveau dossier">+ Dossier</button>
    </div>
  )
}
