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
  {
    page: 'dashboard', label: 'Dashboard', icon: '⊞',
    path: '/pages/dashboard.html',
    roles: null
  },
  {
    page: 'profile', label: 'Perfil', icon: '◎',
    path: '/pages/profile.html',
    roles: null
  },
  {
    page: 'finances', label: 'Financeiro', icon: '◈',
    path: '/pages/finances.html',
    roles: ['presidente','vice_presidente','tesoureiro','conselheiro','secretario_presbiterial']
  },
  {
    page: 'members', label: 'Sócios', icon: '◉',
    path: '/pages/members.html',
    localOnly: true,
    roles: ['presidente','vice_presidente','tesoureiro','conselheiro','secretario_presbiterial']
  },
  {
    page: 'board', label: 'Diretoria', icon: '❖',
    path: '/pages/board.html',
    roles: ['presidente','vice_presidente','conselheiro','secretario_presbiterial']
  },
  {
    page: 'local-umps', label: 'UMPs Locais', icon: '⊟',
    path: '/pages/local-umps.html',
    fedOnly: true,
    roles: ['presidente','vice_presidente','conselheiro','secretario_presbiterial']
  },
  {
    page: 'secretary', label: 'Secretaria', icon: '📋',
    path: '/pages/secretary.html',
    roles: ['presidente','vice_presidente','1_secretario','2_secretario','secretario_executivo','conselheiro','secretario_presbiterial']
  },
  {
    page: 'president', label: 'Presidência', icon: '👑',
    path: '/pages/president.html',
    roles: ['presidente','vice_presidente','conselheiro','secretario_presbiterial']
  },
  {
    page: 'notices', label: 'Avisos', icon: '📢',
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

export function renderShell() {
  const user = getUser()
  if (!user) return

  const roleLabel = user.roles?.length
    ? (ROLE_LABELS[user.roles[0]] || user.roles[0])
    : ''

  const userRoles = user?.roles ?? []

  const navHTML = NAV_ITEMS
    .filter(item => {
      if (item.fedOnly && !isFederation()) return false
      if (item.localOnly && !isLocalUmp()) return false
      if (item.roles === null) return true
      return item.roles.some(r => userRoles.includes(r))
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

  // Botão de alterar senha antes do footer
  const sidebarFooter = document.querySelector('.sidebar-footer')
  if (sidebarFooter) {
    const pwBtn = document.createElement('button')
    pwBtn.className = 'sidebar-pw-btn'
    pwBtn.innerHTML = '🔒 Alterar senha'
    pwBtn.addEventListener('click', () => openPasswordModal())
    sidebarFooter.parentNode.insertBefore(pwBtn, sidebarFooter)
  }

  // Injeta modal de senha no body se ainda não existir
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
