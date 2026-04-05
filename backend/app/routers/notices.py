from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.notice import FederationNotice
from app.models.local_ump import LocalUmp
from app.models.user import User
from app.core.dependencies import get_current_user, require_federation, require_local_ump

router = APIRouter()


class NoticeCreate(BaseModel):
    title: str
    content: str
    target_type: str = 'all'
    target_local_id: Optional[UUID] = None
    expires_at: Optional[datetime.datetime] = None


class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None


def _to_out(n: FederationNotice) -> dict:
    return {
        "id":               str(n.id),
        "federation_id":    str(n.federation_id),
        "title":            n.title,
        "content":          n.content,
        "target_type":      n.target_type,
        "target_local_id":  str(n.target_local_id) if n.target_local_id else None,
        "target_local_name": n.target_local.name if n.target_local else None,
        "is_active":        n.is_active,
        "created_by":       str(n.created_by),
        "creator_name":     n.creator.full_name if n.creator else None,
        "created_at":       n.created_at.isoformat() if n.created_at else None,
        "expires_at":       n.expires_at.isoformat() if n.expires_at else None,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_notice(
    payload: NoticeCreate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    if payload.target_type == 'specific' and not payload.target_local_id:
        raise HTTPException(status_code=400, detail="Informe a UMP Local de destino")

    if payload.target_local_id:
        local = db.query(LocalUmp).filter(
            LocalUmp.id == payload.target_local_id,
            LocalUmp.federation_id == current_user.organization_id,
        ).first()
        if not local:
            raise HTTPException(status_code=403, detail="UMP Local não pertence a esta Federação")

    notice = FederationNotice(
        federation_id=current_user.organization_id,
        title=payload.title,
        content=payload.content,
        target_type=payload.target_type,
        target_local_id=payload.target_local_id,
        expires_at=payload.expires_at,
        created_by=current_user.id,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return _to_out(notice)


@router.get("/sent")
def list_sent_notices(
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    notices = db.query(FederationNotice).filter(
        FederationNotice.federation_id == current_user.organization_id,
    ).order_by(FederationNotice.created_at.desc()).limit(50).all()
    return [_to_out(n) for n in notices]


@router.get("/received")
def list_received_notices(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    local = db.query(LocalUmp).filter(
        LocalUmp.id == current_user.organization_id
    ).first()
    if not local:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada")

    now = datetime.datetime.now(datetime.timezone.utc)

    notices = db.query(FederationNotice).filter(
        FederationNotice.federation_id == local.federation_id,
        FederationNotice.is_active == True,
        (FederationNotice.expires_at.is_(None)) | (FederationNotice.expires_at > now),
        (FederationNotice.target_type == 'all') |
        (FederationNotice.target_local_id == current_user.organization_id),
    ).order_by(FederationNotice.created_at.desc()).limit(50).all()

    return [_to_out(n) for n in notices]


@router.put("/{notice_id}")
def update_notice(
    notice_id: UUID,
    payload: NoticeUpdate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    notice = db.query(FederationNotice).filter(
        FederationNotice.id == notice_id,
        FederationNotice.federation_id == current_user.organization_id,
    ).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Aviso não encontrado")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(notice, field, value)

    db.commit()
    db.refresh(notice)
    return _to_out(notice)


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(
    notice_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    notice = db.query(FederationNotice).filter(
        FederationNotice.id == notice_id,
        FederationNotice.federation_id == current_user.organization_id,
    ).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Aviso não encontrado")
    db.delete(notice)
    db.commit()