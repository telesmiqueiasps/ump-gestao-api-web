from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.member_fees import MemberMonthlyFee, MemberAciContribution
from app.models.member import Member
from app.models.local_ump import LocalUmp
from app.models.finance import FinancialPeriod, FinancialTransaction
from app.models.enums import TransactionType
from app.models.user import User
from app.core.dependencies import require_local_ump
from app.services.storage import upload_file, delete_folder
from app.core.config import get_settings
import re

router = APIRouter()


def _get_period(db, org_id, year):
    return db.query(FinancialPeriod).filter(
        FinancialPeriod.organization_id == org_id,
        FinancialPeriod.fiscal_year == year,
    ).first()


def _create_transaction(db, org_id, period_id, tx_date, tx_type, description, amount, created_by):
    tx = FinancialTransaction(
        period_id=period_id,
        organization_id=org_id,
        transaction_date=tx_date,
        transaction_type=tx_type,
        description=description,
        amount=amount,
        created_by=created_by,
    )
    db.add(tx)
    db.flush()
    return tx


def _delete_receipt_from_b2(receipt_url, settings_obj):
    if not receipt_url:
        return
    bucket_name = settings_obj.b2_bucket_name
    match = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', receipt_url)
    if not match:
        match = re.search(rf'/{re.escape(bucket_name)}/(.+)$', receipt_url)
    if match:
        folder = '/'.join(match.group(1).split('/')[:-1]) + '/'
        delete_folder(folder)


def _delete_linked_transaction(db, transaction_id, settings_obj):
    tx = db.query(FinancialTransaction).filter(
        FinancialTransaction.id == transaction_id
    ).first()
    if tx:
        _delete_receipt_from_b2(tx.receipt_url, settings_obj)
        db.delete(tx)


# ── Configurações de valores ───────────────────────────────────

class LocalFeesConfig(BaseModel):
    monthly_fee_value: Optional[float] = None
    aci_year_value: Optional[float] = None


@router.get("/config")
def get_fees_config(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")
    return {
        "monthly_fee_value": float(local.monthly_fee_value or 0),
        "aci_year_value": float(local.aci_year_value or 0),
    }


@router.put("/config")
def update_fees_config(
    payload: LocalFeesConfig,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")
    if payload.monthly_fee_value is not None:
        local.monthly_fee_value = payload.monthly_fee_value
    if payload.aci_year_value is not None:
        local.aci_year_value = payload.aci_year_value
    db.commit()
    return {
        "monthly_fee_value": float(local.monthly_fee_value or 0),
        "aci_year_value": float(local.aci_year_value or 0),
    }


# ── Mensalidades ──────────────────────────────────────────────

class MonthlyFeeRegister(BaseModel):
    member_id: UUID
    reference_month: datetime.date
    amount: float
    paid_at: datetime.date
    description: Optional[str] = None


@router.get("/monthly/{member_id}")
def list_monthly_fees(
    member_id: UUID,
    year: Optional[int] = None,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    year = year or datetime.date.today().year
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    months = []
    labels = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
              "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    for m in range(1, 13):
        ref = datetime.date(year, m, 1)
        fee = db.query(MemberMonthlyFee).filter(
            MemberMonthlyFee.member_id == member_id,
            MemberMonthlyFee.reference_month == ref,
        ).first()
        months.append({
            "month_num": m,
            "month_label": labels[m - 1],
            "reference_month": ref.isoformat(),
            "id": str(fee.id) if fee else None,
            "amount": float(fee.amount) if fee else None,
            "paid_at": fee.paid_at.isoformat() if fee and fee.paid_at else None,
            "is_paid": fee.is_paid if fee else False,
            "receipt_url": fee.receipt_url if fee else None,
            "transaction_id": str(fee.transaction_id) if fee and fee.transaction_id else None,
        })
    return months


@router.post("/monthly", status_code=status.HTTP_201_CREATED)
def register_monthly_fee(
    payload: MonthlyFeeRegister,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == payload.member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    existing = db.query(MemberMonthlyFee).filter(
        MemberMonthlyFee.member_id == payload.member_id,
        MemberMonthlyFee.reference_month == payload.reference_month,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Mensalidade já registrada para este mês")

    year = payload.paid_at.year
    period = _get_period(db, current_user.organization_id, year)
    if not period:
        raise HTTPException(
            status_code=404,
            detail=f"Período financeiro {year} não encontrado. Crie o período primeiro no módulo Financeiro."
        )
    if period.is_closed:
        raise HTTPException(status_code=400, detail="Período financeiro encerrado")

    desc = payload.description or f"Mensalidade {member.full_name} - {payload.reference_month.strftime('%m/%Y')}"
    tx = _create_transaction(
        db,
        org_id=current_user.organization_id,
        period_id=period.id,
        tx_date=payload.paid_at,
        tx_type=TransactionType.outras_receitas,
        description=desc,
        amount=payload.amount,
        created_by=current_user.id,
    )

    fee = MemberMonthlyFee(
        member_id=payload.member_id,
        local_ump_id=current_user.organization_id,
        reference_month=payload.reference_month,
        amount=payload.amount,
        paid_at=payload.paid_at,
        is_paid=True,
        transaction_id=tx.id,
    )
    db.add(fee)
    db.commit()
    db.refresh(fee)

    return {
        "id": str(fee.id),
        "reference_month": fee.reference_month.isoformat(),
        "amount": float(fee.amount),
        "paid_at": fee.paid_at.isoformat(),
        "is_paid": fee.is_paid,
        "transaction_id": str(fee.transaction_id),
    }


@router.post("/monthly/{fee_id}/receipt")
async def upload_monthly_receipt(
    fee_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    fee = db.query(MemberMonthlyFee).filter(
        MemberMonthlyFee.id == fee_id,
        MemberMonthlyFee.local_ump_id == current_user.organization_id,
    ).first()
    if not fee:
        raise HTTPException(status_code=404, detail="Mensalidade não encontrada")

    allowed = ["image/png", "image/jpeg", "application/pdf"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Formato inválido. Use PNG, JPG ou PDF.")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Máx 10MB.")

    key = f"receipts/members/{fee.member_id}/monthly/{fee_id}/{file.filename}"
    url = upload_file(contents, key, file.content_type)

    fee.receipt_url = url
    if fee.transaction_id:
        tx = db.query(FinancialTransaction).filter(
            FinancialTransaction.id == fee.transaction_id
        ).first()
        if tx:
            tx.receipt_url = url

    db.commit()
    return {"receipt_url": url}


@router.delete("/monthly/{fee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monthly_fee(
    fee_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    settings_obj = get_settings()
    fee = db.query(MemberMonthlyFee).filter(
        MemberMonthlyFee.id == fee_id,
        MemberMonthlyFee.local_ump_id == current_user.organization_id,
    ).first()
    if not fee:
        raise HTTPException(status_code=404, detail="Mensalidade não encontrada")

    receipt_url = fee.receipt_url
    transaction_id = fee.transaction_id

    db.delete(fee)
    db.flush()

    _delete_receipt_from_b2(receipt_url, settings_obj)
    if transaction_id:
        _delete_linked_transaction(db, transaction_id, settings_obj)

    db.commit()


# ── ACI ───────────────────────────────────────────────────────

class AciContributionCreate(BaseModel):
    member_id: UUID
    fiscal_year: int
    payment_date: datetime.date
    amount: float
    description: Optional[str] = None


@router.get("/aci/{member_id}")
def list_aci_contributions(
    member_id: UUID,
    year: Optional[int] = None,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    year = year or datetime.date.today().year
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    aci_year_value = float(local.aci_year_value or 0)

    contributions = db.query(MemberAciContribution).filter(
        MemberAciContribution.member_id == member_id,
        MemberAciContribution.fiscal_year == year,
    ).order_by(MemberAciContribution.payment_date).all()

    total_paid = sum(float(c.amount) for c in contributions)
    remaining = max(0, aci_year_value - total_paid)
    progress = (total_paid / aci_year_value * 100) if aci_year_value > 0 else 0

    return {
        "aci_year_value": aci_year_value,
        "total_paid": total_paid,
        "remaining": remaining,
        "is_complete": total_paid >= aci_year_value and aci_year_value > 0,
        "progress_percent": round(progress, 1),
        "contributions": [
            {
                "id": str(c.id),
                "fiscal_year": c.fiscal_year,
                "payment_date": c.payment_date.isoformat(),
                "amount": float(c.amount),
                "receipt_url": c.receipt_url,
                "transaction_id": str(c.transaction_id) if c.transaction_id else None,
            }
            for c in contributions
        ]
    }


@router.post("/aci", status_code=status.HTTP_201_CREATED)
def register_aci_contribution(
    payload: AciContributionCreate,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == payload.member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    period = _get_period(db, current_user.organization_id, payload.payment_date.year)
    if not period:
        raise HTTPException(
            status_code=404,
            detail=f"Período financeiro {payload.payment_date.year} não encontrado."
        )
    if period.is_closed:
        raise HTTPException(status_code=400, detail="Período financeiro encerrado")

    desc = payload.description or f"ACI {payload.fiscal_year} - {member.full_name}"
    tx = _create_transaction(
        db,
        org_id=current_user.organization_id,
        period_id=period.id,
        tx_date=payload.payment_date,
        tx_type=TransactionType.aci_recebida,
        description=desc,
        amount=payload.amount,
        created_by=current_user.id,
    )

    contribution = MemberAciContribution(
        member_id=payload.member_id,
        local_ump_id=current_user.organization_id,
        fiscal_year=payload.fiscal_year,
        payment_date=payload.payment_date,
        amount=payload.amount,
        transaction_id=tx.id,
    )
    db.add(contribution)
    db.commit()
    db.refresh(contribution)

    return {
        "id": str(contribution.id),
        "fiscal_year": contribution.fiscal_year,
        "payment_date": contribution.payment_date.isoformat(),
        "amount": float(contribution.amount),
        "transaction_id": str(contribution.transaction_id),
    }


@router.post("/aci/{contribution_id}/receipt")
async def upload_aci_receipt(
    contribution_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    contribution = db.query(MemberAciContribution).filter(
        MemberAciContribution.id == contribution_id,
        MemberAciContribution.local_ump_id == current_user.organization_id,
    ).first()
    if not contribution:
        raise HTTPException(status_code=404, detail="Contribuição não encontrada")

    allowed = ["image/png", "image/jpeg", "application/pdf"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Formato inválido. Use PNG, JPG ou PDF.")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Máx 10MB.")

    key = f"receipts/members/{contribution.member_id}/aci/{contribution_id}/{file.filename}"
    url = upload_file(contents, key, file.content_type)

    contribution.receipt_url = url
    if contribution.transaction_id:
        tx = db.query(FinancialTransaction).filter(
            FinancialTransaction.id == contribution.transaction_id
        ).first()
        if tx:
            tx.receipt_url = url

    db.commit()
    return {"receipt_url": url}


@router.delete("/aci/{contribution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_aci_contribution(
    contribution_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    settings_obj = get_settings()
    contribution = db.query(MemberAciContribution).filter(
        MemberAciContribution.id == contribution_id,
        MemberAciContribution.local_ump_id == current_user.organization_id,
    ).first()
    if not contribution:
        raise HTTPException(status_code=404, detail="Contribuição não encontrada")

    receipt_url = contribution.receipt_url
    transaction_id = contribution.transaction_id

    db.delete(contribution)
    db.flush()

    _delete_receipt_from_b2(receipt_url, settings_obj)
    if transaction_id:
        _delete_linked_transaction(db, transaction_id, settings_obj)

    db.commit()


# ── Resumo ACI da local (dashboard) ──────────────────────────

@router.get("/aci-summary")
def get_aci_summary(
    year: Optional[int] = None,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    year = year or datetime.date.today().year

    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    aci_year_value = float(local.aci_year_value or 0)

    total_members = db.query(Member).filter(
        Member.local_ump_id == current_user.organization_id,
        Member.is_active == True,
    ).count()

    total_to_collect = aci_year_value * total_members

    total_collected = float(db.query(
        func.coalesce(func.sum(MemberAciContribution.amount), 0)
    ).filter(
        MemberAciContribution.local_ump_id == current_user.organization_id,
        MemberAciContribution.fiscal_year == year,
    ).scalar())

    remaining = max(0, total_to_collect - total_collected)
    progress = (total_collected / total_to_collect * 100) if total_to_collect > 0 else 0

    return {
        "year": year,
        "aci_year_value": aci_year_value,
        "total_members": total_members,
        "total_to_collect": total_to_collect,
        "total_collected": total_collected,
        "remaining": remaining,
        "progress_percent": round(progress, 1),
        "is_complete": total_collected >= total_to_collect and total_to_collect > 0,
    }
