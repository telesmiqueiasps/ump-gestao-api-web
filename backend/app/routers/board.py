from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.board import BoardMember
from app.models.user import User, UserRole
from app.models.enums import BoardRole, OrgType
from app.core.dependencies import get_current_user

router = APIRouter()

# Cargos exclusivos de cada tipo de organização
FEDERATION_ONLY = {BoardRole.secretario_executivo, BoardRole.secretario_presbiterial}
LOCAL_ONLY = {BoardRole.conselheiro}


class BoardMemberCreate(BaseModel):
    member_name: str
    role: BoardRole
    fiscal_year: Optional[int] = None
    user_id: Optional[UUID] = None
    contact: Optional[str] = None


class BoardMemberUpdate(BaseModel):
    member_name: Optional[str] = None
    role: Optional[BoardRole] = None
    user_id: Optional[UUID] = None
    contact: Optional[str] = None


def _validate_role_for_org(role: BoardRole, org_type: OrgType):
    if org_type == OrgType.federation and role in LOCAL_ONLY:
        raise HTTPException(status_code=400, detail=f"Cargo '{role.value}' é exclusivo de UMP Local")
    if org_type == OrgType.local_ump and role in FEDERATION_ONLY:
        raise HTTPException(status_code=400, detail=f"Cargo '{role.value}' é exclusivo de Federação")


# Listar diretoria da organização atual
@router.get("/")
def list_board(
    fiscal_year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    year = fiscal_year or datetime.date.today().year
    board = db.query(BoardMember).filter(
        BoardMember.organization_id == current_user.organization_id,
        BoardMember.fiscal_year == year,
        BoardMember.is_active == True,
    ).limit(500).all()
    return [_to_out(b) for b in board]


# Adicionar membro à diretoria
@router.post("/", status_code=status.HTTP_201_CREATED)
def add_board_member(
    payload: BoardMemberCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_role_for_org(payload.role, current_user.organization_type)

    year = payload.fiscal_year or datetime.date.today().year

    # Verificar se o cargo já está ocupado no ano
    existing = db.query(BoardMember).filter(
        BoardMember.organization_id == current_user.organization_id,
        BoardMember.role == payload.role.value,
        BoardMember.fiscal_year == year,
        BoardMember.is_active == True,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Cargo '{payload.role.value}' já está ocupado para o ano {year}"
        )

    board_member = BoardMember(
        organization_id=current_user.organization_id,
        organization_type=current_user.organization_type.value,
        member_name=payload.member_name,
        role=payload.role.value,
        fiscal_year=year,
        user_id=payload.user_id,
        contact=payload.contact,
    )
    db.add(board_member)

    # Se veio user_id, cria o role no sistema para esse usuário
    if payload.user_id:
        existing_role = db.query(UserRole).filter(
            UserRole.user_id == payload.user_id,
            UserRole.role == payload.role.value,
            UserRole.fiscal_year == year,
        ).first()
        if not existing_role:
            user_role = UserRole(
                user_id=payload.user_id,
                role=payload.role.value,
                fiscal_year=year,
            )
            db.add(user_role)

    db.commit()
    db.refresh(board_member)
    return _to_out(board_member)


# Atualizar membro da diretoria
@router.put("/{board_member_id}")
def update_board_member(
    board_member_id: UUID,
    payload: BoardMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = db.query(BoardMember).filter(
        BoardMember.id == board_member_id,
        BoardMember.organization_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Membro não encontrado")

    if payload.role:
        _validate_role_for_org(payload.role, current_user.organization_type)

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(member, field, value)
    db.commit()
    db.refresh(member)
    return _to_out(member)


# Remover membro da diretoria
@router.delete("/{board_member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_board_member(
    board_member_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = db.query(BoardMember).filter(
        BoardMember.id == board_member_id,
        BoardMember.organization_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Membro não encontrado")
    member.is_active = False
    db.commit()


from app.models.activity_secretary import ActivitySecretary


class ActivitySecretaryCreate(BaseModel):
    member_name: str
    activity_name: str
    contact: Optional[str] = None
    fiscal_year: Optional[int] = None


class ActivitySecretaryUpdate(BaseModel):
    member_name: Optional[str] = None
    activity_name: Optional[str] = None
    contact: Optional[str] = None


def _as_out(s: ActivitySecretary) -> dict:
    return {
        "id": str(s.id),
        "organization_id": str(s.organization_id),
        "member_name": s.member_name,
        "activity_name": s.activity_name,
        "contact": s.contact,
        "fiscal_year": s.fiscal_year,
        "is_active": s.is_active,
    }


@router.get("/activity-secretaries/")
def list_activity_secretaries(
    fiscal_year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    year = fiscal_year or datetime.date.today().year
    secs = db.query(ActivitySecretary).filter(
        ActivitySecretary.organization_id == current_user.organization_id,
        ActivitySecretary.fiscal_year == year,
        ActivitySecretary.is_active == True,
    ).order_by(ActivitySecretary.activity_name).all()
    return [_as_out(s) for s in secs]


@router.post("/activity-secretaries/", status_code=status.HTTP_201_CREATED)
def create_activity_secretary(
    payload: ActivitySecretaryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    year = payload.fiscal_year or datetime.date.today().year
    sec = ActivitySecretary(
        organization_id=current_user.organization_id,
        organization_type=current_user.organization_type.value
            if hasattr(current_user.organization_type, 'value')
            else str(current_user.organization_type),
        member_name=payload.member_name,
        activity_name=payload.activity_name,
        contact=payload.contact,
        fiscal_year=year,
    )
    db.add(sec)
    db.commit()
    db.refresh(sec)
    return _as_out(sec)


@router.put("/activity-secretaries/{sec_id}")
def update_activity_secretary(
    sec_id: UUID,
    payload: ActivitySecretaryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sec = db.query(ActivitySecretary).filter(
        ActivitySecretary.id == sec_id,
        ActivitySecretary.organization_id == current_user.organization_id,
    ).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Secretário não encontrado")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(sec, field, value)
    db.commit()
    db.refresh(sec)
    return _as_out(sec)


@router.delete("/activity-secretaries/{sec_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_activity_secretary(
    sec_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sec = db.query(ActivitySecretary).filter(
        ActivitySecretary.id == sec_id,
        ActivitySecretary.organization_id == current_user.organization_id,
    ).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Secretário não encontrado")
    db.delete(sec)
    db.commit()


def _to_out(b: BoardMember) -> dict:
    return {
        "id": str(b.id),
        "organization_id": str(b.organization_id),
        "organization_type": b.organization_type.value,
        "member_name": b.member_name,
        "role": b.role.value,
        "fiscal_year": b.fiscal_year,
        "user_id": str(b.user_id) if b.user_id else None,
        "contact": b.contact,
        "is_active": b.is_active,
    }