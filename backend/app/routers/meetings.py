from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
import datetime

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
        "started_at": m.started_at.isoformat() if m.started_at else None,
        "ended_at": m.ended_at.isoformat() if m.ended_at else None,
        "location_name": m.location_name,
        "city": m.city,
        "state": m.state,
        "address": m.address,
        "meeting_president": m.meeting_president,
        "status": m.status,
        "section_devotional": m.section_devotional,
        "section_agenda": m.section_agenda,
        "section_resolutions": m.section_resolutions,
        "section_observations": m.section_observations,
        "section_closing": m.section_closing,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "counts": {
            "total_present": total_present,
            "board": board_present,
            "activity_secretaries": act_sec_present,
            "delegates": delegate_present,
            "members": member_present,
            "visitors": visitor_present,
            "presbyterial": presb_present,
        },
        "attendees": [
            {
                "id": str(a.id),
                "attendee_type": a.attendee_type,
                "name": a.name,
                "local_name": a.local_name,
                "observation": a.observation,
                "is_present": a.is_present,
                "source_id": str(a.source_id) if a.source_id else None,
            }
            for a in sorted(attendees, key=lambda x: (x.attendee_type, x.name))
        ],
    }


class MeetingCreate(BaseModel):
    record_number: str
    meeting_type: str
    title: Optional[str] = None
    started_at: datetime.datetime
    ended_at: Optional[datetime.datetime] = None
    location_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = 'PB'
    address: Optional[str] = None
    meeting_president: Optional[str] = None


class MeetingUpdate(BaseModel):
    record_number: Optional[str] = None
    meeting_type: Optional[str] = None
    title: Optional[str] = None
    started_at: Optional[datetime.datetime] = None
    ended_at: Optional[datetime.datetime] = None
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
        started_at        = payload.started_at,
        ended_at          = payload.ended_at,
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

    for field, value in payload.model_dump(exclude_none=True).items():
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
    """Carrega diretoria e secretários de atividades automaticamente"""
    m = db.query(Meeting).filter(
        Meeting.id == meeting_id,
        Meeting.organization_id == current_user.organization_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Reunião não encontrada")

    year = m.started_at.year
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
        "id": str(a.id),
        "attendee_type": a.attendee_type,
        "name": a.name,
        "local_name": a.local_name,
        "observation": a.observation,
        "is_present": a.is_present,
        "source_id": str(a.source_id) if a.source_id else None,
    }


@router.put("/{meeting_id}/attendees/{attendee_id}")
def update_attendee(
    meeting_id: UUID,
    attendee_id: UUID,
    payload: AttendeeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    a = db.query(MeetingAttendee).filter(
        MeetingAttendee.id == attendee_id,
        MeetingAttendee.meeting_id == meeting_id,
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Presente não encontrado")
    db.delete(a)
    db.commit()
