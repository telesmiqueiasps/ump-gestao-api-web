from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import datetime
import re
from app.db.session import get_db
from app.models.finance import FinancialPeriod, FinancialTransaction
from app.models.enums import TransactionType, OrgType
from app.models.user import User
from app.core.dependencies import get_current_user
from app.core.config import get_settings
from app.services.storage import upload_file, get_presigned_url, delete_file

settings = get_settings()

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


def _month_label(month: int) -> str:
    labels = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
              "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    return labels[month - 1]


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


# Lançamentos agrupados por mês com saldos acumulados
@router.get("/transactions/by-month")
def get_transactions_by_month(
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

    # Agrupa transações por mês
    tx_by_month: dict = {}
    for t in transactions:
        month_key = t.transaction_date.strftime("%Y-%m")
        tx_by_month.setdefault(month_key, []).append(t)

    # Sempre gera os 12 meses, com ou sem lançamentos
    running_balance = float(period.initial_balance)
    months_list = []
    for month_num in range(1, 13):
        month_key = f"{year}-{str(month_num).zfill(2)}"
        txs = tx_by_month.get(month_key, [])

        total_in  = sum(float(t.amount) for t in txs if t.transaction_type in INCOME_TYPES)
        total_out = sum(float(t.amount) for t in txs if t.transaction_type in EXPENSE_TYPES)

        opening = running_balance
        running_balance += total_in - total_out

        months_list.append({
            "month_key": month_key,
            "month_num": month_num,
            "month_label": _month_label(month_num),
            "transactions": [_transaction_out(t) for t in txs],
            "total_in": total_in,
            "total_out": total_out,
            "opening_balance": opening,
            "closing_balance": running_balance,
            "has_transactions": len(txs) > 0,
        })

    return {
        "period": _period_out(period, db),
        "months": months_list,
        "total_in": sum(m["total_in"] for m in months_list),
        "total_out": sum(m["total_out"] for m in months_list),
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

    # Exclui comprovante do Backblaze B2 se existir
    if transaction.receipt_url:
        import logging
        logger = logging.getLogger(__name__)

        bucket_name = settings.b2_bucket_name
        stored_url = transaction.receipt_url

        logger.info(f"Tentando excluir comprovante. URL: {stored_url}")
        logger.info(f"Bucket name: {bucket_name}")

        key = None

        # Formato 1: https://f005.backblazeb2.com/file/BUCKET/KEY
        match1 = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', stored_url)
        if match1:
            key = match1.group(1)
            logger.info(f"Key extraída (formato 1): {key}")

        # Formato 2: https://s3.us-east-005.backblazeb2.com/BUCKET/KEY
        if not key:
            match2 = re.search(rf'/{re.escape(bucket_name)}/(.+)$', stored_url)
            if match2:
                key = match2.group(1)
                logger.info(f"Key extraída (formato 2): {key}")

        # Se não conseguiu extrair, usa a URL inteira como key
        if not key:
            key = stored_url
            logger.info(f"Usando URL completa como key: {key}")

        result = delete_file(key)
        logger.info(f"Resultado da exclusão no B2: {result}")

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


# Gerar pre-signed URL para comprovante de uma transação
@router.get("/transactions/{transaction_id}/receipt-url")
def get_receipt_url(
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
    if not transaction.receipt_url:
        raise HTTPException(status_code=404, detail="Comprovante não encontrado")

    # Extrai a key do arquivo da URL armazenada.
    # Formato esperado: https://f005.backblazeb2.com/file/BUCKET/KEY
    stored_url = transaction.receipt_url
    match = re.search(rf'/file/{re.escape(settings.b2_bucket_name)}/(.+)$', stored_url)
    key = match.group(1) if match else stored_url

    presigned = get_presigned_url(key, expires_in=3600)
    return {"url": presigned, "expires_in": 3600}


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