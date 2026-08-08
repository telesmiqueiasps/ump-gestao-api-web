from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import extract
from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
import datetime
from app.db.session import get_db
from app.models.member import Member, MembershipFee
from app.models.local_ump import LocalUmp
from app.models.enums import MemberType
from app.models.user import User
from app.core.dependencies import get_current_user, require_local_or_federation

router = APIRouter()


class MemberCreate(BaseModel):
    full_name: str
    member_type: MemberType = MemberType.ativo
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    join_date: Optional[datetime.date] = None
    is_board_member: Optional[bool] = False
    local_society: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    avatar_url: Optional[str] = None


class MemberUpdate(BaseModel):
    full_name: Optional[str] = None
    member_type: Optional[MemberType] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    is_board_member: Optional[bool] = None
    local_society: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    avatar_url: Optional[str] = None


class FeeCreate(BaseModel):
    member_id: UUID
    reference_month: datetime.date
    amount: float


# Listar sócios da UMP Local / Delegados da Federação
@router.get("/")
def list_members(
    active_only: bool = True,
    include_board: bool = False,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    # Check/Sync board members if federation
    if current_user.organization_type == 'federation':
        shadow_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
        if not shadow_ump:
            shadow_ump = LocalUmp(
                id=current_user.organization_id,
                federation_id=current_user.organization_id,
                name="Eleições da Federação",
                fiscal_year=2026,
                is_active=True
            )
            db.add(shadow_ump)
            db.flush()

        from app.models.board import BoardMember
        import datetime
        current_year = datetime.date.today().year
        board_members = db.query(BoardMember).filter(
            BoardMember.organization_id == current_user.organization_id,
            BoardMember.fiscal_year == current_year,
            BoardMember.is_active == True,
            BoardMember.role != 'secretario_presbiterial'
        ).all()

        active_board_names = {bm.member_name for bm in board_members}

        # Find all delegates from "Diretoria"
        diretoria_members = db.query(Member).filter(
            Member.local_ump_id == current_user.organization_id,
            Member.local_society == "Diretoria"
        ).all()

        has_changes = False
        for dm in diretoria_members:
            if dm.full_name not in active_board_names and dm.is_active:
                dm.is_active = False
                has_changes = True

        for bm in board_members:
            existing = db.query(Member).filter(
                Member.local_ump_id == current_user.organization_id,
                Member.full_name == bm.member_name
            ).first()
            if not existing:
                new_m = Member(
                    local_ump_id=current_user.organization_id,
                    full_name=bm.member_name,
                    local_society="Diretoria",
                    member_type=MemberType.ativo,
                    is_active=True,
                    join_date=datetime.date.today()
                )
                db.add(new_m)
                has_changes = True
            elif not existing.is_active:
                existing.is_active = True
                has_changes = True

        if has_changes:
            db.commit()

    query = db.query(Member).filter(Member.local_ump_id == current_user.organization_id)
    if active_only:
        query = query.filter(Member.is_active == True)
    if not include_board:
        query = query.filter((Member.local_society.is_(None)) | (Member.local_society != "Diretoria"))
    members = query.order_by(Member.full_name).limit(500).all()
    return [_to_out(m) for m in members]


# Cadastrar sócio
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_member(
    payload: MemberCreate,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    # If federation, create shadow local_ump if not exists
    if current_user.organization_type == 'federation':
        shadow_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
        if not shadow_ump:
            shadow_ump = LocalUmp(
                id=current_user.organization_id,
                federation_id=current_user.organization_id,
                name="Eleições da Federação",
                fiscal_year=2026,
                is_active=True
            )
            db.add(shadow_ump)
            db.flush()

    # Geocodificação automática de endereço (caso coordenadas manuais não tenham sido fornecidas)
    lat, lon = payload.latitude, payload.longitude
    if (lat is None or lon is None) and payload.logradouro and payload.cidade and payload.estado:
        from app.services.geocoder import geocode_address
        lat, lon, _ = geocode_address(
            payload.logradouro, payload.numero, payload.bairro,
            payload.cidade, payload.estado, payload.cep
        )

    dump_data = payload.model_dump()
    dump_data["latitude"] = lat
    dump_data["longitude"] = lon

    member = Member(
        local_ump_id=current_user.organization_id,
        **dump_data
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _to_out(member)


@router.get("/geocode-search")
def geocode_search(
    logradouro: Optional[str] = None,
    numero: Optional[str] = None,
    bairro: Optional[str] = None,
    cidade: Optional[str] = None,
    estado: Optional[str] = None,
    cep: Optional[str] = None,
    current_user: User = Depends(require_local_or_federation),
):
    from app.services.geocoder import geocode_address
    lat, lon, precision = geocode_address(logradouro, numero, bairro, cidade, estado, cep)
    return {"latitude": lat, "longitude": lon, "precision": precision}


@router.get("/birthdays")
def get_birthdays(
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    current_month = datetime.date.today().month
    current_day   = datetime.date.today().day

    members = db.query(Member).filter(
        Member.local_ump_id == current_user.organization_id,
        Member.is_active == True,
        Member.birth_date.isnot(None),
        extract('month', Member.birth_date) == current_month,
    ).order_by(extract('day', Member.birth_date)).all()

    today = datetime.date.today()
    result = []
    for m in members:
        birth_day      = m.birth_date.day
        age            = today.year - m.birth_date.year
        is_today       = birth_day == current_day
        already_passed = birth_day < current_day

        result.append({
            "id":            str(m.id),
            "full_name":     m.full_name,
            "birth_date":    m.birth_date.isoformat(),
            "birth_day":     birth_day,
            "age":           age,
            "is_today":      is_today,
            "already_passed": already_passed,
        })

    return result


# Detalhe de um sócio
@router.get("/{member_id}")
def get_member(
    member_id: UUID,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")
    return _to_out(member)


# Atualizar sócio
@router.put("/{member_id}")
def update_member(
    member_id: UUID,
    payload: MemberUpdate,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")
    
    dump = payload.model_dump(exclude_none=True)
    has_manual_coords = ("latitude" in dump and dump["latitude"] is not None) and ("longitude" in dump and dump["longitude"] is not None)

    address_changed = False
    for field in ['cep', 'logradouro', 'numero', 'bairro', 'cidade', 'estado']:
        if field in dump and getattr(member, field) != dump[field]:
            address_changed = True
            break

    for field, value in dump.items():
        setattr(member, field, value)
        
    if not has_manual_coords and (address_changed or member.latitude is None or member.longitude is None):
        from app.services.geocoder import geocode_address
        lat, lon, _ = geocode_address(
            member.logradouro, member.numero, member.bairro,
            member.cidade, member.estado, member.cep
        )
        member.latitude = lat
        member.longitude = lon

    db.commit()
    db.refresh(member)
    return _to_out(member)


# Excluir ou Desativar sócio
@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_or_deactivate_member(
    member_id: UUID,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    avatar_to_delete = member.avatar_url

    try:
        # Tenta exclusão física
        db.delete(member)
        db.commit()

        # Remove arquivo do Cloudflare R2 após exclusão no banco
        if avatar_to_delete:
            from app.services.storage import delete_file, extract_key_from_url
            key = extract_key_from_url(avatar_to_delete)
            if key:
                delete_file(key)
    except Exception:
        # Em caso de constraint de chave estrangeira (ex: já votou/tem lançamentos), faz o fallback para desativação
        db.rollback()
        member = db.query(Member).filter(Member.id == member_id).first()
        member.is_active = False
        db.commit()


# Upload de avatar/foto do sócio para o Cloudflare R2
@router.post("/{member_id}/avatar")
async def upload_member_avatar(
    member_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="A foto deve ter no máximo 10MB")

    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.split(".")[-1].lower()
    if ext not in ["jpg", "jpeg", "png", "webp"]:
        ext = "jpg"

    content_type = file.content_type or f"image/{ext}"
    timestamp = int(datetime.datetime.now().timestamp())
    key = f"members/avatars/{member_id}_{timestamp}.{ext}"

    # Se já possuía foto anterior, remove do R2
    if member.avatar_url:
        from app.services.storage import delete_file, extract_key_from_url
        old_key = extract_key_from_url(member.avatar_url)
        if old_key:
            delete_file(old_key)

    from app.services.storage import upload_file
    public_url = upload_file(contents, key, content_type)

    member.avatar_url = public_url
    db.commit()
    db.refresh(member)
    return _to_out(member)


# Registrar mensalidade
@router.post("/fees", status_code=status.HTTP_201_CREATED)
def register_fee(
    payload: FeeCreate,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == payload.member_id,
        Member.local_ump_id == current_user.organization_id,
        Member.is_active == True,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    fee = MembershipFee(
        member_id=payload.member_id,
        local_ump_id=current_user.organization_id,
        reference_month=payload.reference_month,
        amount=payload.amount,
    )
    db.add(fee)
    db.commit()
    db.refresh(fee)
    return {
        "id": str(fee.id),
        "member_id": str(fee.member_id),
        "reference_month": fee.reference_month.isoformat(),
        "amount": float(fee.amount),
        "paid_at": fee.paid_at.isoformat() if fee.paid_at else None,
    }


# Listar mensalidades de um sócio
@router.get("/{member_id}/fees")
def list_fees(
    member_id: UUID,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(
        Member.id == member_id,
        Member.local_ump_id == current_user.organization_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Sócio não encontrado")

    fees = db.query(MembershipFee).filter(
        MembershipFee.member_id == member_id
    ).order_by(MembershipFee.reference_month.desc()).limit(500).all()

    return [
        {
            "id": str(f.id),
            "reference_month": f.reference_month.isoformat(),
            "amount": float(f.amount),
            "paid_at": f.paid_at.isoformat() if f.paid_at else None,
            "receipt_url": f.receipt_url,
        }
        for f in fees
    ]


def _to_out(m: Member) -> dict:
    return {
        "id": str(m.id),
        "local_ump_id": str(m.local_ump_id),
        "full_name": m.full_name,
        "member_type": m.member_type.value,
        "email": m.email,
        "phone": m.phone,
        "birth_date": m.birth_date.isoformat() if m.birth_date else None,
        "join_date": m.join_date.isoformat() if m.join_date else None,
        "is_active": m.is_active,
        "is_board_member": m.is_board_member or False,
        "local_society": m.local_society,
        "cep": m.cep,
        "logradouro": m.logradouro,
        "numero": m.numero,
        "bairro": m.bairro,
        "cidade": m.cidade,
        "estado": m.estado,
        "latitude": m.latitude,
        "longitude": m.longitude,
        "avatar_url": m.avatar_url,
    }