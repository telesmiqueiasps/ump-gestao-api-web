import io
import re
import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.models.meeting import Meeting, MeetingAttendee
from app.models.board import BoardMember
from app.models.activity_secretary import ActivitySecretary
from app.models.member import Member
from app.models.user import User
from app.core.dependencies import get_current_user

router = APIRouter()

MEETING_TYPES = [
    'Plenária',
    'Reunião Ordinária',
    'Congresso',
    'Comissão Executiva',
    'Assembleia',
    'Reunião Extraordinária',
    'Outro',
]

ROLE_LABELS = {
    'presidente':              'Presidente',
    'vice_presidente':         'Vice-Presidente',
    '1_secretario':            '1º Secretário(a)',
    '2_secretario':            '2º Secretário(a)',
    'tesoureiro':              'Tesoureiro(a)',
    'secretario_executivo':    'Secretário(a) Executivo(a)',
    'secretario_presbiterial': 'Secretário Presbiterial',
    'conselheiro':             'Conselheiro(a)',
}


# ── Helpers ───────────────────────────────────────────────────

def _parse_dt(dt_str: Optional[str]) -> Optional[datetime.datetime]:
    """Parse ISO string sem timezone para evitar conversão UTC."""
    if not dt_str:
        return None
    try:
        # Remove sufixo de timezone (Z, +00:00, -03:00, etc.) e parseia como local
        s = dt_str.strip()
        # Remove Z ou offset no final
        s = re.sub(r'([+-]\d{2}:\d{2}|Z)$', '', s)
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def _fmt_dt(dt: Optional[datetime.datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.strftime('%Y-%m-%dT%H:%M:%S')


def _meeting_out(m: Meeting) -> dict:
    attendees = m.attendees or []

    board_present    = sum(1 for a in attendees if a.attendee_type == 'board' and a.is_present)
    act_sec_present  = sum(1 for a in attendees if a.attendee_type == 'activity_secretary' and a.is_present)
    delegate_present = sum(1 for a in attendees if a.attendee_type == 'delegate' and a.is_present)
    member_present   = sum(1 for a in attendees if a.attendee_type == 'member' and a.is_present)
    visitor_present  = sum(1 for a in attendees if a.attendee_type == 'visitor' and a.is_present)
    presb_present    = sum(1 for a in attendees if a.attendee_type == 'presbyterial' and a.is_present)
    total_present    = sum(1 for a in attendees if a.is_present)

    return {
        "id": str(m.id),
        "organization_id": str(m.organization_id),
        "organization_type": m.organization_type,
        "record_number": m.record_number,
        "meeting_type": m.meeting_type,
        "title": m.title,
        "started_at": _fmt_dt(m.started_at),
        "ended_at":   _fmt_dt(m.ended_at),
        "location_name": m.location_name,
        "city": m.city,
        "state": m.state,
        "address": m.address,
        "meeting_president": m.meeting_president,
        "status": m.status,
        "section_devotional":   m.section_devotional,
        "section_agenda":       m.section_agenda,
        "section_resolutions":  m.section_resolutions,
        "section_observations": m.section_observations,
        "section_closing":      m.section_closing,
        "created_at": _fmt_dt(m.created_at),
        "updated_at": _fmt_dt(m.updated_at),
        "counts": {
            "total_present":        total_present,
            "board":                board_present,
            "activity_secretaries": act_sec_present,
            "delegates":            delegate_present,
            "members":              member_present,
            "visitors":             visitor_present,
            "presbyterial":         presb_present,
        },
        "attendees": [
            {
                "id":            str(a.id),
                "attendee_type": a.attendee_type,
                "name":          a.name,
                "local_name":    a.local_name,
                "observation":   a.observation,
                "is_present":    a.is_present,
                "source_id":     str(a.source_id) if a.source_id else None,
            }
            for a in sorted(attendees, key=lambda x: (x.attendee_type, x.name))
        ],
    }


# ── Pydantic schemas ──────────────────────────────────────────

class MeetingCreate(BaseModel):
    record_number: str
    meeting_type: str
    title: Optional[str] = None
    started_at: str                   # ISO string sem conversão de tz
    ended_at: Optional[str] = None
    location_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = 'PB'
    address: Optional[str] = None
    meeting_president: Optional[str] = None


class MeetingUpdate(BaseModel):
    record_number: Optional[str] = None
    meeting_type: Optional[str] = None
    title: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    location_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    meeting_president: Optional[str] = None
    status: Optional[str] = None
    section_devotional: Optional[str] = None
    section_agenda: Optional[str] = None
    section_resolutions: Optional[str] = None
    section_observations: Optional[str] = None
    section_closing: Optional[str] = None


class AttendeeCreate(BaseModel):
    attendee_type: str
    name: str
    local_name: Optional[str] = None
    observation: Optional[str] = None
    is_present: bool = True
    source_id: Optional[UUID] = None


class AttendeeUpdate(BaseModel):
    is_present: Optional[bool] = None
    observation: Optional[str] = None


# ── CRUD de reuniões ──────────────────────────────────────────

@router.get("/types")
def get_meeting_types():
    return MEETING_TYPES


@router.get("/prefill")
def get_prefill_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retorna dados para pré-preencher a reunião (local e presidente)."""
    from app.models.local_ump import LocalUmp

    result = {}
    year = datetime.date.today().year
    org_type = current_user.organization_type.value \
        if hasattr(current_user.organization_type, 'value') \
        else str(current_user.organization_type)

    if org_type == 'local_ump':
        local = db.query(LocalUmp).filter(
            LocalUmp.id == current_user.organization_id
        ).first()
        if local:
            result['location_name'] = local.church_name or ''
            result['city'] = ''
            result['address'] = ''
            result['state'] = 'PB'

    # Busca presidente da diretoria do ano atual
    board = db.query(BoardMember).filter(
        BoardMember.organization_id == current_user.organization_id,
        BoardMember.fiscal_year == year,
        BoardMember.is_active == True,
    ).all()
    for b in board:
        role_val = b.role.value if hasattr(b.role, 'value') else str(b.role)
        if role_val == 'presidente':
            result['meeting_president'] = b.member_name
            break

    return result


@router.get("/")
def list_meetings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meetings = db.query(Meeting).filter(
        Meeting.organization_id == current_user.organization_id,
    ).order_by(Meeting.started_at.desc()).all()
    return [_meeting_out(m) for m in meetings]


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_meeting(
    payload: MeetingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meeting = Meeting(
        organization_id   = current_user.organization_id,
        organization_type = current_user.organization_type.value
            if hasattr(current_user.organization_type, 'value')
            else str(current_user.organization_type),
        record_number     = payload.record_number,
        meeting_type      = payload.meeting_type,
        title             = payload.title,
        started_at        = _parse_dt(payload.started_at),
        ended_at          = _parse_dt(payload.ended_at),
        location_name     = payload.location_name,
        city              = payload.city,
        state             = payload.state or 'PB',
        address           = payload.address,
        meeting_president = payload.meeting_president,
        created_by        = current_user.id,
        status            = 'draft',
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return _meeting_out(meeting)


@router.get("/{meeting_id}")
def get_meeting(
    meeting_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")
    return _meeting_out(m)


@router.put("/{meeting_id}")
def update_meeting(
    meeting_id: UUID,
    payload: MeetingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    # Bloqueio: reunião publicada só pode mudar o status
    if m.status == 'published':
        update_data = payload.model_dump(exclude_none=True)
        allowed_fields = {'status'}
        if not all(k in allowed_fields for k in update_data.keys()):
            raise HTTPException(
                status_code=400,
                detail="Reunião publicada não pode ser editada. Despublique primeiro."
            )

    update_data = payload.model_dump(exclude_none=True)

    # Trata campos de datetime separadamente
    for dt_field in ('started_at', 'ended_at'):
        if dt_field in update_data:
            update_data[dt_field] = _parse_dt(update_data[dt_field])

    for field, value in update_data.items():
        setattr(m, field, value)

    db.commit()
    db.refresh(m)
    return _meeting_out(m)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(
    meeting_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")
    db.delete(m)
    db.commit()


# ── Presentes: pré-carregar da diretoria/secretários/sócios ──

@router.post("/{meeting_id}/load-attendees")
def load_default_attendees(
    meeting_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Carrega diretoria e secretários de atividades automaticamente."""
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    if m.status == 'published':
        raise HTTPException(
            status_code=400,
            detail="Reunião publicada não pode ser alterada. Despublique primeiro."
        )

    year = m.started_at.year if m.started_at else datetime.date.today().year
    existing_types = {a.attendee_type for a in m.attendees}
    added = []

    # Diretoria
    if 'board' not in existing_types:
        board_members = db.query(BoardMember).filter(
            BoardMember.organization_id == current_user.organization_id,
            BoardMember.fiscal_year == year,
            BoardMember.is_active == True,
        ).all()
        for b in board_members:
            role = b.role.value if hasattr(b.role, 'value') else str(b.role)
            role_label = ROLE_LABELS.get(role, role)
            atype = 'presbyterial' if role == 'secretario_presbiterial' else 'board'
            a = MeetingAttendee(
                meeting_id    = m.id,
                attendee_type = atype,
                name          = f"{role_label} - {b.member_name}",
                source_id     = b.id,
                is_present    = True,
            )
            db.add(a)
            added.append(a)

    # Secretários de atividades
    if 'activity_secretary' not in existing_types:
        secs = db.query(ActivitySecretary).filter(
            ActivitySecretary.organization_id == current_user.organization_id,
            ActivitySecretary.fiscal_year == year,
            ActivitySecretary.is_active == True,
        ).all()
        for s in secs:
            a = MeetingAttendee(
                meeting_id    = m.id,
                attendee_type = 'activity_secretary',
                name          = f"{s.activity_name} - {s.member_name}",
                source_id     = s.id,
                is_present    = True,
            )
            db.add(a)
            added.append(a)

    # Para UMP Local: carrega sócios
    if 'member' not in existing_types and m.organization_type == 'local_ump':
        members = db.query(Member).filter(
            Member.local_ump_id == current_user.organization_id,
            Member.is_active == True,
        ).order_by(Member.full_name).all()
        for mb in members:
            a = MeetingAttendee(
                meeting_id    = m.id,
                attendee_type = 'member',
                name          = mb.full_name,
                source_id     = mb.id,
                is_present    = True,
            )
            db.add(a)
            added.append(a)

    db.commit()
    db.refresh(m)
    return {"added": len(added), "meeting": _meeting_out(m)}


# ── CRUD de presentes ─────────────────────────────────────────

@router.post("/{meeting_id}/attendees", status_code=status.HTTP_201_CREATED)
def add_attendee(
    meeting_id: UUID,
    payload: AttendeeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    if m.status == 'published':
        raise HTTPException(
            status_code=400,
            detail="Reunião publicada não pode ser alterada. Despublique primeiro."
        )

    a = MeetingAttendee(
        meeting_id    = m.id,
        attendee_type = payload.attendee_type,
        name          = payload.name,
        local_name    = payload.local_name,
        observation   = payload.observation,
        is_present    = payload.is_present,
        source_id     = payload.source_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {
        "id":            str(a.id),
        "attendee_type": a.attendee_type,
        "name":          a.name,
        "local_name":    a.local_name,
        "observation":   a.observation,
        "is_present":    a.is_present,
        "source_id":     str(a.source_id) if a.source_id else None,
    }


@router.put("/{meeting_id}/attendees/{attendee_id}")
def update_attendee(
    meeting_id: UUID,
    attendee_id: UUID,
    payload: AttendeeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Verifica se a reunião pertence à organização
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    if m.status == 'published':
        raise HTTPException(
            status_code=400,
            detail="Reunião publicada não pode ser alterada. Despublique primeiro."
        )

    a = db.query(MeetingAttendee).filter(
        MeetingAttendee.id == attendee_id,
        MeetingAttendee.meeting_id == meeting_id,
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Presente não encontrado")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(a, field, value)
    db.commit()
    return {"id": str(a.id), "is_present": a.is_present}


@router.delete("/{meeting_id}/attendees/{attendee_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_attendee(
    meeting_id: UUID,
    attendee_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    if m.status == 'published':
        raise HTTPException(
            status_code=400,
            detail="Reunião publicada não pode ser alterada. Despublique primeiro."
        )

    a = db.query(MeetingAttendee).filter(
        MeetingAttendee.id == attendee_id,
        MeetingAttendee.meeting_id == meeting_id,
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Presente não encontrado")
    db.delete(a)
    db.commit()


# ── PDF ───────────────────────────────────────────────────────

@router.get("/{meeting_id}/pdf")
def generate_meeting_pdf(
    meeting_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import os
    from app.services.pdf_generator import generate_meeting_report
    from app.services.storage import _get_client
    from app.core.config import get_settings
    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp

    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    settings_obj = get_settings()
    bucket = settings_obj.b2_bucket_name
    b2 = _get_client()

    org_type = current_user.organization_type.value \
        if hasattr(current_user.organization_type, 'value') \
        else str(current_user.organization_type)

    if org_type == 'federation':
        org_obj = db.query(Federation).filter(
            Federation.id == current_user.organization_id).first()
    else:
        org_obj = db.query(LocalUmp).filter(
            LocalUmp.id == current_user.organization_id).first()

    org_data = {
        "name":             getattr(org_obj, 'name', '') or '',
        "presbytery_name":  getattr(org_obj, 'presbytery_name', '') or '',
        "logo_url":         getattr(org_obj, 'logo_url', None),
        "theme_color":      getattr(org_obj, 'theme_color', '#1a2a6c') or '#1a2a6c',
    }

    # Logo da organização via B2
    logo_bytes = None
    if org_data.get('logo_url'):
        try:
            match = re.search(rf'/file/{re.escape(bucket)}/(.+)$', org_data['logo_url'])
            if not match:
                match = re.search(rf'/{re.escape(bucket)}/(.+)$', org_data['logo_url'])
            if match:
                resp = b2.get_object(Bucket=bucket, Key=match.group(1))
                logo_bytes = resp['Body'].read()
        except Exception:
            pass

    # Logo IPB do diretório assets do backend
    ipb_logo_bytes = None
    try:
        ipb_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'ipb_logo.png')
        if os.path.exists(ipb_path):
            with open(ipb_path, 'rb') as f:
                ipb_logo_bytes = f.read()
    except Exception:
        pass

    meeting_data = {
        "record_number":     m.record_number,
        "meeting_type":      m.meeting_type,
        "title":             m.title,
        "started_at":        _fmt_dt(m.started_at),
        "ended_at":          _fmt_dt(m.ended_at),
        "location_name":     m.location_name,
        "city":              m.city,
        "state":             m.state,
        "address":           m.address,
        "meeting_president": m.meeting_president,
        "section_devotional":   m.section_devotional,
        "section_agenda":       m.section_agenda,
        "section_resolutions":  m.section_resolutions,
        "section_observations": m.section_observations,
        "section_closing":      m.section_closing,
        "attendees": [
            {
                "id":            str(a.id),
                "attendee_type": a.attendee_type,
                "name":          a.name,
                "local_name":    a.local_name,
                "observation":   a.observation,
                "is_present":    a.is_present,
            }
            for a in m.attendees
        ],
        "counts": {},
    }

    pdf_bytes = generate_meeting_report(
        meeting_data=meeting_data,
        org_data=org_data,
        logo_bytes=logo_bytes,
        ipb_logo_bytes=ipb_logo_bytes,
        theme_color=org_data.get('theme_color', '#1a2a6c'),
    )

    safe_record = (m.record_number or 'sem-numero').replace('/', '-').replace(' ', '_')
    filename = f"Registro_Atos_{safe_record}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
