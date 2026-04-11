import io
import os
import re
import datetime

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.models.activity_report import ActivityReport, Activity, ActivityPhoto
from app.models.board import BoardMember
from app.models.activity_secretary import ActivitySecretary
from app.models.user import User
from app.core.dependencies import get_current_user
from app.services.storage import upload_file, delete_folder, _get_client
from app.core.config import get_settings

router = APIRouter()

ROLE_LABELS = {
    'presidente':              'Presidente',
    'vice_presidente':         'Vice-presidente',
    '1_secretario':            '1º Secretário (a)',
    '2_secretario':            '2º Secretário (a)',
    'tesoureiro':              'Tesoureiro (a)',
    'secretario_executivo':    'Sec. Executivo (a)',
    'secretario_presbiterial': 'Secretário (a)',
    'conselheiro':             'Conselheiro (a)',
}

ROLE_ORDER = [
    'presidente', 'vice_presidente', 'secretario_executivo',
    '1_secretario', '2_secretario', 'tesoureiro',
    'secretario_presbiterial', 'conselheiro',
]


def _activity_out(a: Activity) -> dict:
    return {
        "id":              str(a.id),
        "organization_id": str(a.organization_id),
        "fiscal_year":     a.fiscal_year,
        "title":           a.title,
        "description":     a.description,
        "start_date":      a.start_date.strftime('%Y-%m-%d') if a.start_date else None,
        "end_date":        a.end_date.strftime('%Y-%m-%d') if a.end_date else None,
        "photos": [
            {
                "id":            str(p.id),
                "photo_url":     p.photo_url,
                "photo_key":     p.photo_key,
                "display_order": p.display_order,
            }
            for p in a.photos
        ],
    }


def _report_out(r: ActivityReport) -> dict:
    return {
        "id":              str(r.id),
        "organization_id": str(r.organization_id),
        "fiscal_year":     r.fiscal_year,
        "status":          r.status,
        "section_intro":               r.section_intro,
        "section_raio_x_strong":       r.section_raio_x_strong,
        "section_raio_x_weak":         r.section_raio_x_weak,
        "section_raio_x_achieved":     r.section_raio_x_achieved,
        "section_raio_x_not_achieved": r.section_raio_x_not_achieved,
        "section_final_word":          r.section_final_word,
        "report_url":  r.report_url,
        "updated_at":  r.updated_at.isoformat() if r.updated_at else None,
    }


def _get_org_data(db, current_user):
    org_type = current_user.organization_type.value \
        if hasattr(current_user.organization_type, 'value') \
        else str(current_user.organization_type)

    if org_type == 'federation':
        from app.models.federation import Federation
        org_obj = db.query(Federation).filter(
            Federation.id == current_user.organization_id).first()
        return {
            "name":            org_obj.name if org_obj else '',
            "presbytery_name": org_obj.presbytery_name if org_obj else '',
            "synodal_name":    getattr(org_obj, 'synodal_name', '') or '',
            "logo_url":        org_obj.logo_url if org_obj else None,
            "theme_color":     getattr(org_obj, 'theme_color', '#1a2a6c') or '#1a2a6c',
            "organization_type": org_type,
        }
    else:
        from app.models.local_ump import LocalUmp
        org_obj = db.query(LocalUmp).filter(
            LocalUmp.id == current_user.organization_id).first()
        return {
            "name":            org_obj.name if org_obj else '',
            "presbytery_name": org_obj.presbytery_name if org_obj else '',
            "synodal_name":    '',
            "logo_url":        org_obj.logo_url if org_obj else None,
            "theme_color":     getattr(org_obj, 'theme_color', '#1a2a6c') or '#1a2a6c',
            "organization_type": org_type,
        }


def _get_board_data(db, current_user, year):
    board_list = db.query(BoardMember).filter(
        BoardMember.organization_id == current_user.organization_id,
        BoardMember.fiscal_year == year,
        BoardMember.is_active == True,
    ).all()

    def _order(b):
        rv = b.role.value if hasattr(b.role, 'value') else str(b.role)
        return ROLE_ORDER.index(rv) if rv in ROLE_ORDER else 99

    result = []
    for b in sorted(board_list, key=_order):
        rv = b.role.value if hasattr(b.role, 'value') else str(b.role)
        result.append({
            "role_label":  ROLE_LABELS.get(rv, rv),
            "member_name": b.member_name,
            "contact":     b.contact or '',
        })
    return result


def _get_act_secs_data(db, current_user, year):
    secs = db.query(ActivitySecretary).filter(
        ActivitySecretary.organization_id == current_user.organization_id,
        ActivitySecretary.fiscal_year == year,
        ActivitySecretary.is_active == True,
    ).order_by(ActivitySecretary.activity_name).all()
    return [
        {"activity_name": s.activity_name, "member_name": s.member_name, "contact": s.contact or ''}
        for s in secs
    ]


def _get_logos(org_data):
    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name
    b2 = _get_client()

    logo_bytes = None
    if org_data.get('logo_url'):
        match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', org_data['logo_url'])
        if not match:
            match = re.search(rf'/{re.escape(bucket)}/(.+)$', org_data['logo_url'])
        if match:
            try:
                resp = b2.get_object(Bucket=bucket, Key=match.group(1))
                logo_bytes = resp['Body'].read()
            except Exception:
                pass

    ipb_logo_bytes = None
    try:
        ipb_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'ipb_logo.png')
        if os.path.exists(ipb_path):
            with open(ipb_path, 'rb') as f:
                ipb_logo_bytes = f.read()
    except Exception:
        pass

    return logo_bytes, ipb_logo_bytes


def _build_activities_data(activities, with_photos=True):
    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name
    b2 = _get_client() if with_photos else None

    result = []
    for act in activities:
        photos_bytes = []
        if with_photos:
            for photo in act.photos:
                try:
                    resp = b2.get_object(Bucket=bucket, Key=photo.photo_key)
                    photos_bytes.append(resp['Body'].read())
                except Exception:
                    photos_bytes.append(None)

        result.append({
            "id":          str(act.id),
            "title":       act.title,
            "description": act.description or '',
            "start_date":  act.start_date.strftime('%Y-%m-%d'),
            "end_date":    act.end_date.strftime('%Y-%m-%d') if act.end_date else None,
            "photos_bytes": photos_bytes,
        })
    return result


# ── Relatório (único por ano) ─────────────────────────────────

class ReportUpdate(BaseModel):
    section_intro:               Optional[str] = None
    section_raio_x_strong:       Optional[str] = None
    section_raio_x_weak:         Optional[str] = None
    section_raio_x_achieved:     Optional[str] = None
    section_raio_x_not_achieved: Optional[str] = None
    section_final_word:          Optional[str] = None
    status:                      Optional[str] = None


@router.get("/report/{year}")
def get_or_create_report(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ActivityReport).filter(
        ActivityReport.organization_id == current_user.organization_id,
        ActivityReport.fiscal_year == year,
    ).first()

    if not report:
        report = ActivityReport(
            organization_id = current_user.organization_id,
            fiscal_year     = year,
            status          = 'draft',
            created_by      = current_user.id,
        )
        db.add(report)
        db.commit()
        db.refresh(report)

    return _report_out(report)


@router.put("/report/{year}")
def update_report(
    year: int,
    payload: ReportUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ActivityReport).filter(
        ActivityReport.organization_id == current_user.organization_id,
        ActivityReport.fiscal_year == year,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    if report.status == 'published' and payload.status != 'draft':
        raise HTTPException(status_code=400,
            detail="Relatório publicado. Despublique para editar.")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(report, field, value)
    db.commit()
    db.refresh(report)
    return _report_out(report)


# ── Atividades ────────────────────────────────────────────────

class ActivityCreate(BaseModel):
    title:       str
    description: Optional[str] = None
    start_date:  str
    end_date:    Optional[str] = None
    fiscal_year: Optional[int] = None


class ActivityUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    start_date:  Optional[str] = None
    end_date:    Optional[str] = None


@router.get("/activities/{year}")
def list_activities(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    acts = db.query(Activity).filter(
        Activity.organization_id == current_user.organization_id,
        Activity.fiscal_year == year,
    ).order_by(Activity.start_date).all()
    return [_activity_out(a) for a in acts]


@router.post("/activities", status_code=status.HTTP_201_CREATED)
def create_activity(
    payload: ActivityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    year = payload.fiscal_year or datetime.date.today().year
    act = Activity(
        organization_id = current_user.organization_id,
        fiscal_year     = year,
        title           = payload.title,
        description     = payload.description,
        start_date      = datetime.date.fromisoformat(payload.start_date),
        end_date        = datetime.date.fromisoformat(payload.end_date) if payload.end_date else None,
    )
    db.add(act)
    db.commit()
    db.refresh(act)
    return _activity_out(act)


@router.put("/activities/{activity_id}")
def update_activity(
    activity_id: UUID,
    payload: ActivityUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    act = db.query(Activity).filter(
        Activity.id == activity_id,
        Activity.organization_id == current_user.organization_id,
    ).first()
    if not act:
        raise HTTPException(status_code=404, detail="Atividade não encontrada")

    if payload.title is not None:
        act.title = payload.title
    if payload.description is not None:
        act.description = payload.description
    if payload.start_date:
        act.start_date = datetime.date.fromisoformat(payload.start_date)
    if payload.end_date is not None:
        act.end_date = datetime.date.fromisoformat(payload.end_date) if payload.end_date else None

    db.commit()
    db.refresh(act)
    return _activity_out(act)


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(
    activity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    act = db.query(Activity).filter(
        Activity.id == activity_id,
        Activity.organization_id == current_user.organization_id,
    ).first()
    if not act:
        raise HTTPException(status_code=404, detail="Atividade não encontrada")

    for photo in act.photos:
        try:
            folder = '/'.join(photo.photo_key.split('/')[:-1]) + '/'
            delete_folder(folder)
        except Exception:
            pass

    db.delete(act)
    db.commit()


# ── Fotos das atividades ──────────────────────────────────────

@router.post("/activities/{activity_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_activity_photo(
    activity_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    act = db.query(Activity).filter(
        Activity.id == activity_id,
        Activity.organization_id == current_user.organization_id,
    ).first()
    if not act:
        raise HTTPException(status_code=404, detail="Atividade não encontrada")

    if len(act.photos) >= 4:
        raise HTTPException(status_code=400, detail="Máximo de 4 fotos por atividade")

    allowed = ["image/png", "image/jpeg", "image/webp"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Formato inválido. Use PNG, JPG ou WEBP.")

    contents = await file.read()
    if len(contents) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Máx 15MB.")

    order = len(act.photos)
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename or 'photo')
    key = f"activities/{current_user.organization_id}/{activity_id}/{order}_{safe_name}"
    url = upload_file(contents, key, file.content_type)

    photo = ActivityPhoto(
        activity_id     = activity_id,
        organization_id = current_user.organization_id,
        photo_url       = url,
        photo_key       = key,
        display_order   = order,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    return {
        "id":            str(photo.id),
        "photo_url":     photo.photo_url,
        "photo_key":     photo.photo_key,
        "display_order": photo.display_order,
    }


@router.delete("/activities/{activity_id}/photos/{photo_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_activity_photo(
    activity_id: UUID,
    photo_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    photo = db.query(ActivityPhoto).filter(
        ActivityPhoto.id == photo_id,
        ActivityPhoto.activity_id == activity_id,
        ActivityPhoto.organization_id == current_user.organization_id,
    ).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Foto não encontrada")

    try:
        folder = '/'.join(photo.photo_key.split('/')[:-1]) + '/'
        delete_folder(folder)
    except Exception:
        pass

    db.delete(photo)
    db.commit()


# ── Gerar PDF e publicar ──────────────────────────────────────

@router.post("/report/{year}/publish")
def publish_report(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ActivityReport).filter(
        ActivityReport.organization_id == current_user.organization_id,
        ActivityReport.fiscal_year == year,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    activities = db.query(Activity).filter(
        Activity.organization_id == current_user.organization_id,
        Activity.fiscal_year == year,
    ).order_by(Activity.start_date).all()

    org_data      = _get_org_data(db, current_user)
    board_data    = _get_board_data(db, current_user, year)
    act_secs_data = _get_act_secs_data(db, current_user, year)
    logo_bytes, ipb_logo_bytes = _get_logos(org_data)
    activities_data = _build_activities_data(activities, with_photos=True)

    from app.services.pdf_generator import generate_activity_report
    pdf_bytes = generate_activity_report(
        org_data       = org_data,
        fiscal_year    = year,
        board_data     = board_data,
        act_secs_data  = act_secs_data,
        activities     = activities_data,
        report         = {
            "section_intro":              report.section_intro or '',
            "section_raio_x_strong":      report.section_raio_x_strong or '',
            "section_raio_x_weak":        report.section_raio_x_weak or '',
            "section_raio_x_achieved":    report.section_raio_x_achieved or '',
            "section_raio_x_not_achieved":report.section_raio_x_not_achieved or '',
            "section_final_word":         report.section_final_word or '',
        },
        logo_bytes     = logo_bytes,
        ipb_logo_bytes = ipb_logo_bytes,
    )

    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name
    key = f"activity-reports/{current_user.organization_id}/{year}/relatorio_atividades_{year}.pdf"
    url = upload_file(pdf_bytes, key, 'application/pdf')

    # Limpa fotos originais do B2 após publicação
    for act in activities:
        for photo in act.photos:
            try:
                folder = '/'.join(photo.photo_key.split('/')[:-1]) + '/'
                delete_folder(folder)
            except Exception:
                pass
        db.query(ActivityPhoto).filter(
            ActivityPhoto.activity_id == act.id
        ).delete(synchronize_session=False)

    report.report_url = url
    report.status = 'published'
    db.commit()

    return {"detail": "Relatório publicado com sucesso", "report_url": url}


@router.get("/report/{year}/preview-pdf")
def preview_report_pdf(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ActivityReport).filter(
        ActivityReport.organization_id == current_user.organization_id,
        ActivityReport.fiscal_year == year,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    activities = db.query(Activity).filter(
        Activity.organization_id == current_user.organization_id,
        Activity.fiscal_year == year,
    ).order_by(Activity.start_date).all()

    org_data      = _get_org_data(db, current_user)
    board_data    = _get_board_data(db, current_user, year)
    act_secs_data = _get_act_secs_data(db, current_user, year)
    logo_bytes, ipb_logo_bytes = _get_logos(org_data)
    activities_data = _build_activities_data(activities, with_photos=True)

    from app.services.pdf_generator import generate_activity_report
    pdf_bytes = generate_activity_report(
        org_data      = org_data,
        fiscal_year   = year,
        board_data    = board_data,
        act_secs_data = act_secs_data,
        activities    = activities_data,
        report        = {
            "section_intro":              report.section_intro or '',
            "section_raio_x_strong":      report.section_raio_x_strong or '',
            "section_raio_x_weak":        report.section_raio_x_weak or '',
            "section_raio_x_achieved":    report.section_raio_x_achieved or '',
            "section_raio_x_not_achieved":report.section_raio_x_not_achieved or '',
            "section_final_word":         report.section_final_word or '',
        },
        logo_bytes    = logo_bytes,
        ipb_logo_bytes= ipb_logo_bytes,
    )

    filename = f"Previa_Relatorio_Atividades_{year}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/report/{year}/published-url")
def get_published_url(
    year: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ActivityReport).filter(
        ActivityReport.organization_id == current_user.organization_id,
        ActivityReport.fiscal_year == year,
        ActivityReport.status == 'published',
    ).first()
    if not report or not report.report_url:
        raise HTTPException(status_code=404, detail="Relatório publicado não encontrado")

    from app.services.storage import get_presigned_url
    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name
    match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', report.report_url)
    if not match:
        match = re.search(rf'/{re.escape(bucket)}/(.+)$', report.report_url)
    if not match:
        raise HTTPException(status_code=400, detail="URL inválida")

    url = get_presigned_url(match.group(1), expires_in=3600)
    return {"url": url}
