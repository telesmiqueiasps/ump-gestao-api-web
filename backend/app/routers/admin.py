from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
import secrets, string, datetime

from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.federation import Federation
from app.models.local_ump import LocalUmp
from app.models.enums import OrgType
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
        "created_at":        u.created_at.isoformat() if u.created_at else None,
    }


# ── Listar todos os usuários ──────────────────────────────────

@router.get("/users")
def list_all_users(
    search: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if search:
        term = search.lower()
        query = query.filter(
            sqlfunc.lower(User.full_name).contains(term) |
            sqlfunc.lower(User.email).contains(term)
        )
    seen_emails: set = set()
    result = []
    for u in query.order_by(User.full_name).all():
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