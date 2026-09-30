from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
import secrets, string, datetime

from app.db.session import get_db
from app.models.user import User, UserRole, RolePermission
from app.models.federation import Federation
from app.models.local_ump import LocalUmp
from app.models.enums import OrgType
from app.models.finance import FinancialPeriod
from app.models.activity_report import ActivityReport
from app.core.admin import require_admin
from app.core.security import hash_password

router = APIRouter()

ROLE_LABELS = {
    'presidente':             'Presidente',
    'vice_presidente':        'Vice-Presidente',
    '1_secretario':           '1º Secretário(a)',
    '2_secretario':           '2º Secretário(a)',
    'tesoureiro':             'Tesoureiro(a)',
    'secretario_executivo':   'Sec. Executivo(a)',
    'secretario_presbiterial':'Sec. Presbiterial',
    'conselheiro':            'Conselheiro(a)',
}


def _org_name(db: Session, org_id, org_type: str) -> str:
    if org_type == 'federation':
        obj = db.query(Federation).filter(Federation.id == org_id).first()
        return obj.name if obj else 'Federação'
    obj = db.query(LocalUmp).filter(LocalUmp.id == org_id).first()
    return obj.name if obj else 'UMP Local'


def _user_out(u: User, db: Session) -> dict:
    org_type = u.organization_type.value \
        if hasattr(u.organization_type, 'value') \
        else str(u.organization_type)

    roles = db.query(UserRole).filter(
        UserRole.user_id == u.id,
        UserRole.is_active == True,
    ).all()
    role_list = [
        {
            "role": r.role.value if hasattr(r.role, 'value') else str(r.role),
            "role_label": ROLE_LABELS.get(
                r.role.value if hasattr(r.role, 'value') else str(r.role), ''),
            "fiscal_year": r.fiscal_year,
        }
        for r in roles
    ]

    all_users = db.query(User).filter(
        sqlfunc.lower(User.email) == u.email.lower()
    ).all()

    orgs = []
    for au in all_users:
        au_type = au.organization_type.value \
            if hasattr(au.organization_type, 'value') \
            else str(au.organization_type)
        orgs.append({
            "user_id":           str(au.id),
            "organization_id":   str(au.organization_id),
            "organization_type": au_type,
            "org_name":          _org_name(db, au.organization_id, au_type),
            "is_active":         au.is_active,
        })

    return {
        "id":                str(u.id),
        "full_name":         u.full_name,
        "email":             u.email,
        "organization_id":   str(u.organization_id),
        "organization_type": org_type,
        "org_name":          _org_name(db, u.organization_id, org_type),
        "is_active":         u.is_active,
        "roles":             role_list,
        "all_orgs":          orgs,
        "custom_permissions": u.custom_permissions or None,
        "has_custom_permissions": bool(u.custom_permissions is not None and len(u.custom_permissions) > 0),
        "created_at":        u.created_at.isoformat() if u.created_at else None,
    }


# ── Listar todos os usuários ──────────────────────────────────

@router.get("/users")
def list_all_users(
    search: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User).order_by(User.full_name)
    if search:
        term = search.lower()
        query = query.filter(
            sqlfunc.lower(User.full_name).contains(term) |
            sqlfunc.lower(User.email).contains(term)
        )
    else:
        # Limita a 50 usuários por padrão para evitar lentidão e timeout (problema de N+1 queries)
        query = query.limit(50)
        
    seen_emails: set = set()
    result = []
    for u in query.all():
        if u.email.lower() not in seen_emails:
            seen_emails.add(u.email.lower())
            result.append(_user_out(u, db))
    return result


# ── Reset de senha ────────────────────────────────────────────

class ResetPasswordPayload(BaseModel):
    new_password: Optional[str] = None


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: UUID,
    payload: ResetPasswordPayload,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if payload.new_password:
        new_pass = payload.new_password
    else:
        chars = string.ascii_letters + string.digits + "!@#$%"
        new_pass = ''.join(secrets.choice(chars) for _ in range(10))

    new_hash = hash_password(new_pass)

    db.query(User).filter(
        sqlfunc.lower(User.email) == user.email.lower()
    ).update({"password_hash": new_hash}, synchronize_session=False)
    db.commit()

    return {
        "detail":       "Senha redefinida com sucesso",
        "new_password": new_pass,
        "email":        user.email,
    }


# ── Ativar/Desativar usuário ──────────────────────────────────

@router.post("/users/{user_id}/toggle-active")
def toggle_user_active(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    new_status = not user.is_active
    now = datetime.datetime.now(datetime.timezone.utc)

    db.query(User).filter(
        sqlfunc.lower(User.email) == user.email.lower()
    ).update({
        "is_active":       new_status,
        "deactivated_at":  now if not new_status else None,
    }, synchronize_session=False)
    db.commit()

    return {
        "detail":    f"Usuário {'ativado' if new_status else 'desativado'} com sucesso",
        "is_active": new_status,
    }


# ── Criar federação ───────────────────────────────────────────

class FederationCreatePayload(BaseModel):
    name: str
    presbytery_name: str
    synodal_name: Optional[str] = None
    society_type: Optional[str] = 'UMP'
    theme_color: Optional[str] = '#1a2a6c'


class InitialUserPayload(BaseModel):
    full_name: str
    email: str
    password: str
    role: str
    fiscal_year: Optional[int] = None


class CreateFederationRequest(BaseModel):
    federation: FederationCreatePayload
    users: List[InitialUserPayload]


@router.post("/federations")
def create_federation(
    payload: CreateFederationRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    fed = Federation(
        name            = payload.federation.name,
        presbytery_name = payload.federation.presbytery_name,
        synodal_name    = payload.federation.synodal_name,
        society_type    = payload.federation.society_type,
        theme_color     = payload.federation.theme_color,
        is_active       = True,
    )
    db.add(fed)
    db.flush()

    year = datetime.date.today().year
    created_users = []

    for u_data in payload.users:
        existing = db.query(User).filter(
            sqlfunc.lower(User.email) == u_data.email.lower()
        ).first()

        if existing:
            existing_type = existing.organization_type.value \
                if hasattr(existing.organization_type, 'value') \
                else str(existing.organization_type)
            if existing_type == 'federation':
                raise HTTPException(
                    status_code=400,
                    detail=f"Email {u_data.email} já cadastrado em outra federação"
                )
            pw_hash = existing.password_hash
        else:
            pw_hash = hash_password(u_data.password)

        new_user = User(
            email             = u_data.email.lower().strip(),
            full_name         = u_data.full_name,
            password_hash     = pw_hash,
            organization_id   = fed.id,
            organization_type = OrgType.federation,
            is_active         = True,
        )
        db.add(new_user)
        db.flush()

        user_role = UserRole(
            user_id     = new_user.id,
            role        = u_data.role,
            fiscal_year = u_data.fiscal_year or year,
            is_active   = True,
        )
        db.add(user_role)
        created_users.append({
            "id":        str(new_user.id),
            "full_name": new_user.full_name,
            "email":     new_user.email,
            "role":      u_data.role,
        })

    db.commit()
    return {
        "detail":     "Federação criada com sucesso",
        "federation": {"id": str(fed.id), "name": fed.name},
        "users":      created_users,
    }


# ── Listar todas as federações ────────────────────────────────

@router.get("/federations")
def list_all_federations(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    feds = db.query(Federation).order_by(Federation.name).all()
    result = []
    for f in feds:
        user_count = db.query(User).filter(
            User.organization_id == f.id
        ).count()
        result.append({
            "id":              str(f.id),
            "name":            f.name,
            "presbytery_name": f.presbytery_name,
            "society_type":    f.society_type,
            "is_active":       f.is_active,
            "user_count":      user_count,
        })
    return result


# ── Listar todas as UMPs Locais ────────────────────────────────

@router.get("/local-umps")
def list_all_local_umps(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    locals = db.query(LocalUmp).filter(
        LocalUmp.id != LocalUmp.federation_id,
        ~LocalUmp.name.ilike('%eleiç%'),
        ~LocalUmp.name.ilike('%eleic%'),
    ).order_by(LocalUmp.name).all()
    result = []
    for l in locals:
        user_count = db.query(User).filter(
            User.organization_id == l.id
        ).count()
        result.append({
            "id":              str(l.id),
            "name":            l.name,
            "presbytery_name": l.presbytery_name,
            "is_active":       l.is_active,
            "user_count":      user_count,
        })
    return result


# ── Gerenciamento e Reabertura de Períodos e Relatórios ────────

@router.get("/organizations/{org_id}/periods")
def get_organization_periods(
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Identifica a organização (Federação ou UMP Local)
    fed = db.query(Federation).filter(Federation.id == org_id).first()
    loc = db.query(LocalUmp).filter(LocalUmp.id == org_id).first() if not fed else None

    if not fed and not loc:
        raise HTTPException(status_code=404, detail="Organização não encontrada")

    org_name = fed.name if fed else loc.name
    org_type = "federation" if fed else "local_ump"

    # Busca períodos financeiros
    fin_periods = db.query(FinancialPeriod).filter(
        FinancialPeriod.organization_id == org_id
    ).order_by(FinancialPeriod.fiscal_year.desc()).all()

    # Busca relatórios de atividades
    act_reports = db.query(ActivityReport).filter(
        ActivityReport.organization_id == org_id
    ).order_by(ActivityReport.fiscal_year.desc()).all()

    fin_out = [
        {
            "id": str(p.id),
            "fiscal_year": p.fiscal_year,
            "initial_balance": float(p.initial_balance or 0),
            "is_closed": bool(p.is_closed),
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            "validation_code": p.validation_code,
            "is_locked": bool(p.is_locked),
            "has_report_url": bool(p.report_url),
            "has_receipts_url": bool(p.receipts_report_url),
        }
        for p in fin_periods
    ]

    act_out = [
        {
            "id": str(r.id),
            "fiscal_year": r.fiscal_year,
            "status": r.status,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "has_report_url": bool(r.report_url),
        }
        for r in act_reports
    ]

    return {
        "org_id": str(org_id),
        "org_name": org_name,
        "org_type": org_type,
        "financial_periods": fin_out,
        "activity_reports": act_out,
    }


@router.post("/financial-periods/{period_id}/reopen")
def reopen_financial_period(
    period_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    period = db.query(FinancialPeriod).filter(FinancialPeriod.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="Período financeiro não encontrado")

    if not period.is_closed:
        raise HTTPException(status_code=400, detail=f"O período financeiro de {period.fiscal_year} já se encontra aberto.")

    # Regra LIFO: verificar se há ano posterior fechado para a mesma organização
    later_closed = db.query(FinancialPeriod).filter(
        FinancialPeriod.organization_id == period.organization_id,
        FinancialPeriod.fiscal_year > period.fiscal_year,
        FinancialPeriod.is_closed == True
    ).order_by(FinancialPeriod.fiscal_year.asc()).first()

    if later_closed:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível reabrir o ano {period.fiscal_year} porque o ano posterior ({later_closed.fiscal_year}) também está encerrado. Reabra primeiro o ano mais recente para preservar a integridade contábil dos saldos."
        )

    # Reabre o período financeiro e invalida autenticações e relatórios antigos
    period.is_closed = False
    period.closed_at = None
    period.is_locked = False
    period.ready_to_close = False
    period.validation_code = None
    period.data_hash = None
    period.report_url = None
    period.receipts_report_url = None
    db.commit()

    return {
        "detail": f"Período financeiro de {period.fiscal_year} reaberto com sucesso.",
        "fiscal_year": period.fiscal_year,
        "period_id": str(period.id),
    }


@router.post("/activity-reports/{report_id}/reopen")
def reopen_activity_report(
    report_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    report = db.query(ActivityReport).filter(ActivityReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Relatório de atividades não encontrado")

    if report.status != 'published':
        raise HTTPException(
            status_code=400,
            detail=f"O relatório de atividades de {report.fiscal_year} não está com status 'Publicado' (status atual: {report.status})."
        )

    # Reabre o relatório para rascunho
    report.status = 'draft'
    report.report_url = None
    db.commit()

    return {
        "detail": f"Relatório de atividades de {report.fiscal_year} reaberto para rascunho com sucesso.",
        "fiscal_year": report.fiscal_year,
        "report_id": str(report.id),
    }


# ── Metadados de Abas e Permissões de Acesso ──────────────────

AVAILABLE_TABS = [
    {
        "id": "finances",
        "name": "Financeiro",
        "description": "Livro caixa, lançamentos de receitas e despesas, relatórios financeiros",
        "icon": "financeiro",
        "scope": "both",
    },
    {
        "id": "members",
        "name": "Sócios / Delegados",
        "description": "Cadastro e gerenciamento de sócios locais ou delegados de federação",
        "icon": "socios",
        "scope": "both",
    },
    {
        "id": "board",
        "name": "Diretoria",
        "description": "Composição e cargos da diretoria em exercício",
        "icon": "diretoria",
        "scope": "both",
    },
    {
        "id": "local-umps",
        "name": "Sociedades Locais",
        "description": "Gestão das sociedades locais vinculadas (exclusivo Federação)",
        "icon": "umps_locais",
        "scope": "federation",
    },
    {
        "id": "secretary",
        "name": "Secretaria",
        "description": "Livro de atas, reuniões, pautas e documentos oficiais",
        "icon": "secretaria",
        "scope": "both",
    },
    {
        "id": "president",
        "name": "Presidência",
        "description": "Manual da liderança, modelos de documentos e resoluções",
        "icon": "presidente",
        "scope": "both",
    },
    {
        "id": "statistics",
        "name": "Estatísticas UPH",
        "description": "Relatório e formulário anual de estatísticas (exclusivo UPH)",
        "icon": "estatistica",
        "scope": "uph",
    },
    {
        "id": "ump-statistics",
        "name": "Estatísticas UMP",
        "description": "Coletor individual e painel estatístico consolidado (exclusivo UMP)",
        "icon": "estatistica",
        "scope": "ump",
    },
    {
        "id": "notices",
        "name": "Avisos e Comunicados",
        "description": "Mural de avisos internos e comunicados da liderança",
        "icon": "aviso",
        "scope": "both",
    },
    {
        "id": "calendar",
        "name": "Calendário",
        "description": "Agenda de programações, reuniões e eventos",
        "icon": "calendario",
        "scope": "both",
    },
    {
        "id": "eleicoes",
        "name": "Eleições",
        "description": "Módulo de votação eletrônica secreta para eleições",
        "icon": "eleicao",
        "scope": "both",
    },
    {
        "id": "congressos",
        "name": "Congressos / Credencial",
        "description": "Organização do congresso, homologação e credenciamento de delegados",
        "icon": "congressos",
        "scope": "both",
    },
]

DEFAULT_ROLE_PERMISSIONS = {
    'presidente': [
        'finances', 'members', 'board', 'local-umps', 'secretary',
        'president', 'statistics', 'ump-statistics', 'notices',
        'calendar', 'eleicoes', 'congressos'
    ],
    'vice_presidente': [
        'finances', 'members', 'board', 'local-umps', 'secretary',
        'president', 'statistics', 'ump-statistics', 'notices',
        'calendar', 'eleicoes', 'congressos'
    ],
    'tesoureiro': [
        'finances', 'members', 'statistics', 'ump-statistics',
        'notices', 'calendar', 'eleicoes', 'congressos'
    ],
    '1_secretario': [
        'secretary', 'statistics', 'ump-statistics',
        'notices', 'calendar', 'eleicoes', 'congressos'
    ],
    '2_secretario': [
        'secretary', 'statistics', 'ump-statistics',
        'notices', 'calendar', 'eleicoes', 'congressos'
    ],
    'secretario_executivo': [
        'secretary', 'statistics', 'ump-statistics',
        'notices', 'calendar', 'eleicoes', 'congressos'
    ],
    'secretario_presbiterial': [
        'finances', 'members', 'board', 'local-umps', 'secretary',
        'president', 'statistics', 'ump-statistics', 'notices',
        'calendar', 'eleicoes', 'congressos'
    ],
    'conselheiro': [
        'finances', 'members', 'board', 'local-umps', 'secretary',
        'president', 'statistics', 'ump-statistics', 'notices',
        'calendar', 'eleicoes', 'congressos'
    ],
}


class UserPermissionsPayload(BaseModel):
    custom_permissions: Optional[dict] = None


class RolePermissionsPayload(BaseModel):
    allowed_pages: Optional[List[str]] = None


@router.get("/permissions/metadata")
def get_permissions_metadata(
    current_user: User = Depends(require_admin),
):
    roles_list = [{"role": k, "role_label": v} for k, v in ROLE_LABELS.items()]
    return {
        "available_tabs": AVAILABLE_TABS,
        "default_role_permissions": DEFAULT_ROLE_PERMISSIONS,
        "roles": roles_list,
    }


@router.get("/users/{user_id}/permissions")
def get_user_permissions(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    year = datetime.date.today().year
    roles = db.query(UserRole).filter(
        UserRole.user_id == target.id,
        UserRole.is_active == True,
        UserRole.fiscal_year == year,
    ).all()
    user_roles = [r.role.value if hasattr(r.role, 'value') else str(r.role) for r in roles]

    role_perms = db.query(RolePermission).all()
    custom_roles_map = {rp.role: rp.allowed_pages for rp in role_perms}

    role_default_pages = set()
    for r in user_roles:
        if r in custom_roles_map:
            role_default_pages.update(custom_roles_map[r])
        elif r in DEFAULT_ROLE_PERMISSIONS:
            role_default_pages.update(DEFAULT_ROLE_PERMISSIONS[r])

    if not user_roles:
        role_default_pages.update(['notices', 'calendar'])

    user_custom = target.custom_permissions or {}
    has_custom = bool(target.custom_permissions is not None and len(target.custom_permissions) > 0)

    effective_permissions = {}
    for tab in AVAILABLE_TABS:
        tab_id = tab["id"]
        if tab_id in user_custom:
            effective_permissions[tab_id] = bool(user_custom[tab_id])
        else:
            effective_permissions[tab_id] = (tab_id in role_default_pages)

    return {
        "user_id": str(target.id),
        "full_name": target.full_name,
        "email": target.email,
        "organization_id": str(target.organization_id),
        "organization_type": target.organization_type.value if hasattr(target.organization_type, 'value') else str(target.organization_type),
        "user_roles": user_roles,
        "has_custom_permissions": has_custom,
        "custom_permissions": target.custom_permissions or None,
        "role_defaults": list(role_default_pages),
        "effective_permissions": effective_permissions,
        "available_tabs": AVAILABLE_TABS,
    }


@router.put("/users/{user_id}/permissions")
def update_user_permissions(
    user_id: UUID,
    payload: UserPermissionsPayload,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if payload.custom_permissions is None or len(payload.custom_permissions) == 0:
        target.custom_permissions = None
        detail = "Permissões personalizadas removidas. O usuário voltou ao padrão do cargo."
    else:
        target.custom_permissions = payload.custom_permissions
        detail = "Permissões personalizadas salvas com sucesso para o usuário."

    db.commit()
    db.refresh(target)
    return {
        "detail": detail,
        "user_id": str(target.id),
        "has_custom_permissions": target.custom_permissions is not None,
        "custom_permissions": target.custom_permissions,
    }


@router.get("/roles/permissions")
def list_role_permissions(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    role_perms = db.query(RolePermission).all()
    custom_map = {rp.role: rp.allowed_pages for rp in role_perms}

    result = []
    for r_key, r_label in ROLE_LABELS.items():
        is_custom = r_key in custom_map
        allowed = custom_map[r_key] if is_custom else DEFAULT_ROLE_PERMISSIONS.get(r_key, ['notices', 'calendar'])
        result.append({
            "role": r_key,
            "role_label": r_label,
            "is_custom": is_custom,
            "allowed_pages": allowed,
            "default_pages": DEFAULT_ROLE_PERMISSIONS.get(r_key, ['notices', 'calendar']),
        })
    return {
        "roles": result,
        "available_tabs": AVAILABLE_TABS,
    }


@router.put("/roles/{role_name}/permissions")
def update_role_permissions(
    role_name: str,
    payload: RolePermissionsPayload,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if role_name not in ROLE_LABELS:
        raise HTTPException(status_code=400, detail=f"Cargo inválido: {role_name}")

    existing = db.query(RolePermission).filter(RolePermission.role == role_name).first()

    if payload.allowed_pages is None:
        if existing:
            db.delete(existing)
            db.commit()
        return {
            "detail": f"Permissões do cargo {ROLE_LABELS[role_name]} restauradas para o padrão do sistema.",
            "role": role_name,
            "is_custom": False,
            "allowed_pages": DEFAULT_ROLE_PERMISSIONS.get(role_name, ['notices', 'calendar']),
        }

    if existing:
        existing.allowed_pages = payload.allowed_pages
    else:
        new_rp = RolePermission(role=role_name, allowed_pages=payload.allowed_pages)
        db.add(new_rp)

    db.commit()
    return {
        "detail": f"Permissões do cargo {ROLE_LABELS[role_name]} atualizadas com sucesso.",
        "role": role_name,
        "is_custom": True,
        "allowed_pages": payload.allowed_pages,
    }