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
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.remove('open')
    })
  })
  document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.closest('.modal-overlay')?.classList.remove('open')
    })
  })
}