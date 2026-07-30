from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import extract
from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.member import Member, MembershipFee
from app.models.local_ump import LocalUmp
from app.models.enums import MemberType
from app.models.user import User
from app.core.dependencies import get_current_user, require_local_or_federation

router = APIRouter()


class MemberCreate(BaseModel):
    full_name: str
    member_type: MemberType = MemberType.ativo
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    join_date: Optional[datetime.date] = None
    is_board_member: Optional[bool] = False
    local_society: Optional[str] = None


class MemberUpdate(BaseModel):
    full_name: Optional[str] = None
    member_type: Optional[MemberType] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    is_board_member: Optional[bool] = None
    local_society: Optional[str] = None


class FeeCreate(BaseModel):
    member_id: UUID
    reference_month: datetime.date
    amount: float


# Listar sócios da UMP Local / Delegados da Federação
@router.get("/")
def list_members(
    active_only: bool = True,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    # Check/Sync board members if federation
    if current_user.organization_type == 'federation':
        shadow_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
        if not shadow_ump:
            shadow_ump = LocalUmp(
                id=current_user.organization_id,
                federation_id=current_user.organization_id,
                name="Eleições da Federação",
                fiscal_year=2026,
                is_active=True
            )
            db.add(shadow_ump)
            db.flush()

        from app.models.board import BoardMember
        import datetime
        current_year = datetime.date.today().year
        board_members = db.query(BoardMember).filter(
            BoardMember.organization_id == current_user.organization_id,
            BoardMember.fiscal_year == current_year,
            BoardMember.is_active == True,
            BoardMember.role != 'secretario_presbiterial'
        ).all()

        active_board_names = {bm.member_name for bm in board_members}

        # Find all delegates from "Diretoria"
        diretoria_members = db.query(Member).filter(
            Member.local_ump_id == current_user.organization_id,
            Member.local_society == "Diretoria"
        ).all()

        has_changes = False
        for dm in diretoria_members:
            if dm.full_name not in active_board_names and dm.is_active:
                dm.is_active = False
                has_changes = True

        for bm in board_members:
            existing = db.query(Member).filter(
                Member.local_ump_id == current_user.organization_id,
                Member.full_name == bm.member_name
            ).first()
            if not existing:
                new_m = Member(
                    local_ump_id=current_user.organization_id,
                    full_name=bm.member_name,
                    local_society="Diretoria",
                    member_type=MemberType.ativo,
                    is_active=True,
                    join_date=datetime.date.today()
                )
                db.add(new_m)
                has_changes = True
            elif not existing.is_active:
                existing.is_active = True
                has_changes = True

        if has_changes:
            db.commit()

    query = db.query(Member).filter(Member.local_ump_id == current_user.organization_id)
    if active_only:
        query = query.filter(Member.is_active == True)
    members = query.order_by(Member.full_name).limit(500).all()
    return [_to_out(m) for m in members]


# Cadastrar sócio
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_member(
    payload: MemberCreate,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    # If federation, create shadow local_ump if not exists
    if current_user.organization_type == 'federation':
        shadow_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
        if not shadow_ump:
            shadow_ump = LocalUmp(
                id=current_user.organization_id,
                federation_id=current_user.organization_id,
                name="Eleições da Federação",
                fiscal_year=2026,
                is_active=True
            )
            db.add(shadow_ump)
            db.flush()

    member = Member(
        local_ump_id=current_user.organization_id,
        **payload.model_dump()
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _to_out(member)


@router.get("/birthdays")
def get_birthdays(
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    current_month = datetime.date.today().month
    current_day   = datetime.date.today().day

    members = db.query(Member).filter(
        Member.local_ump_id == current_user.organization_id,
        Member.is_active == True,
        Member.birth_date.isnot(None),
        extract('month', Member.birth_date) == current_month,
    ).order_by(extract('day', Member.birth_date)).all()

    today = datetime.date.today()
    result = []
    for m in members:
        birth_day      = m.birth_date.day
        age            = today.year - m.birth_date.year
        is_today       = birth_day == current_day
        already_passed = birth_day < current_day

        result.append({
            "id":            str(m.id),
            "full_name":     m.full_name,
            "birth_date":    m.birth_date.isoformat(),
            "birth_day":     birth_day,
            "age":           age,
            "is_today":      is_today,
            "already_passed": already_passed,
        })

    return result


# Detalhe de um sócio
@router.get("/{member_id}")
def get_member(
    member_id: UUID,
    current_user: User = Depends(require_local_or_federation),
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
    current_user: User = Depends(require_local_or_federation),
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
    current_user: User = Depends(require_local_or_federation),
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
    current_user: User = Depends(require_local_or_federation),
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
    current_user: User = Depends(require_local_or_federation),
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
    ).order_by(MembershipFee.reference_month.desc()).limit(500).all()

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
        "is_board_member": m.is_board_member or False,
        "local_society": m.local_society,
    }