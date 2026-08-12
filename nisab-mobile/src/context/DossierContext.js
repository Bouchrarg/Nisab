import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { apiFetch } from '../config/api'
import { useAuth } from './AuthContext'

const DossierContext = createContext(null)

// Version lue-seule de frontend/src/context/DossierContext.jsx : pas de
// createDossier/renameDossier (le dirigeant ne peut pas créer de dossier,
// cf. DirigeantShell.jsx côté web, même contrainte ici). GET /dossiers est
// déjà scopé par RLS + Acces au(x) dossier(s) rattaché(s) à ce dirigeant.
export function DossierProvider({ children }) {
  const { status } = useAuth()
  const [dossiers, setDossiers] = useState([])
  const [activeDossier, setActiveDossierState] = useState(null)
  const [loading, setLoading] = useState(true)

  const refreshDossiers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/dossiers')
      if (!res.ok) throw new Error('list_failed')
      const data = await res.json()
      setDossiers(data)
      setActiveDossierState((prev) => {
        const stillThere = prev && data.find((d) => d.id === prev.id)
        return stillThere || data[0] || null
      })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (status === 'authenticated') {
      refreshDossiers()
    } else {
      setDossiers([])
      setActiveDossierState(null)
      setLoading(false)
    }
  }, [status, refreshDossiers])

  return (
    <DossierContext.Provider
      value={{ dossiers, activeDossier, setActiveDossier: setActiveDossierState, loading, refreshDossiers }}
    >
      {children}
    </DossierContext.Provider>
  )
}

export function useDossier() {
  const ctx = useContext(DossierContext)
  if (!ctx) throw new Error('useDossier doit être utilisé sous <DossierProvider>')
  return ctx
}
