import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import {
  API_URL,
  apiFetch,
  getStoredRefreshToken,
  onAuthFailure,
  setAccessToken,
  setStoredRefreshToken,
} from '../config/api'

const AuthContext = createContext(null)

// Portage direct de frontend/src/context/AuthContext.jsx — même flux
// (login/refresh/me), seule la persistance change (SecureStore, async).
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('loading') // 'loading' | 'authenticated' | 'anonymous'

  const applyTokens = useCallback(async (accessToken, refreshToken) => {
    setAccessToken(accessToken)
    if (refreshToken) await setStoredRefreshToken(refreshToken)
  }, [])

  const fetchMe = useCallback(async () => {
    const res = await apiFetch('/auth/me')
    if (!res.ok) throw new Error('me_failed')
    return res.json()
  }, [])

  const tryRefresh = useCallback(async () => {
    const refresh_token = await getStoredRefreshToken()
    if (!refresh_token) return false
    const res = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token }),
    })
    if (!res.ok) return false
    const data = await res.json()
    await applyTokens(data.access_token, data.refresh_token)
    return true
  }, [applyTokens])

  // Restauration de session au lancement de l'app (équivalent du F5 web).
  useEffect(() => {
    (async () => {
      const refreshed = await tryRefresh()
      if (!refreshed) {
        setStatus('anonymous')
        return
      }
      try {
        const me = await fetchMe()
        setUser(me)
        setStatus('authenticated')
      } catch {
        setStatus('anonymous')
      }
    })()
  }, [tryRefresh, fetchMe])

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const detail = (await res.json().catch(() => null))?.detail
      throw new Error(detail || 'Échec de connexion')
    }
    const data = await res.json()
    await applyTokens(data.access_token, data.refresh_token)
    const me = await fetchMe()
    // Espace dirigeant en lecture seule uniquement (cf. plan Lot 4) : ce
    // client mobile n'a pas d'équivalent des vues cabinet/admin. Un
    // collaborateur/admin qui se connecte ici verrait un shell vide plus
    // bas — mieux vaut le dire tout de suite plutôt que d'improviser une
    // vue non prévue.
    if (me.role !== 'dirigeant_pme') {
      setAccessToken(null)
      await setStoredRefreshToken(null)
      throw new Error(
        "Cette application est réservée aux dirigeants. Utilisez l'interface web pour un compte cabinet/admin."
      )
    }
    setUser(me)
    setStatus('authenticated')
  }, [applyTokens, fetchMe])

  const logout = useCallback(async () => {
    setAccessToken(null)
    await setStoredRefreshToken(null)
    setUser(null)
    setStatus('anonymous')
  }, [])

  useEffect(() => {
    onAuthFailure(logout)
  }, [logout])

  return (
    <AuthContext.Provider value={{ user, status, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth doit être utilisé sous <AuthProvider>')
  return ctx
}
