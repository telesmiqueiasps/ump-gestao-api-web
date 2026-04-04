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

    for field, value in restricted.items():
        setattr(local, field, value)

    db.commit()
    db.refresh(local)
    return _to_out(local)


# Federação desativa uma Local
@router.delete("/{local_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_local_ump(
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
    local.is_active = False
    db.commit()


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
    }