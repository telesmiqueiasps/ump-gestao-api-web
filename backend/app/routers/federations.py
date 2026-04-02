from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from app.db.session import get_db
from app.models.federation import Federation
from app.models.local_ump import LocalUmp
from app.core.dependencies import get_current_user, require_federation
from app.models.user import User
from app.services.storage import upload_file

router = APIRouter()


class FederationCreate(BaseModel):
    name: str
    presbytery_name: Optional[str] = None
    synodal_name: Optional[str] = None
    address: Optional[str] = None


class FederationUpdate(BaseModel):
    name: Optional[str] = None
    presbytery_name: Optional[str] = None
    synodal_name: Optional[str] = None
    address: Optional[str] = None


class FederationOut(BaseModel):
    id: str
    name: str
    presbytery_name: Optional[str]
    synodal_name: Optional[str]
    address: Optional[str]
    logo_url: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


# Apenas para uso interno/admin — criar federação
@router.post("/", response_model=FederationOut, status_code=status.HTTP_201_CREATED)
def create_federation(payload: FederationCreate, db: Session = Depends(get_db)):
    federation = Federation(**payload.model_dump())
    db.add(federation)
    db.commit()
    db.refresh(federation)
    return _to_out(federation)


# Federação visualiza seus próprios dados
@router.get("/me", response_model=FederationOut)
def get_my_federation(
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    federation = db.query(Federation).filter(
        Federation.id == current_user.organization_id
    ).first()
    if not federation:
        raise HTTPException(status_code=404, detail="Federação não encontrada")
    return _to_out(federation)


# Atualizar dados da federação
@router.put("/me", response_model=FederationOut)
def update_my_federation(
    payload: FederationUpdate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    federation = db.query(Federation).filter(
        Federation.id == current_user.organization_id
    ).first()
    if not federation:
        raise HTTPException(status_code=404, detail="Federação não encontrada")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(federation, field, value)

    db.commit()
    db.refresh(federation)
    return _to_out(federation)


# Upload de logo
@router.post("/me/logo", response_model=FederationOut)
async def upload_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    federation = db.query(Federation).filter(
        Federation.id == current_user.organization_id
    ).first()
    if not federation:
        raise HTTPException(status_code=404, detail="Federação não encontrada")

    allowed = ["image/png", "image/jpeg", "image/webp"]
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Formato de imagem inválido. Use PNG, JPG ou WEBP.")

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande. Máximo 5MB.")

    # Exclui logo antiga do B2 se existir
    if federation.logo_url:
        from app.services.storage import delete_folder
        from app.core.config import get_settings
        import re
        s = get_settings()
        match = re.search(rf'/file/{re.escape(s.b2_bucket_name)}/(.+)$', federation.logo_url)
        if not match:
            match = re.search(rf'/{re.escape(s.b2_bucket_name)}/(.+)$', federation.logo_url)
        if match:
            old_key = match.group(1)
            folder = '/'.join(old_key.split('/')[:-1]) + '/'
            delete_folder(folder)

    key = f"logos/federations/{federation.id}/{file.filename}"
    url = upload_file(contents, key, file.content_type)

    federation.logo_url = url
    db.commit()
    db.refresh(federation)
    return _to_out(federation)


# Federação lista suas UMPs Locais
@router.get("/me/local-umps")
def list_my_local_umps(
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db),
):
    locals_ = db.query(LocalUmp).filter(
        LocalUmp.federation_id == current_user.organization_id
    ).limit(500).all()
    return [
        {
            "id": str(l.id),
            "name": l.name,
            "church_name": l.church_name,
            "pastor_name": l.pastor_name,
            "fiscal_year": l.fiscal_year,
            "is_active": l.is_active,
        }
        for l in locals_
    ]


def _to_out(f: Federation) -> dict:
    return {
        "id": str(f.id),
        "name": f.name,
        "presbytery_name": f.presbytery_name,
        "synodal_name": f.synodal_name,
        "address": f.address,
        "logo_url": f.logo_url,
        "is_active": f.is_active,
    }