import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { API_URL, apiFetch, onAuthFailure, setAccessToken } from '../config/api'

const AuthContext = createContext(null)

// Le refresh_token est stocké en localStorage : c'est un compromis - un cookie httpOnly émis par
// le back-end serait plus sûr mais demande de servir front et back sur le
// même domaine/sous-domaine. À revisiter en Phase 7 (sécurité).
const REFRESH_KEY = 'nisab_refresh_token'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('loading') // 'loading' | 'authenticated' | 'anonymous'

  const applyTokens = useCallback((accessToken, refreshToken) => {
    setAccessToken(accessToken)
    if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken)
  }, [])

  const fetchMe = useCallback(async () => {
    const res = await apiFetch('/auth/me')
    if (!res.ok) throw new Error('me_failed')
    return res.json()
  }, [])

  const tryRefresh = useCallback(async () => {
    const refresh_token = localStorage.getItem(REFRESH_KEY)
    if (!refresh_token) return false
    const res = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token }),
    })
    if (!res.ok) return false
    const data = await res.json()
    applyTokens(data.access_token, data.refresh_token)
    return true
  }, [applyTokens])

  // Restauration de session au chargement de l'app (F5, retour sur l'onglet...)
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
    applyTokens(data.access_token, data.refresh_token)
    const me = await fetchMe()
    setUser(me)
    setStatus('authenticated')
  }, [applyTokens, fetchMe])

  const register = useCallback(async (payload) => {
    const res = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const detail = (await res.json().catch(() => null))?.detail
      throw new Error(detail || "Échec de l'inscription")
    }
    const data = await res.json()
    applyTokens(data.access_token, data.refresh_token)
    const me = await fetchMe()
    setUser(me)
    setStatus('authenticated')
  }, [applyTokens, fetchMe])

  const logout = useCallback(() => {
    setAccessToken(null)
    localStorage.removeItem(REFRESH_KEY)
    setUser(null)
    setStatus('anonymous')
  }, [])

  const refreshUser = useCallback(async () => {
    const me = await fetchMe()
    setUser(me)
    return me
  }, [fetchMe])

  // api.js ne peut pas appeler logout() lui-même (pas de React) : il
  // prévient via ce callback quand le refresh_token est lui aussi
  // invalide/expiré, pour qu'on nettoie proprement l'état côté React.
  useEffect(() => {
    onAuthFailure(logout)
  }, [logout])

  return (
    <AuthContext.Provider value={{ user, status, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth doit être utilisé sous <AuthProvider>')
  return ctx
}
