const SOCIETY_TYPES = {
  UMP: {
    sigla: 'UMP',
    nome: 'União de Mocidade Presbiteriana',
    membro: 'Sócio',
    membros: 'Sócios',
    presidente: 'Presidente',
    tesoureiro: 'Tesoureiro(a)',
    secretario: 'Secretário(a)',
    conselheiro: 'Conselheiro(a)',
    sociedade: 'Sociedade',
  },
  UPH: {
    sigla: 'UPH',
    nome: 'União Presbiteriana de Homens',
    membro: 'Membro',
    membros: 'Membros',
    presidente: 'Presidente',
    tesoureiro: 'Tesoureiro',
    secretario: 'Secretário',
    conselheiro: 'Conselheiro',
    sociedade: 'Sociedade',
  },
  SAF: {
    sigla: 'SAF',
    nome: 'Sociedade Auxiliadora Feminina',
    membro: 'Associada',
    membros: 'Associadas',
    presidente: 'Presidente',
    tesoureiro: 'Tesoureira',
    secretario: 'Secretária',
    conselheiro: 'Conselheira',
    sociedade: 'Sociedade',
  },
  UPA: {
    sigla: 'UPA',
    nome: 'União Presbiteriana de Adolescentes',
    membro: 'Participante',
    membros: 'Participantes',
    presidente: 'Presidente',
    tesoureiro: 'Tesoureiro(a)',
    secretario: 'Secretário(a)',
    conselheiro: 'Conselheiro(a)',
    sociedade: 'Sociedade',
  },
}

export function getSocietyType() {
  return localStorage.getItem('society_type') || 'UMP'
}

export function setSocietyType(type) {
  localStorage.setItem('society_type', type)
}

export function getSocietyInfo() {
  return SOCIETY_TYPES[getSocietyType()] || SOCIETY_TYPES['UMP']
}

export function getSocietyLabel(key) {
  return getSocietyInfo()[key] || key
}

export function nameToColor(name) {
  if (!name) return '#64748b'
  const colors = [
    '#1a2a6c', '#1a5c2a', '#7b1fa2', '#b71c1c',
    '#e65100', '#004d40', '#0277bd', '#558b2f',
    '#6a1b9a', '#c62828', '#2e7d32', '#1565c0',
    '#4527a0', '#00695c', '#f57f17', '#37474f',
  ]
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

export function avatarHtml(name, size = 40, fontSize = '1rem') {
  const initials = (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(n => n[0].toUpperCase())
    .join('')
  const bg = nameToColor(name)
  return `
    <div style="
      width:${size}px;height:${size}px;
      border-radius:50%;
      background:${bg};
      color:#fff;
      display:flex;align-items:center;justify-content:center;
      font-size:${fontSize};
      font-weight:700;
      flex-shrink:0;
      user-select:none;
      letter-spacing:-.5px;
    ">${initials}</div>`
}

export function formatCurrency(value) {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency', currency: 'BRL'
  }).format(value ?? 0)
}

export function formatDate(dateStr) {
  if (!dateStr) return '—'
  const [y, m, d] = dateStr.split('-')
  return `${d}/${m}/${y}`
}

export function formatDateTime(isoStr) {
  if (!isoStr) return '—'
  const d = new Date(isoStr)
  return d.toLocaleString('pt-BR')
}

export function currentYear() {
  return new Date().getFullYear()
}

export function el(id) {
  return document.getElementById(id)
}

export function qs(selector, parent = document) {
  return parent.querySelector(selector)
}

export function qsa(selector, parent = document) {
  return [...parent.querySelectorAll(selector)]
}

export function show(el)  { el?.classList.remove('hidden') }
export function hide(el)  { el?.classList.add('hidden') }
export function toggle(el){ el?.classList.toggle('hidden') }

export function showAlert(containerId, message, type = 'error') {
  const container = el(containerId)
  if (!container) return
  container.innerHTML = `<div class="alert alert-${type}">${message}</div>`
  show(container)
  if (type === 'success') setTimeout(() => hide(container), 3500)
}

export function clearAlert(containerId) {
  const container = el(containerId)
  if (!container) return
  container.innerHTML = ''
  hide(container)
}

export function openModal(id) {
  el(id)?.classList.add('open')
}

export function closeModal(id) {
  el(id)?.classList.remove('open')
}

export function setLoading(btnEl, loading, text = 'Salvar') {
  if (!btnEl) return
  btnEl.disabled = loading
  btnEl.innerHTML = loading
    ? `<span class="spinner spinner-sm"></span> Aguarde...`
    : text
}

export function initModalClose() {
  document.addEventListener('click', (e) => {
    // Fecha ao clicar no overlay
    if (e.target.classList.contains('modal-overlay')) {
      e.target.classList.remove('open')
    }
    // Fecha ao clicar em botão .modal-close
    if (e.target.classList.contains('modal-close') ||
        e.target.closest('.modal-close')) {
      const overlay = e.target.closest('.modal-overlay')
      if (overlay) overlay.classList.remove('open')
    }
  })
}

window.openModal = openModal
window.closeModal = closeModal
window.avatarHtml = avatarHtml
window.nameToColor = nameToColor