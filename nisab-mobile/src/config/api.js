import * as SecureStore from 'expo-secure-store'

// Équivalent mobile de frontend/src/config/api.js — même contrat
// (access token en mémoire, refresh token persistant, apiFetch qui
// rafraîchit silencieusement sur 401), adapté à deux différences runtime :
//   - pas de localStorage sur React Native → expo-secure-store (Keychain
//     iOS / Keystore Android), donc les opérations sont asynchrones ;
//   - pas de VITE_API_URL/import.meta.env → EXPO_PUBLIC_API_URL (SDK 49+
//     inline les variables préfixées EXPO_PUBLIC_ au build, même mécanique
//     que Vite pour VITE_*).
//
// Prérequis réseau (cf. plan Lot 4) : le téléphone et le backend doivent
// être joignables sur le même Wi-Fi tant que le backend n'est pas déployé
// (Lot 1.3) — localhost ne veut rien dire depuis un téléphone physique.
// Renseigner EXPO_PUBLIC_API_URL dans nisab-mobile/.env avec l'IP locale
// de la machine qui fait tourner uvicorn (`ipconfig` / `ifconfig`).
export const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000'

const REFRESH_KEY = 'nisab_refresh_token'

let _accessToken = null
let _refreshPromise = null
let _onAuthFailure = null

export function setAccessToken(token) {
  _accessToken = token
}

export function getAccessToken() {
  return _accessToken
}

export async function getStoredRefreshToken() {
  return SecureStore.getItemAsync(REFRESH_KEY)
}

export async function setStoredRefreshToken(token) {
  if (token) return SecureStore.setItemAsync(REFRESH_KEY, token)
  return SecureStore.deleteItemAsync(REFRESH_KEY)
}

/** Même rôle que côté web : AuthContext s'abonne pour se déconnecter
 * proprement quand le refresh_token lui-même est expiré/invalide. */
export function onAuthFailure(cb) {
  _onAuthFailure = cb
}

async function refreshAccessToken() {
  if (_refreshPromise) return _refreshPromise
  _refreshPromise = (async () => {
    const refresh_token = await getStoredRefreshToken()
    if (!refresh_token) return false
    try {
      const res = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token }),
      })
      if (!res.ok) return false
      const data = await res.json()
      _accessToken = data.access_token
      await setStoredRefreshToken(data.refresh_token)
      return true
    } catch {
      return false
    }
  })()
  try {
    return await _refreshPromise
  } finally {
    _refreshPromise = null
  }
}

/** Wrapper fetch — même contrat que apiFetch côté web (401 → refresh
 * silencieux → rejoue une fois → onAuthFailure si le refresh échoue aussi). */
export async function apiFetch(path, options = {}) {
  const doFetch = () => {
    const headers = { ...(options.headers || {}) }
    if (_accessToken) headers['Authorization'] = `Bearer ${_accessToken}`
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json'
    return fetch(`${API_URL}${path}`, { ...options, headers })
  }

  let res = await doFetch()

  if (res.status === 401) {
    const refreshed = await refreshAccessToken()
    if (refreshed) res = await doFetch()
    if (res.status === 401) {
      _onAuthFailure?.()
      const err = new Error('unauthorized')
      err.status = 401
      throw err
    }
  }

  return res
}
