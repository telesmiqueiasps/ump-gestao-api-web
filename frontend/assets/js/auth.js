import { api } from './api.js'

export function getUser() {
  const raw = localStorage.getItem('user')
  return raw ? JSON.parse(raw) : null
}

export function isLoggedIn() {
  return !!localStorage.getItem('access_token')
}

export function isFederation() {
  return getUser()?.organization_type === 'federation'
}

export function isLocalUmp() {
  return getUser()?.organization_type === 'local_ump'
}

export function hasRole(...roles) {
  const user = getUser()
  return roles.some(r => user?.roles?.includes(r))
}

export async function login(email, password) {
  const data = await api.post('/api/auth/login', { email, password })
  localStorage.setItem('access_token', data.access_token)
  localStorage.setItem('refresh_token', data.refresh_token)
  localStorage.setItem('user', JSON.stringify({
    id: data.user_id,
    full_name: data.full_name,
    organization_id: data.organization_id,
    organization_type: data.organization_type,
    roles: data.roles,
  }))

  // Busca e salva o tipo de sociedade
  try {
    const orgEndpoint = data.organization_type === 'federation'
      ? '/api/federations/me'
      : '/api/local-umps/me'
    const orgData = await api.get(orgEndpoint)
    if (orgData.society_type) {
      localStorage.setItem('society_type', orgData.society_type)
    }
  } catch {}

  return data
}

export function logout() {
  localStorage.clear()
  window.location.href = '/index.html'
}

export function requireAuth() {
  if (!isLoggedIn()) {
    window.location.href = '/index.html'
    return false
  }
  return true
}