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