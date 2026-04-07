from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import hashlib, secrets, datetime

from app.db.session import get_db
from app.models.signature import ReportSignature
from app.models.finance import FinancialPeriod, FinancialTransaction
from app.models.board import BoardMember
from app.models.user import User, UserRole
from app.models.local_ump import LocalUmp
from app.models.federation import Federation
from app.core.dependencies import get_current_user

router = APIRouter()

REQUEST_ROLES = {'tesoureiro', 'vice_presidente'}
APPROVE_ROLES = {'presidente', 'vice_presidente', 'secretario_presbiterial', 'conselheiro'}


def _get_user_roles(db: Session, user_id, org_id) -> list[str]:
    roles = db.query(UserRole).filter(
        UserRole.user_id == user_id,
        UserRole.organization_id == org_id,
    ).all()
    return [r.role.value if hasattr(r.role, 'value') else str(r.role) for r in roles]


def _generate_validation_code() -> str:
    return secrets.token_urlsafe(32)[:48]


def _generate_hash(org_id, year, total_in, total_out, initial, final, timestamp) -> str:
    data = f"{org_id}:{year}:{total_in:.2f}:{total_out:.2f}:{initial:.2f}:{final:.2f}:{timestamp}"
    return hashlib.sha256(data.encode()).hexdigest()


def _to_out(s: ReportSignature) -> dict:
    return {
        "id": str(s.id),
        "organization_id": str(s.organization_id),
        "fiscal_year": s.fiscal_year,
        "period_id": str(s.period_id) if s.period_id else None,
        "status": s.status,
        "requested_by": str(s.requested_by),
        "requester_name": s.requester.full_name if s.requester else None,
        "requested_at": s.requested_at.isoformat() if s.requested_at else None,
        "reviewed_by": str(s.reviewed_by) if s.reviewed_by else None,
        "reviewer_name": s.reviewer.full_name if s.reviewer else None,
        "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
        "rejection_reason": s.rejection_reason,
        "validation_code": s.validation_code,
        "report_url": s.report_url,
        "data_hash": s.data_hash,
        "snapshot_data": s.snapshot_data,
        "invalidated_at": s.invalidated_at.isoformat() if s.invalidated_at else None,
        "invalidated_reason": s.invalidated_reason,
    }


# ── Solicitar assinatura ──────────────────────────────────────

class SignatureRequest(BaseModel):
    fiscal_year: int
    period_id: UUID


@router.post("/request", status_code=status.HTTP_201_CREATED)
def request_signature(
    payload: SignatureRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_roles = _get_user_roles(db, current_user.id, current_user.organization_id)
    if not any(r in REQUEST_ROLES for r in user_roles):
        raise HTTPException(403, "Apenas Tesoureiro ou Vice-Presidente podem solicitar assinatura")

    period = db.query(FinancialPeriod).filter(
        FinancialPeriod.id == payload.period_id,
        FinancialPeriod.organization_id == current_user.organization_id,
    ).first()
    if not period:
        raise HTTPException(404, "Período não encontrado")
    if period.is_closed:
        raise HTTPException(400, "Período já encerrado definitivamente")

    pending = db.query(ReportSignature).filter(
        ReportSignature.organization_id == current_user.organization_id,
        ReportSignature.fiscal_year == payload.fiscal_year,
        ReportSignature.status == 'pending',
    ).first()
    if pending:
        raise HTTPException(400, "Já existe uma solicitação pendente para este ano")

    # Invalida aprovações anteriores
    old = db.query(ReportSignature).filter(
        ReportSignature.organization_id == current_user.organization_id,
        ReportSignature.fiscal_year == payload.fiscal_year,
        ReportSignature.status == 'approved',
    ).first()
    if old:
        old.status = 'invalidated'
        old.invalidated_at = datetime.datetime.now(datetime.timezone.utc)
        old.invalidated_reason = 'Nova solicitação emitida'
        period.is_locked = False
        period.signature_id = None

    txs = db.query(FinancialTransaction).filter(
        FinancialTransaction.period_id == period.id
    ).all()
    INCOME = {'outras_receitas', 'aci_recebida'}
    total_in  = sum(float(t.amount) for t in txs if t.transaction_type.value in INCOME)
    total_out = sum(float(t.amount) for t in txs if t.transaction_type.value not in INCOME)
    initial   = float(period.initial_balance or 0)
    final     = initial + total_in - total_out

    now = datetime.datetime.now(datetime.timezone.utc)
    ts  = now.isoformat()
    validation_code = _generate_validation_code()
    data_hash       = _generate_hash(str(current_user.organization_id),
                                     payload.fiscal_year, total_in, total_out, initial, final, ts)

    snapshot = {
        "fiscal_year": payload.fiscal_year,
        "initial_balance": initial,
        "total_in": total_in,
        "total_out": total_out,
        "final_balance": final,
        "total_transactions": len(txs),
        "requested_at": ts,
        "organization_id": str(current_user.organization_id),
    }

    sig = ReportSignature(
        organization_id=current_user.organization_id,
        fiscal_year=payload.fiscal_year,
        period_id=period.id,
        requested_by=current_user.id,
        status='pending',
        validation_code=validation_code,
        data_hash=data_hash,
        snapshot_data=snapshot,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)
    return _to_out(sig)


# ── Listar assinaturas da organização ────────────────────────

@router.get("/")
def list_signatures(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sigs = db.query(ReportSignature).filter(
        ReportSignature.organization_id == current_user.organization_id,
    ).order_by(ReportSignature.created_at.desc()).limit(20).all()
    return [_to_out(s) for s in sigs]


# ── Buscar pendentes (para o presidente) ─────────────────────

@router.get("/pending")
def get_pending(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_roles = _get_user_roles(db, current_user.id, current_user.organization_id)
    if not any(r in APPROVE_ROLES for r in user_roles):
        raise HTTPException(403, "Sem permissão")

    sigs = db.query(ReportSignature).filter(
        ReportSignature.organization_id == current_user.organization_id,
        ReportSignature.status == 'pending',
    ).order_by(ReportSignature.created_at.desc()).all()
    return [_to_out(s) for s in sigs]


# ── Aprovar assinatura ────────────────────────────────────────

@router.post("/{signature_id}/approve")
def approve_signature(
    signature_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_roles = _get_user_roles(db, current_user.id, current_user.organization_id)
    if not any(r in APPROVE_ROLES for r in user_roles):
        raise HTTPException(403, "Sem permissão para aprovar")

    sig = db.query(ReportSignature).filter(
        ReportSignature.id == signature_id,
        ReportSignature.organization_id == current_user.organization_id,
        ReportSignature.status == 'pending',
    ).first()
    if not sig:
        raise HTTPException(404, "Solicitação não encontrada ou já processada")

    if str(sig.requested_by) == str(current_user.id):
        raise HTTPException(400, "Você não pode aprovar sua própria solicitação")

    try:
        _generate_signed_pdf(sig, current_user, db)
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar PDF assinado: {str(e)}")

    now = datetime.datetime.now(datetime.timezone.utc)
    sig.status = 'approved'
    sig.reviewed_by = current_user.id
    sig.reviewed_at = now

    if sig.period_id:
        period = db.query(FinancialPeriod).filter(
            FinancialPeriod.id == sig.period_id
        ).first()
        if period:
            period.is_locked = True
            period.signature_id = sig.id

    db.commit()
    db.refresh(sig)
    return _to_out(sig)


# ── Rejeitar assinatura ───────────────────────────────────────

class RejectPayload(BaseModel):
    reason: str


@router.post("/{signature_id}/reject")
def reject_signature(
    signature_id: UUID,
    payload: RejectPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_roles = _get_user_roles(db, current_user.id, current_user.organization_id)
    if not any(r in APPROVE_ROLES for r in user_roles):
        raise HTTPException(403, "Sem permissão")

    sig = db.query(ReportSignature).filter(
        ReportSignature.id == signature_id,
        ReportSignature.organization_id == current_user.organization_id,
        ReportSignature.status == 'pending',
    ).first()
    if not sig:
        raise HTTPException(404, "Solicitação não encontrada")

    now = datetime.datetime.now(datetime.timezone.utc)
    sig.status = 'rejected'
    sig.reviewed_by = current_user.id
    sig.reviewed_at = now
    sig.rejection_reason = payload.reason

    db.commit()
    db.refresh(sig)
    return _to_out(sig)


# ── Desbloquear período ───────────────────────────────────────

class UnlockPayload(BaseModel):
    reason: Optional[str] = None


@router.post("/unlock/{period_id}")
def unlock_period(
    period_id: UUID,
    payload: UnlockPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_roles = _get_user_roles(db, current_user.id, current_user.organization_id)
    if not any(r in REQUEST_ROLES for r in user_roles):
        raise HTTPException(403, "Sem permissão para desbloquear")

    period = db.query(FinancialPeriod).filter(
        FinancialPeriod.id == period_id,
        FinancialPeriod.organization_id == current_user.organization_id,
    ).first()
    if not period:
        raise HTTPException(404, "Período não encontrado")
    if period.is_closed:
        raise HTTPException(400, "Período encerrado definitivamente — não pode ser desbloqueado")
    if not getattr(period, 'is_locked', False):
        raise HTTPException(400, "Período não está bloqueado")

    now = datetime.datetime.now(datetime.timezone.utc)
    if period.signature_id:
        sig = db.query(ReportSignature).filter(
            ReportSignature.id == period.signature_id
        ).first()
        if sig:
            sig.status = 'invalidated'
            sig.invalidated_at = now
            sig.invalidated_reason = payload.reason or 'Desbloqueado para alterações'

    period.is_locked = False
    period.signature_id = None
    db.commit()
    return {"detail": "Período desbloqueado. Assinatura anterior invalidada."}


# ── Validação pública ─────────────────────────────────────────

@router.get("/validate/{code}")
def validate_code(code: str, db: Session = Depends(get_db)):
    sig = db.query(ReportSignature).filter(
        ReportSignature.validation_code == code,
    ).first()

    if not sig:
        return {"valid": False, "message": "Código de validação não encontrado."}

    if sig.status == 'approved':
        org_name = None
        fed = db.query(Federation).filter(Federation.id == sig.organization_id).first()
        if fed:
            org_name = fed.name
        else:
            local = db.query(LocalUmp).filter(LocalUmp.id == sig.organization_id).first()
            if local:
                org_name = local.name

        return {
            "valid": True,
            "message": "✅ Documento válido e autêntico.",
            "organization": org_name,
            "fiscal_year": sig.fiscal_year,
            "validation_code": sig.validation_code,
            "approved_at": sig.reviewed_at.isoformat() if sig.reviewed_at else None,
            "requester": sig.requester.full_name if sig.requester else None,
            "approver": sig.reviewer.full_name if sig.reviewer else None,
            "data_hash": sig.data_hash,
            "snapshot": sig.snapshot_data,
        }

    if sig.status == 'invalidated':
        org_name_inv = None
        fed_inv = db.query(Federation).filter(Federation.id == sig.organization_id).first()
        if fed_inv:
            org_name_inv = fed_inv.name
        else:
            local_inv = db.query(LocalUmp).filter(LocalUmp.id == sig.organization_id).first()
            if local_inv:
                org_name_inv = local_inv.name
        return {
            "valid": False,
            "message": "⚠️ Este documento foi invalidado.",
            "organization": org_name_inv,
            "fiscal_year": sig.fiscal_year,
            "reason": sig.invalidated_reason,
            "invalidated_at": sig.invalidated_at.isoformat() if sig.invalidated_at else None,
        }

    return {
        "valid": False,
        "message": "❌ Documento não aprovado ou pendente.",
        "status": sig.status,
    }


# ── Pre-signed URL do PDF assinado ───────────────────────────

@router.get("/{signature_id}/report-url")
def get_signed_report_url(
    signature_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import re
    from app.services.storage import get_presigned_url
    from app.core.config import get_settings

    sig = db.query(ReportSignature).filter(
        ReportSignature.id == signature_id,
        ReportSignature.organization_id == current_user.organization_id,
    ).first()
    if not sig or not sig.report_url:
        raise HTTPException(404, "Relatório não encontrado")

    s = get_settings()
    bucket = s.b2_bucket_name
    match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', sig.report_url)
    if not match:
        match = re.search(rf'/{re.escape(bucket)}/(.+)$', sig.report_url)
    if not match:
        raise HTTPException(400, "URL inválida")
    url = get_presigned_url(match.group(1), expires_in=3600)
    return {"url": url, "validation_code": sig.validation_code}


# ── Função interna: gera e faz upload do PDF assinado ────────

def _generate_signed_pdf(sig: ReportSignature, approver: User, db: Session):
    import io, re
    from app.services.storage import upload_file, _get_client
    from app.services.pdf_generator import generate_financial_report
    from app.core.config import get_settings

    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name
    b2 = _get_client()

    # Organização
    fed = db.query(Federation).filter(Federation.id == sig.organization_id).first()
    if fed:
        org_data = {
            "id": str(fed.id), "name": fed.name,
            "presbytery_name": fed.presbytery_name,
            "synodal_name": getattr(fed, 'synodal_name', None),
            "logo_url": fed.logo_url,
            "theme_color": getattr(fed, 'theme_color', '#1a2a6c') or '#1a2a6c',
            "society_type": getattr(fed, 'society_type', 'UMP') or 'UMP',
            "organization_type": "federation",
        }
    else:
        local = db.query(LocalUmp).filter(LocalUmp.id == sig.organization_id).first()
        org_data = {
            "id": str(local.id), "name": local.name,
            "presbytery_name": local.presbytery_name,
            "church_name": local.church_name,
            "pastor_name": local.pastor_name,
            "logo_url": local.logo_url,
            "theme_color": getattr(local, 'theme_color', '#1a2a6c') or '#1a2a6c',
            "society_type": getattr(local, 'society_type', 'UMP') or 'UMP',
            "organization_type": "local_ump",
        }

    # Logo
    logo_bytes = None
    if org_data.get('logo_url'):
        match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', org_data['logo_url'])
        if not match:
            match = re.search(rf'/{re.escape(bucket)}/(.+)$', org_data['logo_url'])
        if match:
            try:
                resp = b2.get_object(Bucket=bucket, Key=match.group(1))
                logo_bytes = resp['Body'].read()
            except:
                pass

    # Diretoria
    period = sig.period
    board_list = db.query(BoardMember).filter(
        BoardMember.organization_id == sig.organization_id,
        BoardMember.fiscal_year == sig.fiscal_year,
        BoardMember.is_active == True,
    ).all()
    board_data = [{"role": b.role.value, "member_name": b.member_name} for b in board_list]

    # Lançamentos por mês
    txs = db.query(FinancialTransaction).filter(
        FinancialTransaction.period_id == sig.period_id
    ).order_by(FinancialTransaction.transaction_date).all()

    INCOME = {'outras_receitas', 'aci_recebida'}
    tx_by_month: dict[int, list] = {}
    for t in txs:
        mk = t.transaction_date.month
        tx_by_month.setdefault(mk, []).append(t)

    running = float(period.initial_balance or 0)
    months_data = []
    for m in range(1, 13):
        mtxs = tx_by_month.get(m, [])
        tin  = sum(float(t.amount) for t in mtxs if t.transaction_type.value in INCOME)
        tout = sum(float(t.amount) for t in mtxs if t.transaction_type.value not in INCOME)
        opening = running
        running += tin - tout
        months_data.append({
            "month_num": m,
            "month_label": ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
                            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"][m-1],
            "transactions": [
                {"id": str(t.id), "transaction_date": t.transaction_date.isoformat(),
                 "transaction_type": t.transaction_type.value, "description": t.description,
                 "amount": float(t.amount), "receipt_url": t.receipt_url}
                for t in mtxs
            ],
            "total_in": tin, "total_out": tout,
            "opening_balance": opening, "closing_balance": running,
            "has_transactions": bool(mtxs),
        })

    period_dict = {
        "fiscal_year": sig.fiscal_year,
        "initial_balance": float(period.initial_balance or 0),
        "final_balance": running,
    }

    # QR Code
    validation_url = f"https://umpgestao.netlify.app/validar.html?codigo={sig.validation_code}"
    qr_bytes = None
    try:
        import qrcode as qr_lib
        qr = qr_lib.QRCode(version=1, box_size=6, border=2)
        qr.add_data(validation_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format='PNG')
        qr_bytes = qr_buf.getvalue()
    except Exception as e:
        print(f"QR Code falhou: {e}")

    requester = db.query(User).filter(User.id == sig.requested_by).first()
    signature_data = {
        "validation_code": sig.validation_code,
        "data_hash": sig.data_hash[:32] + "...",
        "requested_by": requester.full_name if requester else "—",
        "approved_by": approver.full_name,
        "approved_at": datetime.datetime.now(datetime.timezone.utc).strftime('%d/%m/%Y %H:%M UTC'),
        "validation_url": validation_url,
        "qr_bytes": qr_bytes,
    }

    pdf_bytes = generate_financial_report(
        org_data=org_data,
        period_data=period_dict,
        months_data=months_data,
        board_data=board_data,
        logo_bytes=logo_bytes,
        theme_color=org_data.get('theme_color', '#1a2a6c'),
        signature_data=signature_data,
    )

    key = f"signatures/{sig.organization_id}/{sig.fiscal_year}/relatorio_assinado_{sig.validation_code[:12]}.pdf"
    url = upload_file(pdf_bytes, key, 'application/pdf')
    sig.report_url = url
