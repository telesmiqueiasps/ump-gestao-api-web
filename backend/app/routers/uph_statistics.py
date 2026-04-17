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


def _stat_out(s: UphStatistic) -> dict:
    return {
        "id": str(s.id),
        "organization_id": str(s.organization_id),
        "organization_type": s.organization_type,
        "fiscal_year": s.fiscal_year,
        "item1_current":  s.item1_current or 0,
        "item1_previous": s.item1_previous or 0,
        "item1_delta":    _delta(s.item1_current or 0, s.item1_previous or 0),
        "item2_current":  s.item2_current or 0,
        "item2_previous": s.item2_previous or 0,
        "item2_delta":    _delta(s.item2_current or 0, s.item2_previous or 0),
        "item3_current":  s.item3_current or 0,
        "item3_previous": s.item3_previous or 0,
        "item3_delta":    _delta(s.item3_current or 0, s.item3_previous or 0),
        "item4_current":  s.item4_current or 0,
        "item4_previous": s.item4_previous or 0,
        "item4_delta":    _delta(s.item4_current or 0, s.item4_previous or 0),
        "item5_current":  s.item5_current or 0,
        "item5_previous": s.item5_previous or 0,
        "item5_delta":    _delta(s.item5_current or 0, s.item5_previous or 0),
        "item6_current":  s.item6_current or 0,
        "item6_previous": s.item6_previous or 0,
        "item6_delta":    _delta(s.item6_current or 0, s.item6_previous or 0),
        "item7_current":  s.item7_current or 0,
        "item7_previous": s.item7_previous or 0,
        "item7_delta":    _delta(s.item7_current or 0, s.item7_previous or 0),
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

    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp
    from app.services.pdf_generator import generate_uph_stat_report

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
            "organization_type": "local_ump",
        }

    pdf_bytes = generate_uph_stat_report(
        org_data    = org_data,
        fiscal_year = year,
        stat        = _stat_out(stat),
    )

    filename = f"Relatorio_Estatistica_UPH_{year}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


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
