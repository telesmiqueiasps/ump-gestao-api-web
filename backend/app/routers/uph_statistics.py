from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import io

from app.db.session import get_db
from app.models.uph_statistic import UphStatistic
from app.models.user import User
from app.core.dependencies import get_current_user

router = APIRouter()


def _delta(current: int, previous: int) -> Optional[float]:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _relation_pct(numerator: int, denominator: int) -> Optional[float]:
    if not denominator or denominator == 0:
        return None
    return round((numerator / denominator) * 100, 1)


def _stat_out(s: UphStatistic) -> dict:
    i1c = s.item1_current or 0
    i2c = s.item2_current or 0
    i3c = s.item3_current or 0
    i4c = s.item4_current or 0
    i5c = s.item5_current or 0
    i6c = s.item6_current or 0
    i7c = s.item7_current or 0
    i1p = s.item1_previous or 0
    i2p = s.item2_previous or 0
    i3p = s.item3_previous or 0
    i4p = s.item4_previous or 0
    i5p = s.item5_previous or 0
    i6p = s.item6_previous or 0
    i7p = s.item7_previous or 0

    return {
        "id": str(s.id),
        "organization_id": str(s.organization_id),
        "organization_type": s.organization_type,
        "fiscal_year": s.fiscal_year,
        "item1_current":  i1c, "item1_previous": i1p,
        "item2_current":  i2c, "item2_previous": i2p,
        "item3_current":  i3c, "item3_previous": i3p,
        "item4_current":  i4c, "item4_previous": i4p,
        "item5_current":  i5c, "item5_previous": i5p,
        "item6_current":  i6c, "item6_previous": i6p,
        "item7_current":  i7c, "item7_previous": i7p,
        "rel_1_2": _relation_pct(i2c, i1c),
        "rel_3_4": _relation_pct(i4c, i3c),
        "rel_6_7": _relation_pct(i7c, i6c),
        "item1_delta": _delta(i1c, i1p),
        "item2_delta": _delta(i2c, i2p),
        "item3_delta": _delta(i3c, i3p),
        "item4_delta": _delta(i4c, i4p),
        "item5_delta": _delta(i5c, i5p),
        "item6_delta": _delta(i6c, i6p),
        "item7_delta": _delta(i7c, i7p),
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


class StatUpdate(BaseModel):
    item1_current:  Optional[int] = None
    item1_previous: Optional[int] = None
    item2_current:  Optional[int] = None
    item2_previous: Optional[int] = None
    item3_current:  Optional[int] = None
    item3_previous: Optional[int] = None
    item4_current:  Optional[int] = None
    item4_previous: Optional[int] = None
    item5_current:  Optional[int] = None
    item5_previous: Optional[int] = None
    item6_current:  Optional[int] = None
    item6_previous: Optional[int] = None
    item7_current:  Optional[int] = None
    item7_previous: Optional[int] = None


@router.get("/{year}")
def get_or_create_stat(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stat = db.query(UphStatistic).filter(
        UphStatistic.organization_id == current_user.organization_id,
        UphStatistic.fiscal_year == year,
    ).first()

    if not stat:
        org_type = current_user.organization_type.value \
            if hasattr(current_user.organization_type, 'value') \
            else str(current_user.organization_type)
        stat = UphStatistic(
            organization_id   = current_user.organization_id,
            organization_type = org_type,
            fiscal_year       = year,
            created_by        = current_user.id,
        )
        db.add(stat)
        db.commit()
        db.refresh(stat)

    return _stat_out(stat)


@router.put("/{year}")
def update_stat(
    year: int,
    payload: StatUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stat = db.query(UphStatistic).filter(
        UphStatistic.organization_id == current_user.organization_id,
        UphStatistic.fiscal_year == year,
    ).first()
    if not stat:
        raise HTTPException(status_code=404, detail="Estatística não encontrada")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(stat, field, value)
    db.commit()
    db.refresh(stat)
    return _stat_out(stat)


@router.get("/{year}/pdf")
def generate_stat_pdf(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stat = db.query(UphStatistic).filter(
        UphStatistic.organization_id == current_user.organization_id,
        UphStatistic.fiscal_year == year,
    ).first()
    if not stat:
        raise HTTPException(status_code=404, detail="Estatística não encontrada")

    import os, re
    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp
    from app.services.pdf_generator import generate_uph_stat_report
    from app.services.storage import _get_client
    from app.core.config import get_settings

    org_type = current_user.organization_type.value \
        if hasattr(current_user.organization_type, 'value') \
        else str(current_user.organization_type)

    if org_type == 'federation':
        obj = db.query(Federation).filter(
            Federation.id == current_user.organization_id).first()
        org_data = {
            "name": obj.name if obj else '',
            "presbytery_name": obj.presbytery_name if obj else '',
            "synodal_name": getattr(obj, 'synodal_name', '') or '',
            "logo_url": obj.logo_url if obj else None,
            "organization_type": "federation",
        }
    else:
        obj = db.query(LocalUmp).filter(
            LocalUmp.id == current_user.organization_id).first()
        fed = db.query(Federation).filter(
            Federation.id == obj.federation_id).first() if obj else None
        org_data = {
            "name": obj.name if obj else '',
            "presbytery_name": obj.presbytery_name if obj else '',
            "federation_name": fed.name if fed else '',
            "synodal_name": fed.synodal_name if fed and hasattr(fed, 'synodal_name') else '',
            "logo_url": obj.logo_url if obj else None,
            "organization_type": "local_ump",
        }

    ipb_logo_bytes = None
    try:
        ipb_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'ipb_logo.png')
        if os.path.exists(ipb_path):
            with open(ipb_path, 'rb') as f:
                ipb_logo_bytes = f.read()
    except Exception:
        pass

    logo_bytes = None
    logo_url = org_data.get('logo_url')
    if logo_url:
        try:
            settings_obj = get_settings()
            bucket = settings_obj.b2_bucket_name
            b2 = _get_client()
            match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', logo_url)
            if not match:
                match = re.search(rf'/{re.escape(bucket)}/(.+)$', logo_url)
            if match:
                resp = b2.get_object(Bucket=bucket, Key=match.group(1))
                logo_bytes = resp['Body'].read()
        except Exception:
            pass

    pdf_bytes = generate_uph_stat_report(
        org_data       = org_data,
        fiscal_year    = year,
        stat           = _stat_out(stat),
        logo_bytes     = logo_bytes,
        ipb_logo_bytes = ipb_logo_bytes,
    )

    filename = f"Relatorio_Estatistica_UPH_{year}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/consolidate/{year}")
def consolidate_federation_stats(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soma itens 1-5 de todas as locais e salva na federação"""
    from app.models.local_ump import LocalUmp

    org_type = current_user.organization_type.value \
        if hasattr(current_user.organization_type, 'value') \
        else str(current_user.organization_type)

    if org_type != 'federation':
        raise HTTPException(status_code=403,
                            detail="Apenas federações podem consolidar")

    locals_ = db.query(LocalUmp).filter(
        LocalUmp.federation_id == current_user.organization_id,
        LocalUmp.is_active == True,
    ).all()

    totals = {f'item{i}_current': 0 for i in range(1, 6)}
    totals.update({f'item{i}_previous': 0 for i in range(1, 6)})
    locals_with_data = 0

    for local in locals_:
        stat = db.query(UphStatistic).filter(
            UphStatistic.organization_id == local.id,
            UphStatistic.fiscal_year == year,
        ).first()
        if stat:
            locals_with_data += 1
            for i in range(1, 6):
                totals[f'item{i}_current']  += getattr(stat, f'item{i}_current',  0) or 0
                totals[f'item{i}_previous'] += getattr(stat, f'item{i}_previous', 0) or 0

    fed_stat = db.query(UphStatistic).filter(
        UphStatistic.organization_id == current_user.organization_id,
        UphStatistic.fiscal_year == year,
    ).first()

    if not fed_stat:
        fed_stat = UphStatistic(
            organization_id   = current_user.organization_id,
            organization_type = 'federation',
            fiscal_year       = year,
            created_by        = current_user.id,
        )
        db.add(fed_stat)

    for field, value in totals.items():
        setattr(fed_stat, field, value)

    db.commit()
    db.refresh(fed_stat)

    return {
        "detail": f"Consolidado com dados de {locals_with_data} local(is)",
        "locals_count": locals_with_data,
        "stat": _stat_out(fed_stat),
    }


@router.get("/{year}/locals")
def list_locals_stats(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.local_ump import LocalUmp

    org_type = current_user.organization_type.value \
        if hasattr(current_user.organization_type, 'value') \
        else str(current_user.organization_type)
    if org_type != 'federation':
        raise HTTPException(status_code=403, detail="Apenas federações")

    locals_ = db.query(LocalUmp).filter(
        LocalUmp.federation_id == current_user.organization_id,
        LocalUmp.is_active == True,
    ).all()

    result = []
    for local in locals_:
        stat = db.query(UphStatistic).filter(
            UphStatistic.organization_id == local.id,
            UphStatistic.fiscal_year == year,
        ).first()
        result.append({
            "local_id": str(local.id),
            "local_name": local.name,
            "stat": _stat_out(stat) if stat else None,
        })

    return result
