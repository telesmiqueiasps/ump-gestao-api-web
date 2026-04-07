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
    if period.is_locked:
        raise HTTPException(status_code=400, detail="Período bloqueado — relatório assinado pendente. Solicite desbloqueio ao Tesoureiro.")
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
    if period and period.is_locked:
        raise HTTPException(status_code=400, detail="Período bloqueado — relatório assinado pendente.")
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
    import re
    from app.services.storage import delete_file, delete_folder
    from app.core.config import get_settings
    settings_obj = get_settings()

    transaction = db.query(FinancialTransaction).filter(
        FinancialTransaction.id == transaction_id,
        FinancialTransaction.organization_id == current_user.organization_id,
    ).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    period = db.query(FinancialPeriod).filter(
        FinancialPeriod.id == transaction.period_id
    ).first()
    if period and period.is_locked:
        raise HTTPException(status_code=400, detail="Período bloqueado — relatório assinado pendente.")
    if period and period.is_closed:
        raise HTTPException(status_code=400, detail="Período encerrado — lançamento não pode ser excluído")

    # Captura receipt_url antes de deletar
    receipt_url = str(transaction.receipt_url) if transaction.receipt_url else None

    # Nulifica referências em member_monthly_fees se existir
    try:
        from app.models.member_fees import MemberMonthlyFee, MemberAciContribution

        # Mensalidades — nulifica referência e marca como não paga
        db.query(MemberMonthlyFee).filter(
            MemberMonthlyFee.transaction_id == transaction_id
        ).update({"transaction_id": None, "is_paid": False, "paid_at": None}, synchronize_session=False)

        # ACI — exclui a contribuição vinculada completamente
        aci_contribs = db.query(MemberAciContribution).filter(
            MemberAciContribution.transaction_id == transaction_id
        ).all()
        for contrib in aci_contribs:
            if contrib.receipt_url:
                try:
                    bucket_name = settings_obj.b2_bucket_name
                    match = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', contrib.receipt_url)
                    if not match:
                        match = re.search(rf'/{re.escape(bucket_name)}/(.+)$', contrib.receipt_url)
                    if match:
                        folder = '/'.join(match.group(1).split('/')[:-1]) + '/'
                        delete_folder(folder)
                except Exception:
                    pass
            db.delete(contrib)

    except Exception:
        pass  # Tabelas podem não existir em ambientes antigos

    # Deleta o lançamento
    db.delete(transaction)
    db.commit()

    # Exclui comprovante do B2 se existir
    if receipt_url:
        bucket_name = settings_obj.b2_bucket_name
        key = None
        match1 = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', receipt_url)
        if match1:
            key = match1.group(1)
        if not key:
            match2 = re.search(rf'/{re.escape(bucket_name)}/(.+)$', receipt_url)
            if match2:
                key = match2.group(1)
        if key:
            folder_prefix = '/'.join(key.split('/')[:-1]) + '/'
            delete_folder(folder_prefix)


# Excluir todos os comprovantes de um ano
@router.delete("/receipts/year/{year}", status_code=status.HTTP_200_OK)
def delete_receipts_by_year(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import re
    from app.services.storage import delete_folder
    from app.core.config import get_settings
    settings_obj = get_settings()
    bucket_name = settings_obj.b2_bucket_name

    period = _get_period(db, current_user.organization_id, current_user.organization_type, year)
    if not period:
        raise HTTPException(status_code=404, detail=f"Período financeiro {year} não encontrado")

    transactions = db.query(FinancialTransaction).filter(
        FinancialTransaction.period_id == period.id,
        FinancialTransaction.receipt_url.isnot(None),
    ).all()

    deleted_count = 0
    failed_count = 0

    for transaction in transactions:
        receipt_url = str(transaction.receipt_url)

        key = None
        match1 = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', receipt_url)
        if match1:
            key = match1.group(1)
        if not key:
            match2 = re.search(rf'/{re.escape(bucket_name)}/(.+)$', receipt_url)
            if match2:
                key = match2.group(1)

        if key:
            folder_prefix = '/'.join(key.split('/')[:-1]) + '/'
            success = delete_folder(folder_prefix)
            if success:
                transaction.receipt_url = None
                deleted_count += 1
            else:
                failed_count += 1

    db.commit()

    return {
        "year": year,
        "deleted": deleted_count,
        "failed": failed_count,
        "message": f"{deleted_count} comprovante(s) excluído(s) com sucesso."
    }


# Encerrar período
@router.post("/periods/{period_id}/close")
def close_period(
    period_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import datetime as dt
    period = db.query(FinancialPeriod).filter(
        FinancialPeriod.id == period_id,
        FinancialPeriod.organization_id == current_user.organization_id,
    ).first()
    if not period:
        raise HTTPException(status_code=404, detail="Período não encontrado")
    if period.is_closed:
        raise HTTPException(status_code=400, detail="Período já encerrado")

    # Busca dados necessários para os PDFs
    from app.models.board import BoardMember
    from app.models.local_ump import LocalUmp
    from app.models.federation import Federation
    from app.services.storage import upload_file, _get_client, get_presigned_url
    from app.services.pdf_generator import generate_financial_report, generate_receipts_report
    from app.core.config import get_settings
    import re

    settings_obj = get_settings()

    # Dados da organização
    if current_user.organization_type.value == 'federation':
        org_obj = db.query(Federation).filter(
            Federation.id == current_user.organization_id
        ).first()
        org_data = {
            "id": str(org_obj.id),
            "name": org_obj.name,
            "presbytery_name": org_obj.presbytery_name,
            "synodal_name": getattr(org_obj, 'synodal_name', None),
            "logo_url": org_obj.logo_url,
            "theme_color": getattr(org_obj, 'theme_color', '#1a2a6c') or '#1a2a6c',
            "society_type": getattr(org_obj, 'society_type', 'UMP') or 'UMP',
            "organization_type": "federation",
        }
    else:
        org_obj = db.query(LocalUmp).filter(
            LocalUmp.id == current_user.organization_id
        ).first()
        org_data = {
            "id": str(org_obj.id),
            "name": org_obj.name,
            "presbytery_name": org_obj.presbytery_name,
            "church_name": org_obj.church_name,
            "pastor_name": org_obj.pastor_name,
            "logo_url": org_obj.logo_url,
            "theme_color": getattr(org_obj, 'theme_color', '#1a2a6c') or '#1a2a6c',
            "society_type": getattr(org_obj, 'society_type', 'UMP') or 'UMP',
            "organization_type": "local_ump",
        }

    # Diretoria
    board_list = db.query(BoardMember).filter(
        BoardMember.organization_id == current_user.organization_id,
        BoardMember.fiscal_year == period.fiscal_year,
        BoardMember.is_active == True,
    ).all()
    board_data = [{"role": b.role.value, "member_name": b.member_name} for b in board_list]

    # Lançamentos por mês
    transactions = db.query(FinancialTransaction).filter(
        FinancialTransaction.period_id == period.id,
    ).order_by(FinancialTransaction.transaction_date).all()

    INCOME_TYPES = {"outras_receitas", "aci_recebida"}
    tx_by_month = {}
    for t in transactions:
        mk = t.transaction_date.month
        if mk not in tx_by_month:
            tx_by_month[mk] = []
        tx_by_month[mk].append(t)

    running = float(period.initial_balance)
    months_data = []
    total_in_all = 0
    total_out_all = 0
    for m in range(1, 13):
        txs = tx_by_month.get(m, [])
        tin  = sum(float(t.amount) for t in txs if t.transaction_type.value in INCOME_TYPES)
        tout = sum(float(t.amount) for t in txs if t.transaction_type.value not in INCOME_TYPES)
        opening = running
        running += tin - tout
        total_in_all += tin
        total_out_all += tout
        months_data.append({
            "month_num": m,
            "month_label": ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
                            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"][m-1],
            "transactions": [
                {
                    "id": str(t.id),
                    "transaction_date": t.transaction_date.isoformat(),
                    "transaction_type": t.transaction_type.value,
                    "description": t.description,
                    "amount": float(t.amount),
                    "receipt_url": t.receipt_url,
                }
                for t in txs
            ],
            "total_in": tin,
            "total_out": tout,
            "opening_balance": opening,
            "closing_balance": running,
            "has_transactions": len(txs) > 0,
        })

    period_dict = {
        "fiscal_year": period.fiscal_year,
        "initial_balance": float(period.initial_balance or 0),
        "final_balance": running,
    }
    import logging as _logging
    _logging.getLogger(__name__).info(
        f"Period dict: initial={float(period.initial_balance or 0)}, final={running}"
    )

    # Baixa logo da organização
    logo_bytes = None
    logo_ct = None
    b2_client = _get_client()
    bucket_name = settings_obj.b2_bucket_name
    if org_data.get('logo_url'):
        match = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', org_data['logo_url'])
        if not match:
            match = re.search(rf'/{re.escape(bucket_name)}/(.+)$', org_data['logo_url'])
        if match:
            try:
                resp = b2_client.get_object(Bucket=bucket_name, Key=match.group(1))
                logo_bytes = resp['Body'].read()
                logo_ct = resp.get('ContentType', 'image/png')
            except:
                pass

    theme_color = org_data.get('theme_color', '#1a2a6c')

    # ── Gera relatório financeiro ──
    fin_pdf_bytes = generate_financial_report(
        org_data=org_data,
        period_data=period_dict,
        months_data=months_data,
        board_data=board_data,
        logo_bytes=logo_bytes,
        logo_content_type=logo_ct,
        theme_color=theme_color,
    )

    # ── Gera relatório de comprovantes ──
    rec_pdf_bytes = generate_receipts_report(
        org_data=org_data,
        period_data=period_dict,
        months_data=months_data,
        b2_client=b2_client,
        bucket_name=bucket_name,
        theme_color=theme_color,
        board_data=board_data,
        logo_bytes=logo_bytes,
    )

    # ── Faz upload dos PDFs no B2 ──
    org_id = str(current_user.organization_id)
    year = period.fiscal_year

    fin_key = f"reports/{org_id}/{year}/relatorio_financeiro_{year}.pdf"
    rec_key = f"reports/{org_id}/{year}/relatorio_comprovantes_{year}.pdf"

    fin_url = upload_file(fin_pdf_bytes, fin_key, 'application/pdf')
    rec_url = upload_file(rec_pdf_bytes, rec_key, 'application/pdf')

    # ── Encerra o período ──
    period.is_closed = True
    period.closed_at = dt.datetime.now(dt.timezone.utc)
    period.report_url = fin_url
    period.receipts_report_url = rec_url
    db.commit()

    return {
        "detail": "Período encerrado com sucesso",
        "final_balance": running,
        "report_url": fin_url,
        "receipts_report_url": rec_url,
    }


# Gerar pre-signed URLs dos relatórios
@router.get("/periods/{period_id}/report-urls")
def get_report_urls(
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
    if not period.is_closed:
        raise HTTPException(status_code=400, detail="Período não encerrado")

    from app.services.storage import get_presigned_url, _get_client
    from app.core.config import get_settings
    import re
    settings_obj = get_settings()
    bucket_name = settings_obj.b2_bucket_name

    def get_url(stored_url):
        if not stored_url:
            return None
        match = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', stored_url)
        if not match:
            match = re.search(rf'/{re.escape(bucket_name)}/(.+)$', stored_url)
        if not match:
            return None
        return get_presigned_url(match.group(1), expires_in=3600)

    return {
        "report_url": get_url(period.report_url),
        "receipts_report_url": get_url(period.receipts_report_url),
        "fiscal_year": period.fiscal_year,
    }


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
        "is_locked": p.is_locked or False,
        "signature_id": str(p.signature_id) if p.signature_id else None,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "report_url": getattr(p, 'report_url', None),
        "receipts_report_url": getattr(p, 'receipts_report_url', None),
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