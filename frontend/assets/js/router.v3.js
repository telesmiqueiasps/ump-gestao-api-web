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

function getOrgLabel(orgType, societyType) {
  if (orgType === 'federation') return `Federação ${societyType || 'UMP'}`
  return `${societyType || 'UMP'} Local`
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
    page: 'statistics', label: 'Estatísticas', icon: '/assets/img/estatistica.png',
    path: '/pages/statistics.html',
    uphOnly: true,
    roles: ['presidente','vice_presidente','tesoureiro','1_secretario','2_secretario',
            'secretario_executivo','secretario_presbiterial','conselheiro'],
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
  if (item.uphOnly && (localStorage.getItem('society_type') || 'UMP') !== 'UPH') return false
  if (item.roles === null) return true
  const userRoles = getUser()?.roles ?? []
  return item.roles.some(r => userRoles.includes(r))
}

const MEMBER_LABELS = { UMP: 'Sócios', UPH: 'Sócios', SAF: 'Associadas', UPA: 'Participantes' }

// ID da federação administradora — preencha após criar via painel admin
const ADMIN_FEDERATION_ID = 'cf5aaa60-0fd1-4ee5-a0cd-a37849b87a09'

function buildNavHTML(user, societyType) {
  societyType = societyType || localStorage.getItem('society_type') || 'UMP'
  const userRoles = user?.roles ?? []
  const memberLabel = MEMBER_LABELS[societyType] || 'Sócios'

  return NAV_ITEMS
    .filter(item => {
      if (item.fedOnly   && !isFederation()) return false
      if (item.localOnly && !isLocalUmp())   return false
      if (item.uphOnly   && societyType !== 'UPH') return false
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
    }).join('') +
    (ADMIN_FEDERATION_ID && user?.organization_id === ADMIN_FEDERATION_ID
      ? `<button class="nav-item" data-page="admin"
           onclick="window.location.href='/pages/admin.html'"
           style="color:#f97316">
           <span style="width:24px;height:24px;display:inline-flex;
                        align-items:center;justify-content:center;font-size:1rem">⚙️</span>
           Admin
         </button>`
      : '')
}

// ── Cache de perfil (5 min) ────────────────────────────────────────────────
const _PROFILE_KEY  = 'cached_profile'
const _PROFILE_TIME = 'cached_profile_time'
const _PROFILE_TTL  = 5 * 60 * 1000

async function _getProfile(api, endpoint) {
  const cached = localStorage.getItem(_PROFILE_KEY)
  const cachedTime = localStorage.getItem(_PROFILE_TIME)
  if (cached && cachedTime && (Date.now() - parseInt(cachedTime)) < _PROFILE_TTL)
    return JSON.parse(cached)
  const data = await api.get(endpoint)
  localStorage.setItem(_PROFILE_KEY, JSON.stringify(data))
  localStorage.setItem(_PROFILE_TIME, Date.now().toString())
  return data
}

// ── Cache de logo (1 hora) ─────────────────────────────────────────────────
const _LOGO_KEY  = 'cached_logo_b64'
const _LOGO_TIME = 'cached_logo_time'
const _LOGO_TTL  = 60 * 60 * 1000

async function _getLogoB64(api, orgType) {
  const cached = localStorage.getItem(_LOGO_KEY)
  const cachedTime = localStorage.getItem(_LOGO_TIME)
  if (cached && cachedTime && (Date.now() - parseInt(cachedTime)) < _LOGO_TTL)
    return cached
  try {
    const endpoint = orgType === 'federation'
      ? '/api/federations/me/logo-url'
      : '/api/local-umps/me/logo-url'
    const data = await api.get(endpoint)
    const b64 = data.base64 || null
    if (b64) {
      localStorage.setItem(_LOGO_KEY, b64)
      localStorage.setItem(_LOGO_TIME, Date.now().toString())
    }
    return b64
  } catch {
    return cached || null
  }
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
    const data = await _getProfile(api, endpoint)
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
    `${getOrgLabel(user.organization_type, societyType)}${roleLabel ? ' · ' + roleLabel : ''}`
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

  // Botão de troca de organização (apenas se tiver múltiplas)
  try {
    const { api } = await import('./api.js')
    const myOrgs = await api.get('/api/users/my-organizations')
    if (myOrgs.length > 1) {
      const headerRight = document.querySelector('.header-right')
      if (headerRight && !document.getElementById('btn-switch-org')) {
        const switchBtn = document.createElement('button')
        switchBtn.id = 'btn-switch-org'
        switchBtn.title = 'Trocar de organização'
        switchBtn.style.cssText = 'background:none;border:none;cursor:pointer;font-size:1rem;padding:.35rem .5rem;color:var(--slate-500);line-height:1'
        switchBtn.innerHTML = '<img src="/assets/img/trocar.png" alt="Trocar" style="width:20px;height:20px;display:block" />'
        switchBtn.addEventListener('click', () => showOrgSwitchModal(myOrgs))
        const avatar = headerRight.querySelector('.header-avatar')
        if (avatar) headerRight.insertBefore(switchBtn, avatar)
        else headerRight.appendChild(switchBtn)
      }
    }
  } catch {}

  checkNoticesBadge()
  import('./api.js').then(({ api: _a }) =>
    _getLogoB64(_a, user.organization_type).then(b64 => {
      if (!b64) return
      const logoEl = document.querySelector('.sidebar-brand-logo')
      if (logoEl) logoEl.src = b64
    }).catch(() => {})
  )
  initMobileMenu()
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

const CACHE_BUST = '?v=7'

const ICON_IMAGES = {
  dashboard:  '/assets/img/dashboard_mobile.png' + CACHE_BUST,
  finances:   '/assets/img/financeiro_mobile.png' + CACHE_BUST,
  board:      '/assets/img/diretoria_mobile.png' + CACHE_BUST,
  notices:    '/assets/img/aviso_mobile.png' + CACHE_BUST,
}

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
      ${visibleItems.map(item => {
        const hasImg = ICON_IMAGES[item.page]
        const iconHtml = hasImg
          ? `<img src="${ICON_IMAGES[item.page]}" style="width:24px;height:24px;object-fit:contain;opacity:${item.page === currentPage ? '1' : '0.5'}" />`
          : `<span class="nav-icon" style="font-size:1.3rem">${item.icon}</span>`
        return `
          <button class="bottom-nav-item ${item.page === currentPage ? 'active' : ''}"
            onclick="navigate('${item.page}')">
            ${iconHtml}
            <span class="label">${item.label}</span>
          </button>
        `
      }).join('')}
    </div>
  `
}

// ── Troca de organização ────────────────────────────────────────────────────

function _formatRoleLabel(role) {
  const map = {
    'presidente': 'Presidente', 'vice_presidente': 'Vice-Presidente',
    'tesoureiro': 'Tesoureiro(a)', '1_secretario': '1º Secretário(a)',
    '2_secretario': '2º Secretário(a)', 'secretario_executivo': 'Sec. Executivo(a)',
    'secretario_presbiterial': 'Sec. Presbiterial', 'conselheiro': 'Conselheiro(a)',
  }
  return map[role] || role
}

window.showOrgSwitchModal = function(orgs) {
  document.getElementById('modal-switch-org')?.remove()

  const currentUserId = getUser()?.id

  const modal = document.createElement('div')
  modal.id = 'modal-switch-org'
  modal.className = 'modal-overlay'
  modal.style.display = 'flex'
  modal.innerHTML = `
    <div class="modal modal-sm">
      <div class="modal-header">
        <div>
          <h2>Trocar de Organização</h2>
          <p style="font-size:.78rem;color:var(--slate-500);margin-top:.15rem">
            Selecione a organização para entrar
          </p>
        </div>
        <button class="modal-close" onclick="document.getElementById('modal-switch-org').remove()">✕</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:.5rem">
        ${orgs.map(org => {
          const isCurrent = org.is_current || org.user_id === currentUserId
          const orgUserId = org.user_id
          return `
            <button
              style="display:flex;align-items:center;gap:.75rem;padding:.75rem 1rem;
                background:${isCurrent ? '#f0f9ff' : '#fff'};
                border:2px solid ${isCurrent ? '#1a2a6c' : 'var(--slate-200)'};
                border-radius:10px;cursor:${isCurrent ? 'default' : 'pointer'};
                text-align:left;font-family:inherit;width:100%;transition:all .15s;"
              ${isCurrent ? 'disabled' : `onclick="window.switchToOrg('${orgUserId}')"`}
            >
              <div style="width:36px;height:36px;border-radius:50%;flex-shrink:0;
                background:linear-gradient(135deg,#1a2a6c,#2a3f9f);
                display:flex;align-items:center;justify-content:center;
                color:#fff;font-weight:700;font-size:.85rem;">
                ${(org.org_name || '?').charAt(0).toUpperCase()}
              </div>
              <div style="flex:1;min-width:0">
                <div style="font-weight:600;font-size:.875rem;color:var(--slate-800)">${org.org_name}</div>
                <div style="font-size:.72rem;color:var(--slate-500);margin-top:.1rem">
                  ${org.organization_type === 'federation' ? 'Federação' : 'UMP Local'}
                  · ${_formatRoleLabel(org.role)}
                </div>
              </div>
              ${isCurrent
                ? '<span style="font-size:.7rem;color:#1a2a6c;font-weight:600">atual</span>'
                : '<span style="color:var(--slate-300)">›</span>'}
            </button>`
        }).join('')}
      </div>
    </div>`

  document.body.appendChild(modal)
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove() })
}

window.switchToOrg = window._switchToOrg = async function(userId) {
  try {
    const response = await fetch(
      'https://ump-gestao-api.onrender.com/api/auth/login/select-org',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
      }
    )
    const data = await response.json()
    if (!response.ok) { alert(data.detail || 'Erro ao trocar organização'); return }

    // Limpa todo o localStorage exceto as chaves que serão reescritas
    const keep = new Set(['access_token', 'refresh_token', 'user', 'society_type'])
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (!keep.has(key)) localStorage.removeItem(key)
    }

    // Salva novos dados da org selecionada
    localStorage.setItem('access_token',  data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    localStorage.setItem('user', JSON.stringify({
      id:                data.user_id,
      full_name:         data.full_name,
      organization_id:   data.organization_id,
      organization_type: data.organization_type,
      roles:             data.roles,
    }))
    localStorage.setItem('society_type', data.society_type || 'UMP')

    document.getElementById('modal-switch-org')?.remove()
    window.location.href = '/pages/dashboard.html'
  } catch {
    alert('Erro de conexão. Tente novamente.')
  }
}

export function initMobileMenu() {
  const btnMenu = document.getElementById('btn-menu')
  const sidebar = document.querySelector('.sidebar')
  const overlay = document.getElementById('sidebar-overlay')

  if (!btnMenu || !sidebar) return

  // Remove listeners antigos para evitar duplicação
  const newBtn = btnMenu.cloneNode(true)
  btnMenu.parentNode.replaceChild(newBtn, btnMenu)

  newBtn.addEventListener('click', (e) => {
    e.stopPropagation()
    sidebar.classList.toggle('open')
    overlay?.classList.toggle('open')
  })

  overlay?.addEventListener('click', () => {
    sidebar.classList.remove('open')
    overlay.classList.remove('open')
  })

  // Fecha ao clicar em item do nav
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        sidebar.classList.remove('open')
        overlay?.classList.remove('open')
      }
    })
  })

  // Mostra/esconde btn-menu conforme tamanho da tela
  const toggleMenuVisibility = () => {
    newBtn.style.display = window.innerWidth <= 768 ? 'flex' : 'none'
    if (window.innerWidth > 768) {
      sidebar.classList.remove('open')
      overlay?.classList.remove('open')
    }
  }
  toggleMenuVisibility()
  window.addEventListener('resize', toggleMenuVisibility)
}
