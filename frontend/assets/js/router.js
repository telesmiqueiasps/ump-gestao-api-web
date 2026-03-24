import { getUser, isFederation, isLocalUmp, logout } from './auth.js'

const ROLE_LABELS = {
  presidente:              'Presidente',
  vice_presidente:         'Vice-Presidente',
  '1_secretario':          '1º Secretário',
  '2_secretario':          '2º Secretário',
  tesoureiro:              'Tesoureiro',
  secretario_executivo:    'Secretário Executivo',
  secretario_presbiterial: 'Secretário Presbiterial',
  conselheiro:             'Conselheiro',
}

const ORG_LABELS = {
  federation: 'Federação',
  local_ump:  'UMP Local',
}

const NAV_ITEMS = [
  { page: 'dashboard',  label: 'Dashboard',  icon: '⊞', path: '/pages/dashboard.html',  always: true },
  { page: 'profile',    label: 'Perfil',      icon: '◎', path: '/pages/profile.html',    always: true },
  { page: 'finances',   label: 'Financeiro',  icon: '◈', path: '/pages/finances.html',   always: true },
  { page: 'members',    label: 'Sócios',      icon: '◉', path: '/pages/members.html',    localOnly: true },
  { page: 'board',      label: 'Diretoria',   icon: '❖', path: '/pages/board.html',      always: true },
  { page: 'local-umps', label: 'UMPs Locais', icon: '⊟', path: '/pages/local-umps.html', fedOnly: true },
]

// Expõe navigate globalmente para os onclick do HTML
window.navigate = function(page) {
  const item = NAV_ITEMS.find(n => n.page === page)
  if (item) window.location.href = item.path
}

export function renderShell() {
  const user = getUser()
  if (!user) return

  const roleLabel = user.roles?.length
    ? (ROLE_LABELS[user.roles[0]] || user.roles[0])
    : ''

  const navHTML = NAV_ITEMS
    .filter(item => {
      if (item.always) return true
      if (item.fedOnly && isFederation()) return true
      if (item.localOnly && isLocalUmp()) return true
      return false
    })
    .map(item => `
      <button class="nav-item" data-page="${item.page}" onclick="navigate('${item.page}')">
        <span class="nav-icon">${item.icon}</span>
        ${item.label}
      </button>
    `).join('')

  document.getElementById('sidebar-nav').innerHTML = navHTML
  document.getElementById('header-name').textContent = user.full_name
  document.getElementById('header-role').textContent =
    `${ORG_LABELS[user.organization_type] || ''}${roleLabel ? ' · ' + roleLabel : ''}`
  document.getElementById('header-avatar').textContent =
    user.full_name?.charAt(0).toUpperCase() || '?'

  document.getElementById('btn-logout').addEventListener('click', logout)
}

export function setActivePage(page) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page)
  })
}