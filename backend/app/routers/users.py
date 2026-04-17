from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.enums import OrgType, BoardRole
from app.core.dependencies import get_current_user, require_federation
from app.core.security import hash_password

router = APIRouter()


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    organization_id: UUID
    organization_type: OrgType
    role: BoardRole
    fiscal_year: Optional[int] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


# Federação cria usuário para si ou para uma Local sua
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
):
    # Verificações removidas temporariamente para permitir criação sem autenticação

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")

    user = User(
        organization_id=payload.organization_id,
        organization_type=payload.organization_type,
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()

    year = payload.fiscal_year or datetime.date.today().year
    role = UserRole(user_id=user.id, role=payload.role, fiscal_year=year)
    db.add(role)
    db.commit()
    db.refresh(user)
    return _to_out(user)


# Usuário atualiza seus próprios dados
@router.put("/me", )
def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return _to_out(current_user)


# Troca de senha
@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.core.security import verify_password
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()


# Lista usuários de uma organização
@router.get("/by-org/{org_id}")
def list_users_by_org(
    org_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Permite acessar a própria organização
    if str(org_id) == str(current_user.organization_id):
        users = db.query(User).filter(
            User.organization_id == org_id,
            User.is_active == True,
        ).limit(500).all()
        return [_to_out(u) for u in users]

    # Federação acessando uma Local sua
    if current_user.organization_type.value != "federation":
        raise HTTPException(status_code=403, detail="Acesso negado")

    from app.models.local_ump import LocalUmp
    local = db.query(LocalUmp).filter(
        LocalUmp.id == org_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=403, detail="Acesso negado")

    users = db.query(User).filter(
        User.organization_id == org_id,
        User.is_active == True,
    ).limit(500).all()
    return [_to_out(u) for u in users]


# Federação desativa usuário
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    from app.models.local_ump import LocalUmp
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if target.organization_type == OrgType.local_ump:
        local = db.query(LocalUmp).filter(
            LocalUmp.id == target.organization_id,
            LocalUmp.federation_id == current_user.organization_id,
        ).first()
        if not local:
            raise HTTPException(status_code=403, detail="Acesso negado")
    elif str(target.organization_id) != str(current_user.organization_id):
        raise HTTPException(status_code=403, detail="Acesso negado")

    target.is_active = False
    db.commit()


class ExtraOrgPayload(BaseModel):
    user_email: str
    organization_id: UUID
    organization_type: str
    role: str
    fiscal_year: Optional[int] = None


@router.post("/link-org")
def link_user_to_org(
    payload: ExtraOrgPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Vincula um usuário existente a uma organização adicional"""
    from app.models.user_organization import UserOrganization

    year = datetime.date.today().year
    ur = db.query(UserRole).filter(
        UserRole.user_id     == current_user.id,
        UserRole.fiscal_year == year,
        UserRole.is_active   == True,
    ).first()
    user_role = ur.role.value if ur and hasattr(ur.role, 'value') else str(ur.role) if ur else ''
    allowed = {'presidente', 'vice_presidente', 'secretario_presbiterial', 'conselheiro'}
    if user_role not in allowed:
        raise HTTPException(status_code=403, detail="Sem permissão")

    target_user = db.query(User).filter(
        User.email == payload.user_email.lower().strip()
    ).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado com este email")

    fiscal_year = payload.fiscal_year or year

    existing = db.query(UserOrganization).filter(
        UserOrganization.user_id         == target_user.id,
        UserOrganization.organization_id == payload.organization_id,
        UserOrganization.fiscal_year     == fiscal_year,
    ).first()
    if existing:
        existing.is_active = True
        existing.role      = payload.role
        db.commit()
        return {"detail": "Vínculo atualizado com sucesso", "user_name": target_user.full_name}

    uo = UserOrganization(
        user_id           = target_user.id,
        organization_id   = payload.organization_id,
        organization_type = payload.organization_type,
        role              = payload.role,
        fiscal_year       = fiscal_year,
    )
    db.add(uo)
    db.commit()
    return {
        "detail":    f"Usuário {target_user.full_name} vinculado com sucesso",
        "user_name": target_user.full_name,
    }


@router.delete("/link-org/{user_org_id}", status_code=204)
def unlink_user_from_org(
    user_org_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.user_organization import UserOrganization
    uo = db.query(UserOrganization).filter(
        UserOrganization.id == user_org_id
    ).first()
    if not uo:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado")
    uo.is_active = False
    db.commit()


@router.get("/my-organizations")
def list_my_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista todas as organizações do usuário logado"""
    from app.models.user_organization import UserOrganization
    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp

    year     = datetime.date.today().year
    org_type = current_user.organization_type.value \
        if hasattr(current_user.organization_type, 'value') \
        else str(current_user.organization_type)

    if org_type == 'federation':
        obj = db.query(Federation).filter(Federation.id == current_user.organization_id).first()
    else:
        obj = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()

    ur = db.query(UserRole).filter(
        UserRole.user_id     == current_user.id,
        UserRole.fiscal_year == year,
        UserRole.is_active   == True,
    ).first()
    role_str = ur.role.value if ur and hasattr(ur.role, 'value') \
               else str(ur.role) if ur else 'membro'

    orgs = [{
        "id":                None,
        "organization_id":   str(current_user.organization_id),
        "organization_type": org_type,
        "org_name":          obj.name if obj else '',
        "role":              role_str,
        "is_primary":        True,
    }]

    extras = db.query(UserOrganization).filter(
        UserOrganization.user_id   == current_user.id,
        UserOrganization.is_active == True,
    ).all()
    for eo in extras:
        if eo.organization_type == 'federation':
            obj2 = db.query(Federation).filter(Federation.id == eo.organization_id).first()
        else:
            obj2 = db.query(LocalUmp).filter(LocalUmp.id == eo.organization_id).first()
        orgs.append({
            "id":                str(eo.id),
            "organization_id":   str(eo.organization_id),
            "organization_type": eo.organization_type,
            "org_name":          obj2.name if obj2 else '',
            "role":              eo.role,
            "is_primary":        False,
        })

    return orgs


def _to_out(u: User) -> dict:
    latest_role = max(u.roles, key=lambda r: r.fiscal_year, default=None) if u.roles else None
    return {
        "id": str(u.id),
        "full_name": u.full_name,
        "email": u.email,
        "organization_id": str(u.organization_id),
        "organization_type": u.organization_type.value,
        "is_active": u.is_active,
        "role": latest_role.role.value if latest_role else None,
    }