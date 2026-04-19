from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from app.db.session import get_db
from app.models.local_ump import LocalUmp
from app.models.user import User
from app.models.enums import OrgType, BoardRole
from app.core.dependencies import get_current_user, require_federation, require_local_ump
from app.services.storage import upload_file

router = APIRouter()


class LocalUmpCreate(BaseModel):
    name: str
    church_name: Optional[str] = None
    pastor_name: Optional[str] = None
    pastor_contact: Optional[str] = None
    organization_date: Optional[str] = None
    presbytery_name: Optional[str] = None
    address: Optional[str] = None
    fiscal_year: Optional[int] = None
    initial_balance: Optional[float] = 0.0


class LocalUmpUpdate(BaseModel):
    name: Optional[str] = None
    church_name: Optional[str] = None
    pastor_name: Optional[str] = None
    pastor_contact: Optional[str] = None
    organization_date: Optional[str] = None
    presbytery_name: Optional[str] = None
    address: Optional[str] = None
    fiscal_year: Optional[int] = None
    initial_balance: Optional[float] = None
    theme_color: Optional[str] = None
    society_type: Optional[str] = None
    pix_key: Optional[str] = None
    reminder_day: Optional[int] = None
    member_portal_enabled: Optional[bool] = None


# Federação cria uma UMP Local
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_local_ump(
    payload: LocalUmpCreate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    local = LocalUmp(
        federation_id=current_user.organization_id,
        **payload.model_dump()
    )
    db.add(local)
    db.commit()
    db.refresh(local)
    return _to_out(local)


# UMP Local vê seus próprios dados
@router.get("/me")
def get_my_local_ump(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).options(joinedload(LocalUmp.federation)).filter(
        LocalUmp.id == current_user.organization_id,
        LocalUmp.is_active == True,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")
    return _to_out(local)


@router.get("/anniversaries")
def get_local_anniversaries(
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    import datetime
    from sqlalchemy import extract
    current_month = datetime.date.today().month
    current_day   = datetime.date.today().day
    current_year  = datetime.date.today().year

    locals_ = db.query(LocalUmp).filter(
        LocalUmp.federation_id == current_user.organization_id,
        LocalUmp.is_active == True,
        LocalUmp.organization_date.isnot(None),
        extract('month', LocalUmp.organization_date) == current_month,
    ).order_by(extract('day', LocalUmp.organization_date)).all()

    result = []
    for l in locals_:
        org_day        = l.organization_date.day
        years          = current_year - l.organization_date.year
        is_today       = org_day == current_day
        already_passed = org_day < current_day

        result.append({
            "id":                str(l.id),
            "name":              l.name,
            "church_name":       l.church_name,
            "organization_date": l.organization_date.isoformat(),
            "org_day":           org_day,
            "years":             years,
            "is_today":          is_today,
            "already_passed":    already_passed,
        })

    return result


@router.get("/{local_id}/reports")
def get_local_reports(
    local_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    from app.models.finance import FinancialPeriod
    periods = db.query(FinancialPeriod).filter(
        FinancialPeriod.organization_id == local_id,
        FinancialPeriod.is_closed == True,
    ).order_by(FinancialPeriod.fiscal_year.desc()).all()

    result = []
    for p in periods:
        if p.report_url or p.receipts_report_url:
            result.append({
                "id": str(p.id),
                "fiscal_year": p.fiscal_year,
                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
                "report_url": p.report_url,
                "receipts_report_url": p.receipts_report_url,
                "validation_code": p.validation_code,
            })
    return result


@router.get("/{local_id}/reports/{period_id}/urls")
def get_local_report_urls(
    local_id: UUID,
    period_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    from app.models.finance import FinancialPeriod
    from app.services.storage import get_presigned_url
    from app.core.config import get_settings
    import re

    period = db.query(FinancialPeriod).filter(
        FinancialPeriod.id == period_id,
        FinancialPeriod.organization_id == local_id,
        FinancialPeriod.is_closed == True,
    ).first()
    if not period:
        raise HTTPException(status_code=404, detail="Período não encontrado")

    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name

    def _presign(url):
        if not url:
            return None
        match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', url)
        if not match:
            match = re.search(rf'/{re.escape(bucket)}/(.+)$', url)
        if not match:
            return None
        return get_presigned_url(match.group(1), expires_in=3600)

    return {
        "fiscal_year": period.fiscal_year,
        "report_url": _presign(period.report_url),
        "receipts_report_url": _presign(period.receipts_report_url),
        "validation_code": period.validation_code,
        "closed_at": period.closed_at.isoformat() if period.closed_at else None,
    }


# Federação vê uma Local específica sua
@router.get("/{local_id}")
def get_local_ump(
    local_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada ou não pertence à sua Federação")
    return _to_out(local)


# Federação acessa relatórios de atividades de uma Local sua
@router.get("/{local_id}/activity-reports")
def get_local_activity_reports(
    local_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    from app.models.activity_report import ActivityReport
    reports = db.query(ActivityReport).filter(
        ActivityReport.organization_id == local_id,
        ActivityReport.status == 'published',
        ActivityReport.report_url != None,
    ).order_by(ActivityReport.fiscal_year.desc()).all()

    return [
        {
            "id": str(r.id),
            "fiscal_year": r.fiscal_year,
            "report_url": r.report_url,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in reports
    ]


@router.get("/{local_id}/activity-reports/{report_id}/url")
def get_local_activity_report_url(
    local_id: UUID,
    report_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    import re
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    from app.models.activity_report import ActivityReport
    from app.services.storage import get_presigned_url
    from app.core.config import get_settings

    report = db.query(ActivityReport).filter(
        ActivityReport.id == report_id,
        ActivityReport.organization_id == local_id,
        ActivityReport.status == 'published',
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name
    match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', report.report_url)
    if not match:
        match = re.search(rf'/{re.escape(bucket)}/(.+)$', report.report_url)
    if not match:
        raise HTTPException(status_code=400, detail="URL inválida")

    url = get_presigned_url(match.group(1), expires_in=3600)
    return {"url": url, "fiscal_year": report.fiscal_year}


# Federação atualiza uma Local sua
@router.put("/{local_id}")
def update_local_ump(
    local_id: UUID,
    payload: LocalUmpUpdate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(local, field, value)

    db.commit()
    db.refresh(local)
    return _to_out(local)


# UMP Local atualiza seus próprios dados
@router.put("/me/update")
def update_my_local_ump(
    payload: LocalUmpUpdate,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    # Locais não podem alterar saldo inicial e ano fiscal diretamente
    restricted = payload.model_dump(exclude_none=True)
    restricted.pop("initial_balance", None)
    restricted.pop("fiscal_year", None)

    if "reminder_day" in restricted:
        restricted["reminder_day"] = max(1, min(28, restricted["reminder_day"]))

    for field, value in restricted.items():
        setattr(local, field, value)

    db.commit()
    db.refresh(local)
    return _to_out(local)


# Federação desativa uma Local (e seus usuários)
@router.post("/{local_id}/deactivate")
def deactivate_local(
    local_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    import datetime as dt
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")
    if not local.is_active:
        raise HTTPException(status_code=400, detail="Local já inativa")

    now = dt.datetime.now(dt.timezone.utc)
    local.is_active = False
    local.deactivated_at = now

    # Inativa todos os usuários da local
    user_ids = [
        u.id for u in db.query(User).filter(
            User.organization_id == local_id,
            User.is_active == True,
        ).all()
    ]
    if user_ids:
        db.query(User).filter(User.id.in_(user_ids)).update(
            {"is_active": False, "deactivated_at": now},
            synchronize_session=False,
        )

    db.commit()

    inactivated = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    return {
        "detail": "Local inativada com sucesso",
        "inactivated_users": [
            {"id": str(u.id), "full_name": u.full_name, "email": u.email}
            for u in inactivated
        ],
    }


# Federação reativa uma Local (e seus usuários)
@router.post("/{local_id}/reactivate")
def reactivate_local(
    local_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    import datetime as dt
    local = db.query(LocalUmp).filter(
        LocalUmp.id == local_id,
        LocalUmp.federation_id == current_user.organization_id,
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")
    if local.is_active:
        raise HTTPException(status_code=400, detail="Local já ativa")

    now = dt.datetime.now(dt.timezone.utc)
    local.is_active = True
    local.reactivated_at = now

    # Reativa todos os usuários da local
    user_ids = [
        u.id for u in db.query(User).filter(
            User.organization_id == local_id,
            User.is_active == False,
        ).all()
    ]
    if user_ids:
        db.query(User).filter(User.id.in_(user_ids)).update(
            {"is_active": True, "deactivated_at": None},
            synchronize_session=False,
        )

    db.commit()
    return {"detail": "Local reativada com sucesso"}


# Upload logo — UMP Local
@router.post("/me/logo")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    allowed = ["image/png", "image/jpeg", "image/webp"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Formato inválido. Use PNG, JPG ou WEBP.")

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Máximo 5MB.")

    # Exclui logo antiga do B2 se existir
    if local.logo_url:
        from app.services.storage import delete_folder
        from app.core.config import get_settings
        import re
        s = get_settings()
        match = re.search(rf'/file/{re.escape(s.b2_bucket_name)}/(.+)$', local.logo_url)
        if not match:
            match = re.search(rf'/{re.escape(s.b2_bucket_name)}/(.+)$', local.logo_url)
        if match:
            old_key = match.group(1)
            folder = '/'.join(old_key.split('/')[:-1]) + '/'
            delete_folder(folder)

    key = f"logos/local_umps/{local.id}/{file.filename}"
    url = upload_file(contents, key, file.content_type)
    local.logo_url = url
    db.commit()
    db.refresh(local)
    return _to_out(local)


@router.get("/me/logo-url")
def get_logo_url_local(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == current_user.organization_id
    ).first()
    if not local or not local.logo_url:
        raise HTTPException(status_code=404, detail="Logo não encontrada")

    from app.services.storage import get_presigned_url, _get_client
    from app.core.config import get_settings
    import re, base64
    s = get_settings()
    bucket_name = s.b2_bucket_name
    stored_url = local.logo_url

    match = re.search(rf'/file/{re.escape(bucket_name)}/(.+)$', stored_url)
    if not match:
        match = re.search(rf'/{re.escape(bucket_name)}/(.+)$', stored_url)
    if not match:
        raise HTTPException(status_code=400, detail="URL da logo inválida")

    key = match.group(1)

    client = _get_client()
    try:
        response = client.get_object(Bucket=bucket_name, Key=key)
        image_bytes = response['Body'].read()
        content_type = response.get('ContentType', 'image/png')
        b64 = base64.b64encode(image_bytes).decode('utf-8')
        data_url = f"data:{content_type};base64,{b64}"
        return {"url": get_presigned_url(key, expires_in=86400), "base64": data_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao baixar logo: {str(e)}")


@router.post("/me/pix-qr")
async def upload_pix_qr(
    file: UploadFile = File(...),
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Máx 5MB.")

    allowed = ["image/png", "image/jpeg", "image/webp"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Formato inválido")

    if local.pix_qr_key:
        try:
            from app.services.storage import delete_folder
            delete_folder(local.pix_qr_key)
        except:
            pass

    key = f"pix-qr/{current_user.organization_id}/{file.filename}"
    url = upload_file(contents, key, file.content_type)

    local.pix_qr_url = url
    local.pix_qr_key = key
    db.commit()

    import base64
    b64 = base64.b64encode(contents).decode('utf-8')
    return {
        "url": url,
        "base64": f"data:{file.content_type};base64,{b64}"
    }


@router.post("/me/pix-qr/generate")
async def generate_pix_qr(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()

    if not local.pix_key:
        raise HTTPException(status_code=400,
            detail="Cadastre a chave PIX antes de gerar o QR Code")

    import qrcode as _qrcode
    import io as _io
    import base64

    qr = _qrcode.QRCode(
        version=1,
        error_correction=_qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(local.pix_key)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = _io.BytesIO()
    img.save(buf, format='PNG')
    png_bytes = buf.getvalue()

    if local.pix_qr_key:
        try:
            from app.services.storage import delete_folder
            delete_folder(local.pix_qr_key)
        except:
            pass

    key = f"pix-qr/{current_user.organization_id}/pix_qr.png"
    url = upload_file(png_bytes, key, 'image/png')

    local.pix_qr_url = url
    local.pix_qr_key = key
    db.commit()

    b64 = base64.b64encode(png_bytes).decode('utf-8')
    return {
        "url": url,
        "base64": f"data:image/png;base64,{b64}"
    }


@router.get("/me/pix-qr-base64")
def get_pix_qr_base64(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    from app.services.storage import _get_client
    from app.core.config import get_settings
    local = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    if not local or not local.pix_qr_key:
        raise HTTPException(status_code=404, detail="QR Code não encontrado")
    settings_obj = get_settings()
    b2 = _get_client()
    try:
        import base64
        resp = b2.get_object(Bucket=settings_obj.b2_bucket_name, Key=local.pix_qr_key)
        content = resp['Body'].read()
        ct = resp.get('ContentType', 'image/png')
        return {"base64": f"data:{ct};base64,{base64.b64encode(content).decode()}"}
    except:
        raise HTTPException(status_code=404, detail="QR Code não encontrado")


def _to_out(l: LocalUmp) -> dict:
    return {
        "id": str(l.id),
        "federation_id": str(l.federation_id),
        "name": l.name,
        "church_name": l.church_name,
        "pastor_name": l.pastor_name,
        "pastor_contact": l.pastor_contact,
        "organization_date": l.organization_date.isoformat() if l.organization_date else None,
        "presbytery_name": l.presbytery_name,
        "address": l.address,
        "logo_url": l.logo_url,
        "theme_color": getattr(l, 'theme_color', None) or "#1a2a6c",
        "society_type": l.federation.society_type if l.federation else getattr(l, 'society_type', None) or 'UMP',
        "fiscal_year": l.fiscal_year,
        "initial_balance": float(l.initial_balance) if l.initial_balance else 0.0,
        "is_active": l.is_active,
        "deactivated_at": l.deactivated_at.isoformat() if l.deactivated_at else None,
        "reactivated_at": l.reactivated_at.isoformat() if l.reactivated_at else None,
        "pix_key":               l.pix_key,
        "pix_qr_url":            l.pix_qr_url,
        "reminder_day":          l.reminder_day or 5,
        "member_portal_enabled": l.member_portal_enabled if l.member_portal_enabled is not None else True,
        "portal_url":            f"https://umpgestao.netlify.app/socio.html?org={str(l.id)}",
    }