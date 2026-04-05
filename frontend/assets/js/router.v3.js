import { getUser, isFederation, isLocalUmp, logout } from './auth.js'
import { getSocietyLabel } from './utils.js'

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
  {
    page: 'dashboard', label: 'Dashboard', icon: '/assets/img/dashboard.png',
    path: '/pages/dashboard.html',
    roles: null
  },
  {
    page: 'profile', label: 'Perfil', icon: '/assets/img/perfil.png',
    path: '/pages/profile.html',
    roles: null
  },
  {
    page: 'finances', label: 'Financeiro', icon: '/assets/img/financeiro.png',
    path: '/pages/finances.html',
    roles: ['presidente','vice_presidente','tesoureiro','conselheiro','secretario_presbiterial']
  },
  {
    page: 'members', label: getSocietyLabel('membros'), icon: '/assets/img/socios.png',
    path: '/pages/members.html',
    localOnly: true,
    roles: ['presidente','vice_presidente','tesoureiro','conselheiro','secretario_presbiterial']
  },
  {
    page: 'board', label: 'Diretoria', icon: '/assets/img/diretoria.png',
    path: '/pages/board.html',
    roles: ['presidente','vice_presidente','conselheiro','secretario_presbiterial']
  },
  {
    page: 'local-umps', label: 'UMPs Locais', icon: '/assets/img/umps_locais.png',
    path: '/pages/local-umps.html',
    fedOnly: true,
    roles: ['presidente','vice_presidente','conselheiro','secretario_presbiterial']
  },
  {
    page: 'secretary', label: 'Secretaria', icon: '/assets/img/secretaria.png',
    path: '/pages/secretary.html',
    roles: ['presidente','vice_presidente','1_secretario','2_secretario','secretario_executivo','conselheiro','secretario_presbiterial']
  },
  {
    page: 'president', label: 'Presidência', icon: '/assets/img/presidente.png',
    path: '/pages/president.html',
    roles: ['presidente','vice_presidente','conselheiro','secretario_presbiterial']
  },
  {
    page: 'notices', label: 'Avisos', icon: '/assets/img/aviso.png',
    path: '/pages/notices.html',
    roles: null
  },
]

// Expõe navigate globalmente para os onclick do HTML
window.navigate = function(page) {
  const item = NAV_ITEMS.find(n => n.page === page)
  if (item) window.location.href = item.path
}

export function canAccessPage(page) {
  const item = NAV_ITEMS.find(n => n.page === page)
  if (!item) return false
  if (item.fedOnly && !isFederation()) return false
  if (item.localOnly && !isLocalUmp()) return false
  if (item.roles === null) return true
  const userRoles = getUser()?.roles ?? []
  return item.roles.some(r => userRoles.includes(r))
}

const MEMBER_LABELS = { UMP: 'Sócios', UPH: 'Membros', SAF: 'Associadas', UPA: 'Participantes' }

function buildNavHTML(user, societyType) {
  societyType = societyType || localStorage.getItem('society_type') || 'UMP'
  const userRoles = user?.roles ?? []
  const memberLabel = MEMBER_LABELS[societyType] || 'Sócios'

  return NAV_ITEMS
    .filter(item => {
      if (item.fedOnly && !isFederation()) return false
      if (item.localOnly && !isLocalUmp()) return false
      if (item.roles === null) return true
      return item.roles.some(r => userRoles.includes(r))
    })
    .map(item => {
      let label = item.label
      if (item.page === 'local-umps') label = `${societyType}s Locais`
      if (item.page === 'members')    label = memberLabel
      if (item.page === 'notices') {
        return `
          <button class="nav-item" data-page="${item.page}" onclick="navigate('${item.page}')">
            <img class="nav-icon" src="${item.icon}" alt="" />
            ${label}
            <span class="nav-badge" id="notices-badge" style="display:none">0</span>
          </button>
        `
      }
      return `
        <button class="nav-item" data-page="${item.page}" onclick="navigate('${item.page}')">
          <img class="nav-icon" src="${item.icon}" alt="" />
          ${label}
        </button>
      `
    }).join('')
}

export async function renderShell() {
  const user = getUser()
  if (!user) return

  const roleLabel = user.roles?.length
    ? (ROLE_LABELS[user.roles[0]] || user.roles[0])
    : ''

  // Busca o perfil da organização ANTES de renderizar para ter o society_type correto
  let societyType = 'UMP'
  let orgName = ''
  try {
    const { api } = await import('./api.js')
    const orgType = user.organization_type
    const endpoint = orgType === 'federation' ? '/api/federations/me' : '/api/local-umps/me'
    const data = await api.get(endpoint)
    orgName = data.name || ''
    societyType = data.society_type || 'UMP'
    localStorage.setItem('society_type', societyType)
    // Atualiza o título da página
    document.title = document.title.replace(/UMP|UPH|SAF|UPA/g, societyType)
  } catch {}

  // Agora renderiza a sidebar com o societyType correto
  document.getElementById('sidebar-nav').innerHTML = buildNavHTML(user, societyType)
  document.getElementById('header-name').textContent = user.full_name
  document.getElementById('header-role').textContent =
    `${ORG_LABELS[user.organization_type] || ''}${roleLabel ? ' · ' + roleLabel : ''}`
  document.getElementById('header-avatar').textContent =
    user.full_name?.charAt(0).toUpperCase() || '?'

  const orgNameEl = document.getElementById('header-org-name')
  if (orgNameEl) orgNameEl.textContent = orgName

  document.getElementById('btn-logout')?.addEventListener('click', logout)

  // Botão de alterar senha e modal (código existente mantido)
  const sidebarFooter = document.querySelector('.sidebar-footer')
  if (sidebarFooter && !document.querySelector('.sidebar-pw-btn')) {
    const pwBtn = document.createElement('button')
    pwBtn.className = 'sidebar-pw-btn'
    pwBtn.innerHTML = '🔒 Alterar senha'
    pwBtn.addEventListener('click', () => openPasswordModal())
    sidebarFooter.parentNode.insertBefore(pwBtn, sidebarFooter)
  }

  if (!document.getElementById('modal-sidebar-pw')) {
    const modalHtml = `
      <div class="modal-overlay" id="modal-sidebar-pw">
        <div class="modal modal-sm">
          <div class="modal-header">
            <h2>Alterar Senha</h2>
            <button class="modal-close">✕</button>
          </div>
          <div class="field" style="margin-bottom:1rem">
            <label>Senha atual</label>
            <input class="input" type="password" id="sidebar-pw-current" />
          </div>
          <div class="field" style="margin-bottom:1rem">
            <label>Nova senha</label>
            <input class="input" type="password" id="sidebar-pw-new" />
          </div>
          <div class="field" style="margin-bottom:1rem">
            <label>Confirmar nova senha</label>
            <input class="input" type="password" id="sidebar-pw-confirm" />
          </div>
          <div id="sidebar-pw-alert" class="hidden" style="margin-bottom:1rem"></div>
          <div id="sidebar-pw-success" class="hidden" style="margin-bottom:1rem">
            <div class="alert alert-success">✅ Senha alterada com sucesso!</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary modal-close">Cancelar</button>
            <button class="btn btn-primary" id="sidebar-btn-save-pw">Alterar</button>
          </div>
        </div>
      </div>`
    document.body.insertAdjacentHTML('beforeend', modalHtml)

    document.getElementById('sidebar-btn-save-pw').addEventListener('click', async () => {
      const current   = document.getElementById('sidebar-pw-current').value
      const newPw     = document.getElementById('sidebar-pw-new').value
      const confirmPw = document.getElementById('sidebar-pw-confirm').value
      const alertEl   = document.getElementById('sidebar-pw-alert')
      const successEl = document.getElementById('sidebar-pw-success')

      alertEl.classList.add('hidden')
      successEl.classList.add('hidden')

      if (!current || !newPw || !confirmPw) {
        alertEl.innerHTML = '<div class="alert alert-error">Preencha todos os campos.</div>'
        alertEl.classList.remove('hidden')
        return
      }
      if (newPw !== confirmPw) {
        alertEl.innerHTML = '<div class="alert alert-error">As senhas não coincidem.</div>'
        alertEl.classList.remove('hidden')
        return
      }
      if (newPw.length < 6) {
        alertEl.innerHTML = '<div class="alert alert-error">A nova senha deve ter pelo menos 6 caracteres.</div>'
        alertEl.classList.remove('hidden')
        return
      }

      const btn = document.getElementById('sidebar-btn-save-pw')
      btn.disabled = true
      btn.textContent = 'Salvando...'

      try {
        const { api } = await import('./api.js')
        await api.post('/api/users/me/change-password', {
          current_password: current,
          new_password: newPw
        })
        document.getElementById('sidebar-pw-current').value = ''
        document.getElementById('sidebar-pw-new').value = ''
        document.getElementById('sidebar-pw-confirm').value = ''
        successEl.classList.remove('hidden')
        setTimeout(() => {
          document.getElementById('modal-sidebar-pw').classList.remove('open')
          successEl.classList.add('hidden')
        }, 2500)
      } catch(err) {
        alertEl.innerHTML = `<div class="alert alert-error">${err.message || 'Erro ao alterar senha.'}</div>`
        alertEl.classList.remove('hidden')
      } finally {
        btn.disabled = false
        btn.textContent = 'Alterar'
      }
    })

    document.getElementById('modal-sidebar-pw').addEventListener('click', (e) => {
      if (e.target === document.getElementById('modal-sidebar-pw')) {
        document.getElementById('modal-sidebar-pw').classList.remove('open')
      }
    })
    document.querySelectorAll('#modal-sidebar-pw .modal-close').forEach(btn => {
      btn.addEventListener('click', () => {
        document.getElementById('modal-sidebar-pw').classList.remove('open')
      })
    })
  }

  checkNoticesBadge()
  return societyType
}

async function checkNoticesBadge() {
  try {
    const { api } = await import('./api.js')
    const user = getUser()
    let count = 0

    if (user?.organization_type === 'local_ump') {
      try {
        const notices = await api.get('/api/notices/received')
        count += notices.length
      } catch {}

      try {
        const birthdays = await api.get('/api/members/birthdays')
        const todayBirthdays = birthdays.filter(b => b.is_today)
        count += todayBirthdays.length
      } catch {}
    }

    if (user?.organization_type === 'federation') {
      try {
        const anniversaries = await api.get('/api/local-umps/anniversaries')
        const todayAnniversaries = anniversaries.filter(a => a.is_today)
        count += todayAnniversaries.length
      } catch {}
    }

    const badge = document.getElementById('notices-badge')
    if (badge && count > 0) {
      badge.textContent = count > 9 ? '9+' : count
      badge.style.display = 'flex'
    }
  } catch {}
}

window.openPasswordModal = function() {
  document.getElementById('sidebar-pw-alert')?.classList.add('hidden')
  document.getElementById('sidebar-pw-success')?.classList.add('hidden')
  document.getElementById('sidebar-pw-current').value = ''
  document.getElementById('sidebar-pw-new').value = ''
  document.getElementById('sidebar-pw-confirm').value = ''
  document.getElementById('modal-sidebar-pw')?.classList.add('open')
}

export function setActivePage(page) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page)
  })
}

let _currentPage = ''

export function renderBottomNav(currentPage, societyType) {
  _currentPage = currentPage
  if (window.innerWidth > 768) return

  const user = getUser()
  if (!user) return

  const userRoles = user?.roles ?? []
  const bottomSocietyType = societyType || localStorage.getItem('society_type') || 'UMP'
  const bottomMemberLabel = MEMBER_LABELS[bottomSocietyType] || 'Sócios'

  const BOTTOM_ITEMS = [
    { page: 'dashboard', label: 'Início',          icon: '⊞', roles: null },
    { page: 'finances',  label: 'Financeiro',       icon: '◈', roles: ['presidente','vice_presidente','tesoureiro','conselheiro','secretario_presbiterial'] },
    { page: 'members',   label: bottomMemberLabel,  icon: '◉', localOnly: true, roles: ['presidente','vice_presidente','tesoureiro','conselheiro','secretario_presbiterial'] },
    { page: 'board',     label: 'Diretoria',        icon: '❖', roles: ['presidente','vice_presidente','conselheiro','secretario_presbiterial'] },
    { page: 'notices',   label: 'Avisos',           icon: '📢', roles: null },
  ]

  const visibleItems = BOTTOM_ITEMS.filter(item => {
    if (item.fedOnly   && !isFederation()) return false
    if (item.localOnly && !isLocalUmp())   return false
    if (item.roles === null) return true
    return item.roles.some(r => userRoles.includes(r))
  })

  let bottomNav = document.getElementById('bottom-nav')
  if (!bottomNav) {
    bottomNav = document.createElement('nav')
    bottomNav.id = 'bottom-nav'
    bottomNav.className = 'bottom-nav'
    document.body.appendChild(bottomNav)
  }

  bottomNav.innerHTML = `
    <div class="bottom-nav-items">
      ${visibleItems.map(item => `
        <button class="bottom-nav-item ${item.page === currentPage ? 'active' : ''}"
          onclick="navigate('${item.page}')">
          <span class="nav-icon">${item.icon}</span>
          <span class="label">${item.label}</span>
        </button>
      `).join('')}
    </div>
  `
}
