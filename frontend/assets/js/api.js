const BASE_URL = 'https://ump-gestao-api.onrender.com'
// Em desenvolvimento use: const BASE_URL = 'http://localhost:8000'

async function request(method, path, body = null, isFormData = false) {
  const token = localStorage.getItem('access_token')

  const headers = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (!isFormData) headers['Content-Type'] = 'application/json'

  const controller = new AbortController()
  const timeoutId  = setTimeout(() => controller.abort(), 30000)

  const options = { method, headers, signal: controller.signal }
  if (body) options.body = isFormData ? body : JSON.stringify(body)

  let res
  try {
    res = await fetch(BASE_URL + path, options)
  } catch (err) {
    clearTimeout(timeoutId)
    if (err.name === 'AbortError') throw new Error('Servidor demorando para responder. Aguarde...')
    throw err
  }
  clearTimeout(timeoutId)

  // Tenta refresh automático se 401
  if (res.status === 401 && !path.includes('/auth/')) {
    const refreshed = await tryRefresh()
    if (refreshed) {
      headers['Authorization'] = `Bearer ${localStorage.getItem('access_token')}`
      options.headers = headers
      res = await fetch(BASE_URL + path, options)
    } else {
      logout()
      return
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Erro desconhecido' }))
    throw new Error(err.detail || `Erro ${res.status}`)
  }

  if (res.status === 204) return null
  return res.json()
}

async function tryRefresh() {
  const refresh_token = localStorage.getItem('refresh_token')
  if (!refresh_token) return false
  try {
    const res = await fetch(BASE_URL + '/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token })
    })
    if (!res.ok) return false
    const data = await res.json()
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    return true
  } catch { return false }
}

function logout() {
  localStorage.clear()
  window.location.href = '/index.html'
}

export const api = {
  get:    (path)              => request('GET',    path),
  post:   (path, body)        => request('POST',   path, body),
  put:    (path, body)        => request('PUT',    path, body),
  delete: (path)              => request('DELETE', path),
  upload: (path, formData)    => request('POST',   path, formData, true),
}