export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ── Phase 2/3 : store de session partagé (token + dossier actif) ─────────
// Simple module-level store plutôt qu'un contexte React pur : plusieurs
// fichiers (GlobalCopilot.jsx, les pages) font des fetch() directs en
// dehors du rendu, il faut donc une source unique lisible partout sans
// prop-drilling. AuthContext/DossierContext sont les seuls à écrire ici ;
// tout le reste ne fait que lire via apiFetch().

let _accessToken = null
let _activeDossierId = null
let _refreshPromise = null
let _onAuthFailure = null

// Même clé que AuthContext.jsx (REFRESH_KEY) — dupliquée volontairement
// plutôt que de créer un module partagé pour une seule constante : api.js
// doit pouvoir rafraîchir le token sans dépendre de React/AuthContext.
const REFRESH_KEY = 'nisab_refresh_token'

export function setAccessToken(token) {
  _accessToken = token
}

export function getAccessToken() {
  return _accessToken
}

export function setActiveDossierId(id) {
  _activeDossierId = id
}

export function getActiveDossierId() {
  return _activeDossierId
}

/**
 * Enregistre le callback appelé quand le refresh_token lui-même est
 * invalide/expiré (14 jours) — AuthContext s'en sert pour déclencher un
 * logout() propre. api.js ne connaît pas React/AuthContext, donc ne peut
 * pas appeler logout() directement.
 */
export function onAuthFailure(cb) {
  _onAuthFailure = cb
}

/**
 * Échange le refresh_token contre un nouveau access_token. Dédupliqué via
 * _refreshPromise : si plusieurs requêtes tombent sur un 401 en même temps
 * (ex. plusieurs dossiers chargés en parallèle sur CabinetOverviewPage),
 * une seule vraie requête /auth/refresh part, les autres attendent son résultat.
 */
async function refreshAccessToken() {
  if (_refreshPromise) return _refreshPromise
  _refreshPromise = (async () => {
    const refresh_token = localStorage.getItem(REFRESH_KEY)
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
      localStorage.setItem(REFRESH_KEY, data.refresh_token)
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

/**
 * Wrapper autour de fetch() qui :
 *  - préfixe automatiquement API_URL
 *  - ajoute le header Authorization si un token est présent
 *  - sur un 401 (access_token expiré, durée de vie 30 min), tente un
 *    rafraîchissement silencieux via refresh_token et rejoue la requête
 *    une fois — invisible pour l'appelant tant que le refresh_token
 *    (14 jours) reste valide
 *  - si le refresh échoue aussi, prévient via onAuthFailure() puis lève
 *    une erreur lisible (le composant appelant peut aussi gérer le cas
 *    localement s'il le souhaite)
 */
export async function apiFetch(path, options = {}) {
  const doFetch = () => {
    const headers = { ...(options.headers || {}) }
    if (_accessToken) {
      headers['Authorization'] = `Bearer ${_accessToken}`
    }
    if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json'
    }
    return fetch(`${API_URL}${path}`, { ...options, headers })
  }

  let res = await doFetch()

  if (res.status === 401) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      res = await doFetch()
    }
    if (res.status === 401) {
      _onAuthFailure?.()
      const err = new Error('unauthorized')
      err.status = 401
      throw err
    }
  }

  return res
}

/** Raccourci pour les endpoints /dossiers/{id}/... du dossier actif. */
export function dossierFetch(subPath, options = {}) {
  const dossierId = getActiveDossierId()
  if (!dossierId) {
    return Promise.reject(new Error('Aucun dossier actif sélectionné.'))
  }
  return apiFetch(`/dossiers/${dossierId}${subPath}`, options)
}
