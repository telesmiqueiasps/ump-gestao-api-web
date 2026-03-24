from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.member import Member, MembershipFee
from app.models.local_ump import LocalUmp
from app.models.enums import MemberType
from app.models.user import User
from app.core.dependencies import get_current_user, require_local_ump

router = APIRouter()


class MemberCreate(BaseModel):
    full_name: str
    member_type: MemberType = MemberType.ativo
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    join_date: Optional[datetime.date] = None


class MemberUpdate(BaseModel):
    full_name: Optional[str] = None
    member_type: Optional[MemberType] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None


class FeeCreate(BaseModel):
    member_id: UUID
    reference_month: datetime.date
    amount: float


# Listar sócios da UMP Local
@router.get("/")
def list_members(
    active_only: bool = True,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    query = db.query(Member).filter(Member.local_ump_id == current_user.organization_id)
    if active_only:
        query = query.filter(Member.is_active == True)
    members = query.order_by(Member.full_name).all()
    return [_to_out(m) for m in members]


# Cadastrar sócio
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_member(
    payload: MemberCreate,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = Member(
        local_ump_id=current_user.organization_id,
        **payload.model_dump()
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _to_out(member)


# Detalhe de um sócio
@router.get("/{member_id}")
def get_member(
    member_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")
    return _to_out(member)


# Atualizar sócio
@router.put("/{member_id}")
def update_member(
    member_id: UUID,
    payload: MemberUpdate,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(member, field, value)
    db.commit()
    db.refresh(member)
    return _to_out(member)


# Desativar sócio
@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_member(
    member_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")
    member.is_active = False
    db.commit()


# Registrar mensalidade
@router.post("/fees", status_code=status.HTTP_201_CREATED)
def register_fee(
    payload: FeeCreate,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == payload.member_id,
        Member.local_ump_id == current_user.organization_id,
        Member.is_active == True,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    fee = MembershipFee(
        member_id=payload.member_id,
        local_ump_id=current_user.organization_id,
        reference_month=payload.reference_month,
        amount=payload.amount,
    )
    db.add(fee)
    db.commit()
    db.refresh(fee)
    return {
        "id": str(fee.id),
        "member_id": str(fee.member_id),
        "reference_month": fee.reference_month.isoformat(),
        "amount": float(fee.amount),
        "paid_at": fee.paid_at.isoformat() if fee.paid_at else None,
    }


# Listar mensalidades de um sócio
@router.get("/{member_id}/fees")
def list_fees(
    member_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    fees = db.query(MembershipFee).filter(
        MembershipFee.member_id == member_id
    ).order_by(MembershipFee.reference_month.desc()).all()

    return [
        {
            "id": str(f.id),
            "reference_month": f.reference_month.isoformat(),
            "amount": float(f.amount),
            "paid_at": f.paid_at.isoformat() if f.paid_at else None,
            "receipt_url": f.receipt_url,
        }
        for f in fees
    ]


def _to_out(m: Member) -> dict:
    return {
        "id": str(m.id),
        "local_ump_id": str(m.local_ump_id),
        "full_name": m.full_name,
        "member_type": m.member_type.value,
        "email": m.email,
        "phone": m.phone,
        "birth_date": m.birth_date.isoformat() if m.birth_date else None,
        "join_date": m.join_date.isoformat() if m.join_date else None,
        "is_active": m.is_active,
    }