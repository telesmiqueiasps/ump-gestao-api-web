from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
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
    password: Optional[str] = None   # opcional quando email já existe em outra org
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


@router.get("/check-email")
def check_email(
    email: str,
    organization_id: str,
    organization_type: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verifica se email já existe, bloqueia duplicatas no mesmo tipo de org."""
    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp

    existing_users = db.query(User).filter(
        sqlfunc.lower(User.email) == email.lower().strip()
    ).all()

    if not existing_users:
        return {"exists": False, "can_register": True}

    for existing in existing_users:
        existing_org_type = existing.organization_type.value \
            if hasattr(existing.organization_type, 'value') \
            else str(existing.organization_type)

        # Mesma organização — bloqueia
        if str(existing.organization_id) == str(organization_id):
            return {
                "exists": True,
                "can_register": False,
                "error": "Este email já está cadastrado nesta organização.",
            }

        # Mesmo tipo de organização — bloqueia
        if existing_org_type == organization_type:
            if existing_org_type == 'federation':
                obj = db.query(Federation).filter(
                    Federation.id == existing.organization_id).first()
                org_name = obj.name if obj else 'outra Federação'
            else:
                obj = db.query(LocalUmp).filter(
                    LocalUmp.id == existing.organization_id).first()
                org_name = obj.name if obj else 'outra UMP Local'

            tipo_plural = 'federações' if existing_org_type == 'federation' else 'UMPs Locais'
            return {
                "exists": True,
                "can_register": False,
                "error": f"Este email já está cadastrado em {org_name}. "
                         f"Não é permitido o mesmo email em duas {tipo_plural}.",
            }

    # Email existe mas em tipo diferente (fed+local) — permitido
    existing = existing_users[0]
    existing_org_type = existing.organization_type.value \
        if hasattr(existing.organization_type, 'value') \
        else str(existing.organization_type)

    if existing_org_type == 'federation':
        obj = db.query(Federation).filter(Federation.id == existing.organization_id).first()
    else:
        obj = db.query(LocalUmp).filter(LocalUmp.id == existing.organization_id).first()

    return {
        "exists": True,
        "can_register": True,
        "org_name": obj.name if obj else '',
        "org_type": existing_org_type,
        "full_name": existing.full_name,
    }


# Federação cria usuário para si ou para uma Local sua
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
):
    existing_users = db.query(User).filter(
        sqlfunc.lower(User.email) == payload.email.lower().strip()
    ).all()

    password_hash = None
    for existing in existing_users:
        existing_org_type = existing.organization_type.value \
            if hasattr(existing.organization_type, 'value') \
            else str(existing.organization_type)

        if str(existing.organization_id) == str(payload.organization_id):
            raise HTTPException(
                status_code=400,
                detail="Este email já está cadastrado nesta organização."
            )

        payload_org_type = payload.organization_type.value \
            if hasattr(payload.organization_type, 'value') \
            else str(payload.organization_type)

        if existing_org_type == payload_org_type:
            raise HTTPException(
                status_code=400,
                detail="Não é permitido o mesmo email em organizações do mesmo tipo."
            )

        # Reutiliza senha do usuário existente (tipo diferente)
        if password_hash is None:
            password_hash = existing.password_hash

    if password_hash is None:
        if not payload.password:
            raise HTTPException(status_code=400, detail="Senha obrigatória para novo usuário")
        password_hash = hash_password(payload.password)

    user = User(
        organization_id=payload.organization_id,
        organization_type=payload.organization_type,
        full_name=payload.full_name,
        email=payload.email.lower().strip(),
        password_hash=password_hash,
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


# Troca de senha — propaga para todos os registros com o mesmo email
@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.core.security import verify_password
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")

    new_hash = hash_password(payload.new_password)
    db.query(User).filter(
        sqlfunc.lower(User.email) == current_user.email.lower()
    ).update({"password_hash": new_hash}, synchronize_session=False)
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



@router.get("/my-organizations")
def list_my_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista todas as organizações do usuário logado, buscando pelo email."""
    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp

    year = datetime.date.today().year

    # Busca todos os registros de usuário com o mesmo email (um por org)
    all_users = db.query(User).filter(
        sqlfunc.lower(User.email) == current_user.email.lower(),
        User.is_active == True,
    ).all()

    result = []
    for u in all_users:
        org_type = u.organization_type.value \
            if hasattr(u.organization_type, 'value') \
            else str(u.organization_type)

        if org_type == 'federation':
            obj = db.query(Federation).filter(Federation.id == u.organization_id).first()
        else:
            obj = db.query(LocalUmp).filter(LocalUmp.id == u.organization_id).first()

        ur = db.query(UserRole).filter(
            UserRole.user_id     == u.id,
            UserRole.fiscal_year == year,
            UserRole.is_active   == True,
        ).first()
        role_str = ur.role.value if ur and hasattr(ur.role, 'value') \
                   else str(ur.role) if ur else 'membro'

        result.append({
            "user_id":           str(u.id),
            "organization_id":   str(u.organization_id),
            "organization_type": org_type,
            "org_name":          obj.name if obj else '',
            "role":              role_str,
            "is_current":        str(u.id) == str(current_user.id),
        })

    return result


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