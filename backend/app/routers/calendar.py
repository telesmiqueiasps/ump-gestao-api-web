from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import datetime

from app.db.session import get_db
from app.models.calendar_event import CalendarEvent
from app.models.local_ump import LocalUmp
from app.models.user import User
from app.models.enums import OrgType, BoardRole
from app.core.dependencies import get_current_user, require_local_or_federation, require_roles

router = APIRouter()


class CalendarEventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    start_date: datetime.datetime
    end_date: datetime.datetime
    location: Optional[str] = None


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[datetime.datetime] = None
    end_date: Optional[datetime.datetime] = None
    location: Optional[str] = None


def _to_out(event: CalendarEvent) -> dict:
    organizer_name = ""
    organizer_type = "federation"
    if event.local_ump_id:
        organizer_name = event.local_ump.name if event.local_ump else "UMP Local"
        organizer_type = "local_ump"
    else:
        organizer_name = event.federation.name if event.federation else "Federação"
        organizer_type = "federation"

    return {
        "id": str(event.id),
        "federation_id": str(event.federation_id),
        "local_ump_id": str(event.local_ump_id) if event.local_ump_id else None,
        "title": event.title,
        "description": event.description,
        "start_date": event.start_date.isoformat() if event.start_date else None,
        "end_date": event.end_date.isoformat() if event.end_date else None,
        "location": event.location,
        "created_by": str(event.created_by),
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "organizer_name": organizer_name,
        "organizer_type": organizer_type
    }


@router.get("/")
def list_calendar_events(
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db)
):
    # Determine the federation context
    if current_user.organization_type == OrgType.federation:
        federation_id = current_user.organization_id
    else:
        local_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
        if not local_ump:
            raise HTTPException(status_code=404, detail="UMP Local não encontrada")
        federation_id = local_ump.federation_id

    # Retrieve all events belonging to this federation (including all its local UMPs)
    events = db.query(CalendarEvent).filter(
        CalendarEvent.federation_id == federation_id
    ).order_by(CalendarEvent.start_date.asc()).all()

    return [_to_out(event) for event in events]


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_calendar_event(
    payload: CalendarEventCreate,
    current_user: User = Depends(require_roles(
        BoardRole.presidente,
        BoardRole.vice_presidente,
        BoardRole.primeiro_secretario,
        BoardRole.segundo_secretario,
        BoardRole.secretario_executivo
    )),
    db: Session = Depends(get_db)
):
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="A data de término não pode ser anterior à data de início")

    # Resolve federation and local context
    if current_user.organization_type == OrgType.federation:
        federation_id = current_user.organization_id
        local_ump_id = None
    else:
        local_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
        if not local_ump:
            raise HTTPException(status_code=404, detail="UMP Local não encontrada")
        federation_id = local_ump.federation_id
        local_ump_id = current_user.organization_id

    event = CalendarEvent(
        federation_id=federation_id,
        local_ump_id=local_ump_id,
        title=payload.title,
        description=payload.description,
        start_date=payload.start_date,
        end_date=payload.end_date,
        location=payload.location,
        created_by=current_user.id
    )

    db.add(event)
    db.commit()
    db.refresh(event)
    return _to_out(event)


@router.put("/{event_id}")
def update_calendar_event(
    event_id: UUID,
    payload: CalendarEventUpdate,
    current_user: User = Depends(require_roles(
        BoardRole.presidente,
        BoardRole.vice_presidente,
        BoardRole.primeiro_secretario,
        BoardRole.segundo_secretario,
        BoardRole.secretario_executivo
    )),
    db: Session = Depends(get_db)
):
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Programação não encontrada")

    # Access control: Must belong to the exact same organization that created the event
    if current_user.organization_type == OrgType.federation:
        if event.local_ump_id is not None or event.federation_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Você não tem permissão para editar eventos desta organização")
    else:
        if event.local_ump_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Você não tem permissão para editar eventos desta organização")

    # Update fields
    update_data = payload.model_dump(exclude_none=True)
    
    # Check updated dates validity
    new_start = update_data.get("start_date", event.start_date)
    new_end = update_data.get("end_date", event.end_date)
    if new_end < new_start:
        raise HTTPException(status_code=400, detail="A data de término não pode ser anterior à data de início")

    for field, value in update_data.items():
        setattr(event, field, value)

    db.commit()
    db.refresh(event)
    return _to_out(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_event(
    event_id: UUID,
    current_user: User = Depends(require_roles(
        BoardRole.presidente,
        BoardRole.vice_presidente,
        BoardRole.primeiro_secretario,
        BoardRole.segundo_secretario,
        BoardRole.secretario_executivo
    )),
    db: Session = Depends(get_db)
):
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Programação não encontrada")

    # Access control: Must belong to the exact same organization that created the event
    if current_user.organization_type == OrgType.federation:
        if event.local_ump_id is not None or event.federation_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Você não tem permissão para excluir eventos desta organização")
    else:
        if event.local_ump_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Você não tem permissão para excluir eventos desta organização")

    db.delete(event)
    db.commit()
    return None
