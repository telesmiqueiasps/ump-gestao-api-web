from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Security
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import re

from app.db.session import get_db
from app.models.member import Member
from app.models.local_ump import LocalUmp
from app.models.member_fees import MemberMonthlyFee, MemberAciContribution
from app.core.security import create_access_token
from app.services.storage import _get_client
from app.core.config import get_settings

router = APIRouter()

MONTH_NAMES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
               'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


def _clean_phone(phone: str) -> str:
    return re.sub(r'\D', '', phone or '')


class MemberLoginPayload(BaseModel):
    org_id: UUID
    phone: str
    pin: str


@router.post("/login")
def member_login(
    payload: MemberLoginPayload,
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == payload.org_id,
        LocalUmp.is_active == True,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="Organização não encontrada")

    if not local.member_portal_enabled:
        raise HTTPException(status_code=403,
            detail="Portal de sócios desativado para esta organização")

    clean_input = _clean_phone(payload.phone)
    all_members = db.query(Member).filter(
        Member.local_ump_id == payload.org_id,
        Member.is_active == True,
    ).all()

    member = None
    for m in all_members:
        if _clean_phone(m.phone) == clean_input:
            member = m
            break

    if not member:
        raise HTTPException(status_code=401,
            detail="Número de celular não encontrado")

    if not member.birth_date:
        raise HTTPException(status_code=403,
            detail="Seu cadastro ainda não tem data de nascimento. "
                   "Entre em contato com a diretoria para liberar seu acesso.")

    birth = member.birth_date
    expected_pin = f"{birth.day:02d}{birth.month:02d}"
    if payload.pin.strip() != expected_pin:
        raise HTTPException(status_code=401,
            detail="PIN incorreto. Use o dia e mês do seu nascimento (ex: 1503 para 15/03)")

    token = create_access_token(data={
        "sub": str(member.id),
        "type": "member_portal",
        "org_id": str(payload.org_id),
    })

    return {
        "access_token": token,
        "member": {
            "id": str(member.id),
            "full_name": member.full_name,
            "member_type": member.member_type.value
                if hasattr(member.member_type, 'value') else str(member.member_type),
            "org_id": str(payload.org_id),
            "org_name": local.name,
        }
    }


bearer = HTTPBearer()


def get_portal_member(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
    db: Session = Depends(get_db),
):
    from jose import jwt, JWTError
    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=["HS256"]
        )
        if payload.get("type") != "member_portal":
            raise HTTPException(status_code=401, detail="Token inválido")
        member_id = payload.get("sub")
        org_id    = payload.get("org_id")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    member = db.query(Member).filter(Member.id == member_id).first()
    if not member or not member.is_active:
        raise HTTPException(status_code=401, detail="Sócio inativo")
    return member, org_id


@router.get("/me")
def get_portal_member_data(
    auth=Depends(get_portal_member),
    db: Session = Depends(get_db),
):
    member, org_id = auth
    local = db.query(LocalUmp).filter(LocalUmp.id == member.local_ump_id).first()

    pix_qr_b64 = None
    if local and local.pix_qr_key:
        try:
            import base64
            settings = get_settings()
            b2 = _get_client()
            resp = b2.get_object(Bucket=settings.b2_bucket_name, Key=local.pix_qr_key)
            content = resp['Body'].read()
            ct = resp.get('ContentType', 'image/png')
            pix_qr_b64 = f"data:{ct};base64,{base64.b64encode(content).decode()}"
        except:
            pass

    return {
        "id": str(member.id),
        "full_name": member.full_name,
        "org_name": local.name if local else '',
        "pix_key": local.pix_key if local else None,
        "pix_qr_b64": pix_qr_b64,
        "reminder_day": local.reminder_day if local else 5,
    }


@router.get("/fees/{year}")
def get_member_fees(
    year: int,
    auth=Depends(get_portal_member),
    db: Session = Depends(get_db),
):
    import datetime
    member, org_id = auth

    fees = db.query(MemberMonthlyFee).filter(
        MemberMonthlyFee.member_id == member.id,
        MemberMonthlyFee.local_ump_id == member.local_ump_id,
    ).order_by(MemberMonthlyFee.reference_month).all()

    result = []
    for month_num in range(1, 13):
        ref_date = datetime.date(year, month_num, 1)
        fee = next((f for f in fees
                    if f.reference_month.year == year
                    and f.reference_month.month == month_num), None)
        result.append({
            "month": month_num,
            "month_name": MONTH_NAMES[month_num - 1],
            "reference_month": ref_date.isoformat(),
            "is_paid": fee.is_paid if fee else False,
            "amount": float(fee.amount) if fee else None,
            "paid_at": fee.paid_at.isoformat() if fee and fee.paid_at else None,
            "has_record": fee is not None,
        })
    return result


@router.get("/aci/{year}")
def get_member_aci(
    year: int,
    auth=Depends(get_portal_member),
    db: Session = Depends(get_db),
):
    member, org_id = auth
    contribs = db.query(MemberAciContribution).filter(
        MemberAciContribution.member_id == member.id,
        MemberAciContribution.fiscal_year == year,
    ).order_by(MemberAciContribution.payment_date).all()

    total_paid = sum(float(c.amount) for c in contribs)

    local = db.query(LocalUmp).filter(LocalUmp.id == member.local_ump_id).first()
    aci_year_value = float(local.aci_year_value) if local and local.aci_year_value else 0

    return {
        "fiscal_year": year,
        "aci_year_value": aci_year_value,
        "total_paid": total_paid,
        "remaining": max(0, aci_year_value - total_paid),
        "contributions": [
            {
                "id": str(c.id),
                "payment_date": c.payment_date.isoformat(),
                "amount": float(c.amount),
            }
            for c in contribs
        ],
    }


@router.get("/org/{org_id}")
def get_org_public_info(
    org_id: UUID,
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == org_id,
        LocalUmp.is_active == True,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="Organização não encontrada")

    logo_b64 = None
    if local.logo_url:
        try:
            import re as _re, base64
            settings = get_settings()
            b2 = _get_client()
            bucket = settings.b2_bucket_name
            match = _re.search(rf'/file/{_re.escape(bucket)}/(.+)$', local.logo_url)
            if not match:
                match = _re.search(rf'/{_re.escape(bucket)}/(.+)$', local.logo_url)
            if match:
                resp = b2.get_object(Bucket=bucket, Key=match.group(1))
                ct = resp.get('ContentType', 'image/png')
                logo_b64 = f"data:{ct};base64,{base64.b64encode(resp['Body'].read()).decode()}"
        except:
            pass

    return {
        "id": str(local.id),
        "name": local.name,
        "church_name": local.church_name,
        "theme_color": local.theme_color or '#1a2a6c',
        "society_type": local.society_type or 'UMP',
        "logo_b64": logo_b64,
        "portal_enabled": local.member_portal_enabled if local.member_portal_enabled is not None else True,
    }