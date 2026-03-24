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


# Federação lista usuários de uma Local sua
@router.get("/by-org/{org_id}")
def list_users_by_org(
    org_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
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
    ).all()
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


def _to_out(u: User) -> dict:
    return {
        "id": str(u.id),
        "full_name": u.full_name,
        "email": u.email,
        "organization_id": str(u.organization_id),
        "organization_type": u.organization_type.value,
        "is_active": u.is_active,
    }