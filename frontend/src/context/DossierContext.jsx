import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { apiFetch, setActiveDossierId, getActiveDossierId } from '../config/api'
import { useAuth } from './AuthContext'

const DossierContext = createContext(null)

const ACTIVE_DOSSIER_KEY = 'nisab_active_dossier_id'

export function DossierProvider({ children }) {
  const { status } = useAuth()
  const [dossiers, setDossiers] = useState([])
  const [activeDossier, setActiveDossierState] = useState(null)
  const [loading, setLoading] = useState(true)

  const setActiveDossier = useCallback((dossier) => {
    setActiveDossierState(dossier)
    setActiveDossierId(dossier ? dossier.id : null)
    if (dossier) localStorage.setItem(ACTIVE_DOSSIER_KEY, dossier.id)
  }, [])

  const refreshDossiers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/dossiers')
      if (!res.ok) throw new Error('list_failed')
      const data = await res.json()
      setDossiers(data)

      const savedId = localStorage.getItem(ACTIVE_DOSSIER_KEY) || getActiveDossierId()
      const match = data.find((d) => d.id === savedId)
      if (match) {
        setActiveDossier(match)
      } else if (data.length > 0) {
        setActiveDossier(data[0])
      } else {
        setActiveDossier(null)
      }
    } finally {
      setLoading(false)
    }
  }, [setActiveDossier])

  useEffect(() => {
    if (status === 'authenticated') {
      refreshDossiers()
    } else {
      setDossiers([])
      setActiveDossier(null)
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  const createDossier = useCallback(async (payload) => {
    const res = await apiFetch('/dossiers', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const detail = (await res.json().catch(() => null))?.detail
      throw new Error(detail || 'Échec de la création du dossier.')
    }
    const dossier = await res.json()
    await refreshDossiers()
    setActiveDossier(dossier)
    return dossier
  }, [refreshDossiers, setActiveDossier])

  const renameDossier = useCallback(async (dossierId, raisonSociale) => {
    const res = await apiFetch(`/dossiers/${dossierId}`, {
      method: 'PATCH',
      body: JSON.stringify({ raison_sociale: raisonSociale }),
    })
    if (!res.ok) throw new Error('rename_failed')
    const dossier = await res.json()
    await refreshDossiers()
    if (activeDossier?.id === dossierId) setActiveDossier(dossier)
    return dossier
  }, [refreshDossiers, setActiveDossier, activeDossier])

  return (
    <DossierContext.Provider
      value={{ dossiers, activeDossier, setActiveDossier, createDossier, renameDossier, refreshDossiers, loading }}
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
