from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.finance import FinancialPeriod, FinancialTransaction
from app.models.enums import TransactionType, OrgType
from app.models.user import User
from app.core.dependencies import get_current_user
from app.services.storage import upload_file

router = APIRouter()


class PeriodCreate(BaseModel):
    fiscal_year: int
    initial_balance: float = 0.0


class TransactionCreate(BaseModel):
    transaction_date: datetime.date
    transaction_type: TransactionType
    description: str
    amount: float


class TransactionUpdate(BaseModel):
    transaction_date: Optional[datetime.date] = None
    transaction_type: Optional[TransactionType] = None
    description: Optional[str] = None
    amount: Optional[float] = None


INCOME_TYPES = {TransactionType.outras_receitas, TransactionType.aci_recebida}
EXPENSE_TYPES = {TransactionType.outras_despesas, TransactionType.aci_enviada}


def _get_period(db, org_id, org_type, year):
    return db.query(FinancialPeriod).filter(
        FinancialPeriod.organization_id == org_id,
        FinancialPeriod.fiscal_year == year,
    ).first()


def _calc_balance(db, period_id, initial_balance):
    row = db.query(
        func.coalesce(func.sum(case(
            (FinancialTransaction.transaction_type.in_(INCOME_TYPES), FinancialTransaction.amount),
            else_=0
        )), 0).label("total_in"),
        func.coalesce(func.sum(case(
            (FinancialTransaction.transaction_type.in_(EXPENSE_TYPES), FinancialTransaction.amount),
            else_=0
        )), 0).label("total_out"),
    ).filter(FinancialTransaction.period_id == period_id).one()
    return float(initial_balance) + float(row.total_in) - float(row.total_out)


# Criar ou abrir período financeiro
@router.post("/periods", status_code=status.HTTP_201_CREATED)
def create_period(
    payload: PeriodCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = _get_period(db, current_user.organization_id, current_user.organization_type, payload.fiscal_year)
    if existing:
        raise HTTPException(status_code=400, detail="Período já existe para este ano")

    period = FinancialPeriod(
        organization_id=current_user.organization_id,
        organization_type=current_user.organization_type,
        fiscal_year=payload.fiscal_year,
        initial_balance=payload.initial_balance,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return _period_out(period, db)


# Buscar período atual
@router.get("/periods/current")
def get_current_period(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    year = datetime.date.today().year
    period = _get_period(db, current_user.organization_id, current_user.organization_type, year)
    if not period:
        raise HTTPException(status_code=404, detail="Nenhum período aberto para o ano atual")
    return _period_out(period, db)


# Listar todos os períodos da organização
@router.get("/periods")
def list_periods(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    periods = db.query(FinancialPeriod).filter(
        FinancialPeriod.organization_id == current_user.organization_id,
    ).order_by(FinancialPeriod.fiscal_year.desc()).limit(500).all()
    return [_period_out(p, db) for p in periods]


# Lançar transação
@router.post("/transactions", status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="O valor deve ser maior que zero")

    year = payload.transaction_date.year
    period = _get_period(db, current_user.organization_id, current_user.organization_type, year)
    if not period:
        raise HTTPException(status_code=404, detail=f"Período financeiro para {year} não encontrado. Crie o período primeiro.")
    if period.is_closed:
        raise HTTPException(status_code=400, detail="Este período financeiro está encerrado")

    transaction = FinancialTransaction(
        period_id=period.id,
        organization_id=current_user.organization_id,
        transaction_date=payload.transaction_date,
        transaction_type=payload.transaction_type,
        description=payload.description,
        amount=payload.amount,
        created_by=current_user.id,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return _transaction_out(transaction)


# Upload de comprovante para uma transação
@router.post("/transactions/{transaction_id}/receipt")
async def upload_receipt(
    transaction_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction = db.query(FinancialTransaction).filter(
        FinancialTransaction.id == transaction_id,
        FinancialTransaction.organization_id == current_user.organization_id,
    ).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    allowed = ["image/png", "image/jpeg", "application/pdf"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Formato inválido. Use PNG, JPG ou PDF.")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Máximo 10MB.")

    key = f"receipts/{current_user.organization_id}/{transaction_id}/{file.filename}"
    url = upload_file(contents, key, file.content_type)
    transaction.receipt_url = url
    db.commit()
    db.refresh(transaction)
    return _transaction_out(transaction)


# Listar transações do período atual
@router.get("/transactions")
def list_transactions(
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    year = year or datetime.date.today().year
    period = _get_period(db, current_user.organization_id, current_user.organization_type, year)
    if not period:
        raise HTTPException(status_code=404, detail="Período não encontrado")

    transactions = db.query(FinancialTransaction).filter(
        FinancialTransaction.period_id == period.id,
    ).order_by(FinancialTransaction.transaction_date).limit(500).all()

    return {
        "period": _period_out(period, db),
        "transactions": [_transaction_out(t) for t in transactions],
    }


# Atualizar transação
@router.put("/transactions/{transaction_id}")
def update_transaction(
    transaction_id: UUID,
    payload: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction = db.query(FinancialTransaction).filter(
        FinancialTransaction.id == transaction_id,
        FinancialTransaction.organization_id == current_user.organization_id,
    ).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    period = db.query(FinancialPeriod).filter(FinancialPeriod.id == transaction.period_id).first()
    if period and period.is_closed:
        raise HTTPException(status_code=400, detail="Período encerrado — lançamento não pode ser editado")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(transaction, field, value)
    db.commit()
    db.refresh(transaction)
    return _transaction_out(transaction)


# Excluir transação
@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction = db.query(FinancialTransaction).filter(
        FinancialTransaction.id == transaction_id,
        FinancialTransaction.organization_id == current_user.organization_id,
    ).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    period = db.query(FinancialPeriod).filter(FinancialPeriod.id == transaction.period_id).first()
    if period and period.is_closed:
        raise HTTPException(status_code=400, detail="Período encerrado — lançamento não pode ser excluído")

    db.delete(transaction)
    db.commit()


# Encerrar período
@router.post("/periods/{period_id}/close")
def close_period(
    period_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    period = db.query(FinancialPeriod).filter(
        FinancialPeriod.id == period_id,
        FinancialPeriod.organization_id == current_user.organization_id,
    ).first()
    if not period:
        raise HTTPException(status_code=404, detail="Período não encontrado")
    if period.is_closed:
        raise HTTPException(status_code=400, detail="Período já encerrado")

    period.is_closed = True
    period.closed_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return {"detail": "Período encerrado com sucesso", "final_balance": _calc_balance(db, period.id, period.initial_balance)}


def _period_out(p: FinancialPeriod, db) -> dict:
    final_balance = _calc_balance(db, p.id, p.initial_balance)
    return {
        "id": str(p.id),
        "organization_id": str(p.organization_id),
        "fiscal_year": p.fiscal_year,
        "initial_balance": float(p.initial_balance),
        "final_balance": final_balance,
        "is_closed": p.is_closed,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
    }


def _transaction_out(t: FinancialTransaction) -> dict:
    return {
        "id": str(t.id),
        "period_id": str(t.period_id),
        "transaction_date": t.transaction_date.isoformat(),
        "transaction_type": t.transaction_type.value,
        "description": t.description,
        "amount": float(t.amount),
        "receipt_url": t.receipt_url,
        "created_by": str(t.created_by),
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }