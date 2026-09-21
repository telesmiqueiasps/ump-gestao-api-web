import re
import secrets
import logging
import base64
import uuid as _uuid
from datetime import datetime, date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.session import get_db
from app.core.dependencies import get_current_user, require_federation, require_local_ump, require_local_or_federation
from app.models.user import User, UserRole
from app.models.federation import Federation
from app.models.local_ump import LocalUmp
from app.models.member import Member
from app.models.finance import FinancialPeriod
from app.models.activity_report import ActivityReport
from app.models.ump_statistic import UmpStatisticCollector
from app.models.congress import (
    Congress, CongressCommission, CongressCommissionMember, CongressCommissionDocument,
    CongressCredential, CongressCredentialDelegate
)
from app.services.storage import (
    get_presigned_url, upload_file, delete_file, delete_folder, extract_key_from_url, resize_image_max_size
)
from app.services.pdf_generator import generate_commission_report, generate_credential_pdf
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ── SCHEMAS ──

class CongressCreate(BaseModel):
    title: str
    fiscal_year: int
    description: Optional[str] = None

class CongressUpdate(BaseModel):
    title: Optional[str] = None
    fiscal_year: Optional[int] = None
    description: Optional[str] = None
    status: Optional[str] = None

class CommissionCreate(BaseModel):
    name: str
    description: Optional[str] = None

class CommissionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class CommissionMemberItem(BaseModel):
    delegate_id: Optional[UUID] = None
    delegate_name: str
    is_relator: bool = False

class CommissionMembersPayload(BaseModel):
    relator_id: Optional[UUID] = None
    relator_name: Optional[str] = None
    members: List[CommissionMemberItem] = []

class DocumentAttachItem(BaseModel):
    title: str
    category: str = "avulso"
    origin_name: Optional[str] = None
    document_url: str
    external_reference_id: Optional[str] = None

class OpinionPayload(BaseModel):
    opinion_report: str
    approval_date: Optional[str] = None

class DelegateLimitsPayload(BaseModel):
    min_delegates: int = 1
    max_delegates: int = 5

class CredentialDelegateItem(BaseModel):
    member_id: Optional[UUID] = None
    delegate_name: str
    is_optional: bool = False

class CredentialSavePayload(BaseModel):
    delegates: List[CredentialDelegateItem] = []
    pastor_name: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None

class PastorApprovalPayload(BaseModel):
    pastor_name: Optional[str] = None
    selfie_base64: Optional[str] = None


# ── HELPERS ──

def _presign_url_if_needed(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    # Se a URL já contiver query string (ex: ?X-Amz-...), remove para isolar a chave pura
    clean_url = url.split('?')[0].strip()
    match = re.search(r'(?:/file/[^/]+/|/|^)(activity-reports/[^?]+|activities/[^?]+|receipts/[^?]+|logos/[^?]+|reports/[^?]+|pix-qr/[^?]+|signatures/[^?]+|congresses/[^?]+)$', clean_url)
    if match:
        key = match.group(1).lstrip('/')
        return get_presigned_url(key, expires_in=7200)
    return url


def _freeze_congress_members(congress: Congress):
    """Salva de forma estática e definitiva os nomes de relatores e membros nas comissões."""
    for comm in congress.commissions:
        if comm.relator and comm.relator.full_name:
            comm.relator_name = comm.relator.full_name.strip()
        for m in comm.members:
            if m.delegate and m.delegate.full_name:
                m.delegate_name = m.delegate.full_name.strip()


def _serialize_commission(comm: CongressCommission) -> dict:
    is_closed = bool(comm.congress and comm.congress.status == "encerrado")
    if is_closed:
        rel_name = comm.relator_name
    else:
        rel_name = comm.relator.full_name.strip() if (comm.relator and comm.relator.full_name) else comm.relator_name

    return {
        "id": str(comm.id),
        "congress_id": str(comm.congress_id),
        "name": comm.name,
        "description": comm.description,
        "relator_id": str(comm.relator_id) if comm.relator_id else None,
        "relator_name": rel_name,
        "access_token": comm.access_token,
        "opinion_report": comm.opinion_report or "",
        "approval_date": comm.approval_date,
        "validation_code": comm.validation_code,
        "status": comm.status or "em_elaboracao",
        "final_report_url": _presign_url_if_needed(comm.final_report_url),
        "approved_at": comm.approved_at.isoformat() if comm.approved_at else None,
        "approved_by": str(comm.approved_by) if comm.approved_by else None,
        "is_locked": (comm.status == "aprovado" or is_closed),
        "opinion_updated_at": comm.opinion_updated_at.isoformat() if comm.opinion_updated_at else None,
        "has_opinion": bool(comm.opinion_report and comm.opinion_report.strip()),
        "created_at": comm.created_at.isoformat() if comm.created_at else None,
        "members": [
            {
                "id": str(m.id),
                "delegate_id": str(m.delegate_id) if m.delegate_id else None,
                "delegate_name": m.delegate_name if is_closed else (m.delegate.full_name.strip() if (m.delegate and m.delegate.full_name) else m.delegate_name),
                "is_relator": m.is_relator
            }
            for m in comm.members
        ],
        "documents": [
            {
                "id": str(d.id),
                "title": d.title,
                "category": d.category,
                "origin_name": d.origin_name,
                "document_url": _presign_url_if_needed(d.document_url),
                "external_reference_id": d.external_reference_id,
                "created_at": d.created_at.isoformat() if d.created_at else None
            }
            for d in comm.documents
        ]
    }


def _serialize_credential(cred: CongressCredential, include_token: bool = True) -> dict:
    return {
        "id": str(cred.id),
        "congress_id": str(cred.congress_id),
        "local_ump_id": str(cred.local_ump_id),
        "local_ump_name": cred.local_ump.name if cred.local_ump else None,
        "church_name": cred.local_ump.church_name if cred.local_ump else None,
        "status": cred.status,
        "city": cred.city or (cred.local_ump.cidade if cred.local_ump else None),
        "document_date": cred.document_date.isoformat() if cred.document_date else None,
        "pastor_name": cred.pastor_name or (cred.local_ump.pastor_name if cred.local_ump else None),
        "pastor_token": cred.pastor_token if include_token else None,
        "pastor_selfie_url": _presign_url_if_needed(cred.pastor_selfie_url),
        "pastor_approved_at": cred.pastor_approved_at.isoformat() if cred.pastor_approved_at else None,
        "president_name": cred.president_name,
        "president_signed_at": cred.president_signed_at.isoformat() if cred.president_signed_at else None,
        "submitted_at": cred.submitted_at.isoformat() if cred.submitted_at else None,
        "submitted_by": str(cred.submitted_by) if cred.submitted_by else None,
        "validation_code": cred.validation_code,
        "homologated_at": cred.homologated_at.isoformat() if cred.homologated_at else None,
        "notes": cred.notes,
        "delegates_count": len(cred.delegates) if cred.delegates else 0,
        "delegates": [
            {
                "id": str(d.id),
                "member_id": str(d.member_id) if d.member_id else None,
                "delegate_name": d.delegate_name,
                "order_index": d.order_index,
                "is_optional": d.is_optional,
            }
            for d in cred.delegates
        ] if cred.delegates else []
    }


def _serialize_congress(c: Congress, include_commissions: bool = True) -> dict:
    data = {
        "id": str(c.id),
        "federation_id": str(c.federation_id),
        "title": c.title,
        "fiscal_year": c.fiscal_year,
        "description": c.description,
        "status": c.status,
        "min_delegates": c.min_delegates if c.min_delegates is not None else 1,
        "max_delegates": c.max_delegates if c.max_delegates is not None else 5,
        "created_by": str(c.created_by) if c.created_by else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "commissions_count": len(c.commissions) if c.commissions else 0,
        "credentials_count": len(c.credentials) if c.credentials else 0,
        "total_documents_count": sum(len(comm.documents) for comm in c.commissions) if c.commissions else 0
    }
    if include_commissions and c.commissions:
        data["commissions"] = [_serialize_commission(comm) for comm in c.commissions]
    else:
        data["commissions"] = []
    return data


# ── ROTAS AUTENTICADAS (FEDERAÇÃO) ──

@router.get("", include_in_schema=False)
@router.get("/")
def list_congresses(
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Lista todos os congressos cadastrados pela federação."""
    congresses = db.query(Congress).filter(
        Congress.federation_id == current_user.organization_id
    ).order_by(desc(Congress.fiscal_year), desc(Congress.created_at)).all()
    return [_serialize_congress(c, include_commissions=True) for c in congresses]


@router.post("", status_code=status.HTTP_201_CREATED, include_in_schema=False)
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_congress(
    payload: CongressCreate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Cria um novo congresso e gera automaticamente as 4 comissões padrão."""
    congress = Congress(
        federation_id=current_user.organization_id,
        title=payload.title.strip(),
        fiscal_year=payload.fiscal_year,
        description=payload.description.strip() if payload.description else None,
        status="aberto",
        created_by=current_user.id
    )
    db.add(congress)
    db.flush()

    # 4 Comissões padrão recomendadas pela rotina sinodal/federativa
    default_commissions = [
        "Comissão de Planos e Metas",
        "Comissão de Relatórios Estatísticos",
        "Comissão de Relatórios de Atividades",
        "Comissão de Relatórios Financeiros"
    ]

    for comm_name in default_commissions:
        comm = CongressCommission(
            congress_id=congress.id,
            name=comm_name,
            description=f"Comissão temática de {comm_name.lower().replace('comissão de ', '')} do congresso."
        )
        db.add(comm)

    db.commit()
    db.refresh(congress)
    return _serialize_congress(congress, include_commissions=True)


def _is_local_leader(user_id: UUID, db: Session) -> tuple[bool, str]:
    """Verifica se o usuário possui cargo ativo de Presidente ou Vice-Presidente da UMP Local."""
    roles = db.query(UserRole).filter(
        UserRole.user_id == user_id,
        UserRole.is_active == True
    ).all()
    role_names = [r.role.value if hasattr(r.role, 'value') else str(r.role) for r in roles]
    if "presidente" in role_names:
        return True, "Presidente"
    if "vice_presidente" in role_names:
        return True, "Vice-Presidente"
    return False, ""


@router.get("/active-for-local")
def get_active_congress_for_local(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db)
):
    """
    Retorna o congresso ativo da federação para a UMP Local do usuário,
    junto aos limites de delegados e a credencial atual.
    Acesso restrito a Presidente e Vice-Presidente da UMP Local.
    """
    is_leader, role_label = _is_local_leader(current_user.id, db)
    if not is_leader:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o Presidente e o Vice-Presidente da UMP Local têm acesso à Credencial do Congresso."
        )

    local_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    if not local_ump:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada.")

    # Busca congresso aberto da federação vinculada
    congress = db.query(Congress).filter(
        Congress.federation_id == local_ump.federation_id,
        Congress.status == "aberto"
    ).order_by(desc(Congress.fiscal_year), desc(Congress.created_at)).first()

    if not congress:
        return {
            "has_active_congress": False,
            "message": "Nenhum congresso aberto no momento pela sua Federação."
        }

    # Busca ou cria a credencial da UMP local para este congresso
    cred = db.query(CongressCredential).filter(
        CongressCredential.congress_id == congress.id,
        CongressCredential.local_ump_id == local_ump.id
    ).first()

    if not cred:
        cred = CongressCredential(
            congress_id=congress.id,
            local_ump_id=local_ump.id,
            status="rascunho",
            city=local_ump.cidade or "Patos",
            pastor_name=local_ump.pastor_name,
            document_date=date.today()
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)

    fed = db.query(Federation).filter(Federation.id == local_ump.federation_id).first()
    active_members = db.query(Member).filter(
        Member.local_ump_id == local_ump.id,
        Member.is_active == True
    ).order_by(Member.full_name).all()

    return {
        "has_active_congress": True,
        "congress": _serialize_congress(congress, include_commissions=False),
        "credential": _serialize_credential(cred, include_token=True),
        "federation": {
            "name": fed.name if fed else "",
            "presbytery_name": fed.presbytery_name if fed else "",
            "synodal_name": fed.synodal_name if fed else "",
        },
        "local_ump": {
            "id": str(local_ump.id),
            "name": local_ump.name,
            "church_name": local_ump.church_name,
            "pastor_name": local_ump.pastor_name,
            "cidade": local_ump.cidade,
        },
        "members": [
            {"id": str(m.id), "full_name": m.full_name}
            for m in active_members
        ],
        "current_user_name": current_user.full_name,
        "current_user_role": role_label
    }


@router.get("/{congress_id}")
def get_congress(
    congress_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Retorna os dados detalhados de um congresso e suas comissões."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")
    return _serialize_congress(congress, include_commissions=True)


@router.put("/{congress_id}")
def update_congress(
    congress_id: UUID,
    payload: CongressUpdate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Atualiza dados do congresso."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")

    if payload.title is not None:
        congress.title = payload.title.strip()
    if payload.fiscal_year is not None:
        congress.fiscal_year = payload.fiscal_year
    if payload.description is not None:
        congress.description = payload.description.strip() if payload.description else None
    if payload.status is not None:
        if payload.status == "encerrado" and congress.status != "encerrado":
            _freeze_congress_members(congress)
        congress.status = payload.status

    db.commit()
    db.refresh(congress)
    return _serialize_congress(congress, include_commissions=True)


@router.post("/{congress_id}/close")
def close_congress(
    congress_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Encerra oficialmente o congresso e congela estaticamente os nomes de relatores e membros nas comissões."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")

    _freeze_congress_members(congress)
    congress.status = "encerrado"
    db.commit()
    db.refresh(congress)
    return _serialize_congress(congress, include_commissions=True)


@router.post("/{congress_id}/reopen")
def reopen_congress(
    congress_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Reabre o congresso para edições."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")

    congress.status = "aberto"
    db.commit()
    db.refresh(congress)
    return _serialize_congress(congress, include_commissions=True)


@router.delete("/{congress_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_congress(
    congress_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Exclui o congresso e todas as suas comissões associadas."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")
    if congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado e não pode ser excluído.")

    # Exclui pasta com arquivos avulsos e pareceres gerados para o congresso no R2
    try:
        delete_folder(f"congresses/{congress.id}")
    except Exception as e:
        logger.error(f"Erro ao excluir pasta do congresso {congress.id} do R2: {e}")

    db.delete(congress)
    db.commit()
    return None


# ── GESTÃO DE COMISSÕES ──

@router.post("/{congress_id}/commissions", status_code=status.HTTP_201_CREATED)
def create_commission(
    congress_id: UUID,
    payload: CommissionCreate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Adiciona uma nova comissão ao congresso."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")
    if congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. Não é possível criar novas comissões.")

    commission = CongressCommission(
        congress_id=congress.id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None
    )
    db.add(commission)
    db.commit()
    db.refresh(commission)
    return _serialize_commission(commission)


@router.put("/commissions/{commission_id}")
def update_commission(
    commission_id: UUID,
    payload: CommissionUpdate,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Atualiza dados básicos da comissão."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. Não é possível editar comissões.")

    if payload.name is not None:
        comm.name = payload.name.strip()
    if payload.description is not None:
        comm.description = payload.description.strip() if payload.description else None

    db.commit()
    db.refresh(comm)
    return _serialize_commission(comm)


@router.delete("/commissions/{commission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_commission(
    commission_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Exclui uma comissão de trabalho."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. Não é possível excluir comissões.")

    # Exclui pasta de arquivos avulsos e parecer homologado da comissão no R2
    try:
        delete_folder(f"congresses/{comm.congress_id}/commissions/{comm.id}")
        if comm.final_report_url:
            pdf_key = extract_key_from_url(comm.final_report_url)
            if pdf_key:
                delete_file(pdf_key)
    except Exception as e:
        logger.error(f"Erro ao excluir arquivos da comissão {comm.id} do R2: {e}")

    db.delete(comm)
    db.commit()
    return None


@router.put("/commissions/{commission_id}/members")
def set_commission_members(
    commission_id: UUID,
    payload: CommissionMembersPayload,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Define o Relator e a lista de membros da comissão."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. Não é possível editar comissões.")

    comm.relator_id = payload.relator_id
    if payload.relator_id:
        rel_obj = db.query(Member).filter(Member.id == payload.relator_id).first()
        comm.relator_name = rel_obj.full_name.strip() if rel_obj else (payload.relator_name.strip() if payload.relator_name else None)
    else:
        comm.relator_name = payload.relator_name.strip() if payload.relator_name else None

    # Remove membros antigos e adiciona os novos
    db.query(CongressCommissionMember).filter(CongressCommissionMember.commission_id == comm.id).delete()

    for m in payload.members:
        del_name = m.delegate_name.strip()
        if m.delegate_id:
            del_obj = db.query(Member).filter(Member.id == m.delegate_id).first()
            if del_obj:
                del_name = del_obj.full_name.strip()

        member_obj = CongressCommissionMember(
            commission_id=comm.id,
            delegate_id=m.delegate_id,
            delegate_name=del_name,
            is_relator=m.is_relator
        )
        db.add(member_obj)

    db.commit()
    db.refresh(comm)
    return _serialize_commission(comm)


# ── DOCUMENTOS DISPONÍVEIS NO SISTEMA ──

@router.get("/available-documents/list")
def get_available_documents(
    year: Optional[int] = Query(default=None),
    congress_id: Optional[UUID] = Query(default=None),
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """
    Retorna todos os documentos do sistema gerados pelas UMPs Locais e pela própria Federação,
    prontos para serem selecionados e disponibilizados para as comissões.
    Se congress_id for fornecido, oculta os documentos que já foram atribuídos a alguma comissão deste congresso.
    """
    fed_id = current_user.organization_id
    fed_obj = db.query(Federation).filter(Federation.id == fed_id).first()
    fed_name = fed_obj.name if fed_obj else "Federação"

    locals_in_fed = db.query(LocalUmp).filter(
        LocalUmp.federation_id == fed_id,
        LocalUmp.id != fed_id,
        ~LocalUmp.name.ilike('%eleiç%'),
        ~LocalUmp.name.ilike('%eleic%'),
        LocalUmp.is_active == True
    ).order_by(LocalUmp.name.asc()).all()

    documents = []

    # 1. Documentos das UMPs Locais
    for loc in locals_in_fed:
        # A. Relatórios Financeiros e Comprovantes de Períodos Encerrados
        p_query = db.query(FinancialPeriod).filter(
            FinancialPeriod.organization_id == loc.id,
            FinancialPeriod.is_closed == True
        )
        if year:
            p_query = p_query.filter(FinancialPeriod.fiscal_year == year)
        periods = p_query.order_by(desc(FinancialPeriod.fiscal_year)).all()

        for p in periods:
            if p.report_url:
                documents.append({
                    "id": f"fin_{p.id}",
                    "title": f"Relatório Financeiro {p.fiscal_year} — {loc.name}",
                    "category": "financeiro",
                    "origin_name": loc.name,
                    "document_url": p.report_url.split('?')[0],
                    "fiscal_year": p.fiscal_year,
                    "external_reference_id": str(p.id)
                })
            if p.receipts_report_url:
                documents.append({
                    "id": f"rec_{p.id}",
                    "title": f"Comprovantes Financeiros {p.fiscal_year} — {loc.name}",
                    "category": "comprovantes",
                    "origin_name": loc.name,
                    "document_url": p.receipts_report_url.split('?')[0],
                    "fiscal_year": p.fiscal_year,
                    "external_reference_id": str(p.id)
                })

        # B. Relatórios de Atividades Publicados
        act_query = db.query(ActivityReport).filter(
            ActivityReport.organization_id == loc.id,
            ActivityReport.status.in_(["published", "publicado"])
        )
        if year:
            act_query = act_query.filter(ActivityReport.fiscal_year == year)
        act_reports = act_query.order_by(desc(ActivityReport.fiscal_year)).all()

        for a in act_reports:
            if a.report_url:
                documents.append({
                    "id": f"act_{a.id}",
                    "title": f"Relatório de Atividades {a.fiscal_year} — {loc.name}",
                    "category": "atividades",
                    "origin_name": loc.name,
                    "document_url": a.report_url.split('?')[0],
                    "fiscal_year": a.fiscal_year,
                    "external_reference_id": str(a.id)
                })

        # C. Relatórios Estatísticos Publicados (Apenas PDF publicado)
        stat_query = db.query(UmpStatisticCollector).filter(
            UmpStatisticCollector.local_ump_id == loc.id,
            UmpStatisticCollector.status.in_(["published", "publicado"]),
            UmpStatisticCollector.report_url != None
        )
        if year:
            stat_query = stat_query.filter(UmpStatisticCollector.fiscal_year == year)
        collectors = stat_query.all()
        for col in collectors:
            documents.append({
                "id": f"stat_{col.id}",
                "title": f"Relatório Estatístico {col.fiscal_year} — {loc.name}",
                "category": "estatistica",
                "origin_name": loc.name,
                "document_url": col.report_url.split('?')[0],
                "fiscal_year": col.fiscal_year,
                "external_reference_id": str(col.id)
            })

    # 2. Documentos da própria Federação
    fed_p_query = db.query(FinancialPeriod).filter(
        FinancialPeriod.organization_id == fed_id,
        FinancialPeriod.is_closed == True
    )
    if year:
        fed_p_query = fed_p_query.filter(FinancialPeriod.fiscal_year == year)
    fed_periods = fed_p_query.order_by(desc(FinancialPeriod.fiscal_year)).all()

    for fp in fed_periods:
        if fp.report_url:
            documents.append({
                "id": f"fin_fed_{fp.id}",
                "title": f"Relatório Financeiro {fp.fiscal_year} — {fed_name}",
                "category": "financeiro",
                "origin_name": fed_name,
                "document_url": fp.report_url.split('?')[0],
                "fiscal_year": fp.fiscal_year,
                "external_reference_id": str(fp.id)
            })
        if fp.receipts_report_url:
            documents.append({
                "id": f"rec_fed_{fp.id}",
                "title": f"Comprovantes Financeiros {fp.fiscal_year} — {fed_name}",
                "category": "comprovantes",
                "origin_name": fed_name,
                "document_url": fp.receipts_report_url.split('?')[0],
                "fiscal_year": fp.fiscal_year,
                "external_reference_id": str(fp.id)
            })

    # Relatório de atividades da Federação
    fed_act_query = db.query(ActivityReport).filter(
        ActivityReport.organization_id == fed_id,
        ActivityReport.status.in_(["published", "publicado"])
    )
    if year:
        fed_act_query = fed_act_query.filter(ActivityReport.fiscal_year == year)
    fed_acts = fed_act_query.order_by(desc(ActivityReport.fiscal_year)).all()

    for fa in fed_acts:
        if fa.report_url:
            documents.append({
                "id": f"act_fed_{fa.id}",
                "title": f"Relatório de Atividades {fa.fiscal_year} — {fed_name}",
                "category": "atividades",
                "origin_name": fed_name,
                "document_url": fa.report_url.split('?')[0],
                "fiscal_year": fa.fiscal_year,
                "external_reference_id": str(fa.id)
            })

    # Relatório estatístico consolidado publicado da Federação
    fed_stat_query = db.query(UmpStatisticCollector).filter(
        UmpStatisticCollector.federation_id == fed_id,
        UmpStatisticCollector.status.in_(["published", "publicado"]),
        UmpStatisticCollector.report_url != None
    )
    if year:
        fed_stat_query = fed_stat_query.filter(UmpStatisticCollector.fiscal_year == year)
    fed_stat_collectors = fed_stat_query.all()
    for fsc in fed_stat_collectors:
        documents.append({
            "id": f"stat_fed_{fsc.id}",
            "title": f"Relatório Estatístico Consolidado {fsc.fiscal_year} — {fed_name}",
            "category": "estatistica",
            "origin_name": fed_name,
            "document_url": fsc.report_url.split('?')[0],
            "fiscal_year": fsc.fiscal_year,
            "external_reference_id": str(fsc.id)
        })

    # 3. Filtrar documentos já vinculados a qualquer comissão deste congresso
    if congress_id:
        commissions_in_congress = db.query(CongressCommission.id).filter(
            CongressCommission.congress_id == congress_id
        ).all()
        comm_ids = [c.id for c in commissions_in_congress]
        if comm_ids:
            already_attached = db.query(CongressCommissionDocument).filter(
                CongressCommissionDocument.commission_id.in_(comm_ids)
            ).all()

            used_refs = {doc.external_reference_id for doc in already_attached if doc.external_reference_id}
            used_urls = {doc.document_url.split('?')[0].strip() for doc in already_attached if doc.document_url}
            used_titles = {doc.title.strip() for doc in already_attached if doc.title}

            filtered_documents = []
            for d in documents:
                doc_id = d.get('id')
                ext_id = d.get('external_reference_id')
                doc_url = d.get('document_url', '').split('?')[0].strip()
                doc_title = d.get('title', '').strip()

                if doc_id in used_refs or ext_id in used_refs or doc_url in used_urls or doc_title in used_titles:
                    continue
                filtered_documents.append(d)

            return filtered_documents

    return documents


@router.post("/commissions/{commission_id}/documents")
def attach_commission_documents(
    commission_id: UUID,
    payload: List[DocumentAttachItem],
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Vincula um ou mais documentos selecionados à comissão."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. Não é possível vincular documentos.")

    # Busca todas as comissões do mesmo congresso
    other_commissions = db.query(CongressCommission.id).filter(
        CongressCommission.congress_id == comm.congress_id
    ).all()
    other_comm_ids = [c.id for c in other_commissions]

    attached_docs_in_congress = db.query(CongressCommissionDocument).filter(
        CongressCommissionDocument.commission_id.in_(other_comm_ids)
    ).all()

    used_refs = {doc.external_reference_id for doc in attached_docs_in_congress if doc.external_reference_id}
    used_urls = {doc.document_url.split('?')[0].strip() for doc in attached_docs_in_congress if doc.document_url}
    used_titles = {doc.title.strip() for doc in attached_docs_in_congress if doc.title}

    new_docs = []
    for item in payload:
        if item.document_url.startswith("http"):
            clean_item_url = item.document_url.split('?')[0].strip()
        else:
            clean_item_url = item.document_url.strip()

        item_title = item.title.strip()
        item_ref = item.external_reference_id

        # Verifica se o documento já está vinculado em QUALQUER comissão deste congresso
        if clean_item_url in used_urls or item_title in used_titles or (item_ref and item_ref in used_refs):
            raise HTTPException(
                status_code=400,
                detail=f"O documento '{item_title}' já está disponibilizado para uma comissão neste congresso."
            )

        doc = CongressCommissionDocument(
            commission_id=comm.id,
            title=item_title,
            category=item.category,
            origin_name=item.origin_name.strip() if item.origin_name else None,
            document_url=clean_item_url,
            external_reference_id=item_ref
        )
        db.add(doc)
        new_docs.append(doc)

        used_urls.add(clean_item_url)
        used_titles.add(item_title)
        if item_ref:
            used_refs.add(item_ref)

    db.commit()
    db.refresh(comm)
    return _serialize_commission(comm)


@router.post("/commissions/{commission_id}/documents/upload")
async def upload_commission_document(
    commission_id: UUID,
    title: str = Form(...),
    category: str = Form("avulso"),
    origin_name: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Faz o upload de um PDF ou documento avulso diretamente para a comissão."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. Não é possível enviar novos documentos.")

    content = await file.read()
    if len(content) > 25 * 1024 * 1024:  # 25 MB max
        raise HTTPException(status_code=400, detail="Arquivo muito grande. O limite máximo é 25MB.")

    clean_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', file.filename or "documento.pdf")
    unique_prefix = secrets.token_hex(4)
    key = f"congresses/{comm.congress_id}/commissions/{comm.id}/{unique_prefix}_{clean_filename}"
    uploaded_url = upload_file(content, key, file.content_type or "application/pdf")

    doc = CongressCommissionDocument(
        commission_id=comm.id,
        title=title.strip(),
        category=category,
        origin_name=origin_name.strip() if origin_name else "Avulso",
        document_url=uploaded_url.split('?')[0].strip(),
        external_reference_id=None
    )
    db.add(doc)
    db.commit()
    db.refresh(comm)
    return _serialize_commission(comm)


@router.delete("/commissions/{commission_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_commission_document(
    commission_id: UUID,
    doc_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Remove um documento vinculado à comissão. Se for documento avulso (upload), exclui também do bucket R2."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. Não é possível desvincular documentos.")

    doc = db.query(CongressCommissionDocument).filter(
        CongressCommissionDocument.id == doc_id,
        CongressCommissionDocument.commission_id == comm.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    # Exclui do bucket R2 APENAS se for documento avulso (upload para a comissão).
    # Documentos gerados pelo sistema (financeiro, comprovantes, atividades, estatísticas) NÃO são excluídos do bucket.
    is_avulso = (doc.category == "avulso") or (not doc.external_reference_id and "commissions/" in (doc.document_url or ""))
    if is_avulso and doc.document_url:
        key = extract_key_from_url(doc.document_url)
        if key:
            try:
                delete_file(key)
                logger.info(f"Documento avulso excluído do R2 com sucesso: {key}")
            except Exception as e:
                logger.error(f"Erro ao excluir documento avulso {key} do R2: {e}")

    db.delete(doc)
    db.commit()
    return None


@router.put("/commissions/{commission_id}/opinion")
def save_commission_opinion_admin(
    commission_id: UUID,
    payload: OpinionPayload,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Salva o parecer da comissão diretamente pelo painel administrativo da federação."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso está encerrado. O parecer está bloqueado para edições.")

    comm.opinion_report = payload.opinion_report
    if payload.approval_date is not None:
        comm.approval_date = payload.approval_date
    comm.opinion_updated_at = datetime.utcnow()
    db.commit()
    return {
        "message": "Parecer salvo com sucesso.",
        "opinion_updated_at": comm.opinion_updated_at.isoformat()
    }


@router.get("/commissions/{commission_id}/preview-pdf")
def preview_commission_pdf_admin(
    commission_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Gera a prévia em PDF do parecer da comissão a partir do painel da federação."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")

    congress = comm.congress
    fed = db.query(Federation).filter(Federation.id == congress.federation_id).first() if congress else None

    is_closed = bool(congress and congress.status == "encerrado")
    rel_name = comm.relator_name if is_closed else (comm.relator.full_name.strip() if (comm.relator and comm.relator.full_name) else (comm.relator_name or "Não informado"))
    members_names = [m.delegate_name if is_closed else (m.delegate.full_name.strip() if (m.delegate and m.delegate.full_name) else m.delegate_name) for m in comm.members]

    pdf_bytes = generate_commission_report(
        congress_title=congress.title if congress else "Congresso Ordinário",
        commission_name=comm.name,
        relator_name=rel_name,
        members_list=members_names,
        opinion_html=comm.opinion_report or "",
        approval_date=comm.approval_date,
        presbytery_name=fed.presbytery_name if fed else None,
        federation_name=fed.name if fed else None,
        validation_code=comm.validation_code,
        is_preview=True
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=previa_parecer_{comm.id}.pdf"}
    )


@router.post("/commissions/{commission_id}/approve")
def approve_commission_opinion(
    commission_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """
    Aprova oficialmente o parecer da comissão pela diretoria da federação:
    1. Gera código aleatório único de autenticidade (VAL-COM-YYYY-XXXXXXXX).
    2. Compila o PDF oficial com autenticidade no rodapé (sem marca d'água de prévia).
    3. Faz upload para o Cloudflare R2.
    4. Bloqueia a comissão para novas edições (status='aprovado').
    5. Grava url do parecer oficial, data, código de autenticidade e usuário que aprovou.
    """
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso já está encerrado. Não é possível aprovar pareceres.")

    if not comm.opinion_report or not comm.opinion_report.strip():
        raise HTTPException(status_code=400, detail="Esta comissão ainda não possui parecer redigido para aprovação.")

    congress = comm.congress
    fed = db.query(Federation).filter(Federation.id == congress.federation_id).first() if congress else None

    # Gerar código de validação único
    year = congress.fiscal_year if congress else datetime.utcnow().year
    import uuid as _uuid
    val_code = comm.validation_code or f"VAL-COM-{year}-{_uuid.uuid4().hex[:8].upper()}"
    comm.validation_code = val_code

    # Gerar PDF Oficial (is_preview=False)
    rel_name = comm.relator.full_name.strip() if (comm.relator and comm.relator.full_name) else (comm.relator_name or "Não informado")
    members_names = [(m.delegate.full_name.strip() if (m.delegate and m.delegate.full_name) else m.delegate_name) for m in comm.members]

    pdf_bytes = generate_commission_report(
        congress_title=congress.title if congress else "Congresso Ordinário",
        commission_name=comm.name,
        relator_name=rel_name,
        members_list=members_names,
        opinion_html=comm.opinion_report,
        approval_date=comm.approval_date,
        presbytery_name=fed.presbytery_name if fed else None,
        federation_name=fed.name if fed else None,
        validation_code=val_code,
        is_preview=False
    )

    # Upload para o Cloudflare R2
    key = f"congresses/{comm.congress_id}/parecer_{comm.id}.pdf"
    file_url = upload_file(pdf_bytes, key, "application/pdf")

    comm.status = "aprovado"
    comm.final_report_url = file_url
    comm.approved_at = datetime.utcnow()
    comm.approved_by = current_user.id
    db.commit()

    return {
        "message": "Parecer da comissão aprovado oficialmente com sucesso!",
        "commission": _serialize_commission(comm)
    }


# ── ROTAS PÚBLICAS (ACESSO POR TOKEN - SEM LOGIN) ──

@router.get("/public/commission/{token}")
def get_public_commission(
    token: str,
    db: Session = Depends(get_db)
):
    """Retorna os dados da comissão, lista de delegados, documentos com link e parecer atual."""
    comm = db.query(CongressCommission).filter(
        CongressCommission.access_token == token
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Link de comissão inválido ou não encontrado.")

    congress = comm.congress
    fed_name = "Federação"
    if congress:
        fed = db.query(Federation).filter(Federation.id == congress.federation_id).first()
        if fed:
            fed_name = fed.name

    return {
        "commission": _serialize_commission(comm),
        "congress": {
            "id": str(congress.id) if congress else None,
            "title": congress.title if congress else "Congresso",
            "fiscal_year": congress.fiscal_year if congress else None,
            "status": congress.status if congress else "aberto"
        },
        "federation_name": fed_name
    }


@router.put("/public/commission/{token}/opinion")
def save_public_commission_opinion(
    token: str,
    payload: OpinionPayload,
    db: Session = Depends(get_db)
):
    """
    Endpoint com Auto-Save para que o relator e os membros salvem o parecer em tempo real
    através do link público compartilhado.
    """
    comm = db.query(CongressCommission).filter(
        CongressCommission.access_token == token
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Link de comissão inválido.")

    if comm.status == "aprovado":
        raise HTTPException(status_code=403, detail="Este parecer já foi aprovado oficialmente pela diretoria e está bloqueado para edições.")
    if comm.congress and comm.congress.status == "encerrado":
        raise HTTPException(status_code=403, detail="Este congresso foi oficialmente encerrado pela federação. O parecer está bloqueado para edições.")

    comm.opinion_report = payload.opinion_report
    if payload.approval_date is not None:
        comm.approval_date = payload.approval_date
    comm.opinion_updated_at = datetime.utcnow()
    db.commit()

    return {
        "message": "Parecer salvo com sucesso.",
        "saved_at": comm.opinion_updated_at.strftime("%H:%M:%S")
    }


@router.get("/public/commission/{token}/preview-pdf")
def preview_public_commission_pdf(
    token: str,
    db: Session = Depends(get_db)
):
    """Gera a prévia em PDF do parecer da comissão com layout oficial (sem aprovação)."""
    comm = db.query(CongressCommission).filter(
        CongressCommission.access_token == token
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")

    congress = comm.congress
    fed = db.query(Federation).filter(Federation.id == congress.federation_id).first() if congress else None

    is_closed = bool(congress and congress.status == "encerrado")
    rel_name = comm.relator_name if is_closed else (comm.relator.full_name.strip() if (comm.relator and comm.relator.full_name) else (comm.relator_name or "Não informado"))
    members_names = [m.delegate_name if is_closed else (m.delegate.full_name.strip() if (m.delegate and m.delegate.full_name) else m.delegate_name) for m in comm.members]

    pdf_bytes = generate_commission_report(
        congress_title=congress.title if congress else "Congresso Ordinário",
        commission_name=comm.name,
        relator_name=rel_name,
        members_list=members_names,
        opinion_html=comm.opinion_report or "",
        approval_date=comm.approval_date,
        presbytery_name=fed.presbytery_name if fed else None,
        federation_name=fed.name if fed else None,
        validation_code=comm.validation_code,
        is_preview=True
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=previa_parecer_{comm.id}.pdf"}
    )


# ── ROTAS DE CREDENCIAIS (FEDERAÇÃO, UMP LOCAL E PÚBLICO) ──

@router.post("/{congress_id}/my-credential")
def save_my_credential(
    congress_id: UUID,
    payload: CredentialSavePayload,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db)
):
    """Salva os dados do rascunho da credencial e a lista de delegados pela UMP Local."""
    is_leader, _ = _is_local_leader(current_user.id, db)
    if not is_leader:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o Presidente e o Vice-Presidente da UMP Local têm permissão para preencher a credencial."
        )

    local_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    if not local_ump:
        raise HTTPException(status_code=404, detail="UMP Local não encontrada.")

    congress = db.query(Congress).filter(Congress.id == congress_id).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")

    cred = db.query(CongressCredential).filter(
        CongressCredential.congress_id == congress.id,
        CongressCredential.local_ump_id == local_ump.id
    ).first()

    if not cred:
        cred = CongressCredential(
            congress_id=congress.id,
            local_ump_id=local_ump.id,
            status="rascunho",
            document_date=date.today()
        )
        db.add(cred)
        db.flush()

    if cred.status in ("enviada", "homologada"):
        raise HTTPException(status_code=400, detail="Esta credencial já foi enviada à Federação e não pode mais ser alterada.")

    # Se o pastor já havia aprovado, mas a lista de delegados mudou, o status volta para aguardando pastor
    existing_del_names = [d.delegate_name.strip().upper() for d in cred.delegates]
    new_del_names = [d.delegate_name.strip().upper() for d in payload.delegates if d.delegate_name.strip()]
    if cred.status == "aprovado_pastor" and existing_del_names != new_del_names:
        cred.status = "aguardando_pastor"
        cred.pastor_approved_at = None
        cred.pastor_selfie_url = None

    if payload.pastor_name is not None:
        cred.pastor_name = payload.pastor_name.strip()
    if payload.city is not None:
        cred.city = payload.city.strip()
    if payload.notes is not None:
        cred.notes = payload.notes.strip()

    # Atualiza lista de delegados
    db.query(CongressCredentialDelegate).filter(CongressCredentialDelegate.credential_id == cred.id).delete()

    min_d = congress.min_delegates or 1
    for idx, d_item in enumerate(payload.delegates, start=1):
        d_name = d_item.delegate_name.strip()
        if not d_name:
            continue
        is_opt = idx > min_d
        delegate_obj = CongressCredentialDelegate(
            credential_id=cred.id,
            member_id=d_item.member_id,
            delegate_name=d_name,
            order_index=idx,
            is_optional=is_opt
        )
        db.add(delegate_obj)

    if cred.status == "rascunho" and new_del_names:
        cred.status = "aguardando_pastor"

    db.commit()
    db.refresh(cred)
    return {
        "message": "Credencial salva com sucesso.",
        "credential": _serialize_credential(cred, include_token=True)
    }


@router.post("/credentials/{credential_id}/submit")
def submit_credential_to_federation(
    credential_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db)
):
    """
    Submete a credencial à Federação:
    1. Valida se a quantidade de delegados respeita o mínimo e o máximo estipulados pela federação.
    2. Valida se o pastor aprovou via foto selfie.
    3. Registra a assinatura automática do Presidente logado.
    4. Atualiza o status para 'enviada'.
    """
    is_leader, _ = _is_local_leader(current_user.id, db)
    if not is_leader:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o Presidente e o Vice-Presidente da UMP Local têm permissão para assinar e enviar a credencial."
        )

    cred = db.query(CongressCredential).filter(
        CongressCredential.id == credential_id,
        CongressCredential.local_ump_id == current_user.organization_id
    ).first()

    if not cred:
        raise HTTPException(status_code=404, detail="Credencial não encontrada.")

    congress = cred.congress
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso vinculado não encontrado.")

    if congress.status == "encerrado":
        raise HTTPException(status_code=400, detail="Este congresso já foi encerrado pela Federação.")

    del_count = len(cred.delegates)
    min_d = congress.min_delegates or 1
    max_d = congress.max_delegates or 5

    if del_count < min_d:
        raise HTTPException(status_code=400, detail=f"A credencial precisa de pelo menos {min_d} delegado(s). Atualmente possui {del_count}.")
    if del_count > max_d:
        raise HTTPException(status_code=400, detail=f"A credencial permite no máximo {max_d} delegados. Atualmente possui {del_count}.")

    if cred.status != "aprovado_pastor" or not cred.pastor_approved_at:
        raise HTTPException(
            status_code=400,
            detail="A credencial precisa ser aprovada pelo Pastor da igreja via foto/selfie antes do envio à Federação."
        )

    # Assinatura automática da Presidência da UMP
    cred.president_name = current_user.full_name
    cred.president_signed_at = datetime.utcnow()
    cred.submitted_at = datetime.utcnow()
    cred.submitted_by = current_user.id
    cred.validation_code = cred.validation_code or f"VAL-CRED-{congress.fiscal_year}-{_uuid.uuid4().hex[:8].upper()}"
    cred.status = "enviada"

    db.commit()
    db.refresh(cred)

    return {
        "message": "Credencial enviada com sucesso à Federação!",
        "credential": _serialize_credential(cred, include_token=True)
    }


# ── ROTAS DA FEDERAÇÃO PARA CREDENCIAIS ──

@router.put("/{congress_id}/delegate-limits")
def update_congress_delegate_limits(
    congress_id: UUID,
    payload: DelegateLimitsPayload,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Atualiza a quantidade mínima e máxima de delegados permitida por UMP Local no congresso."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")

    if payload.min_delegates < 1:
        raise HTTPException(status_code=400, detail="A quantidade mínima de delegados deve ser de pelo menos 1.")
    if payload.max_delegates < payload.min_delegates:
        raise HTTPException(status_code=400, detail="A quantidade máxima não pode ser menor que a quantidade mínima.")

    congress.min_delegates = payload.min_delegates
    congress.max_delegates = payload.max_delegates
    db.commit()

    return {
        "message": "Limites de delegados atualizados com sucesso.",
        "min_delegates": congress.min_delegates,
        "max_delegates": congress.max_delegates
    }


@router.get("/{congress_id}/credentials")
def list_congress_credentials(
    congress_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Lista todas as UMPs Locais e o status da sua respectiva credencial para este congresso."""
    congress = db.query(Congress).filter(
        Congress.id == congress_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not congress:
        raise HTTPException(status_code=404, detail="Congresso não encontrado.")

    # Todas as UMPs locais ativas da federação (exclui a própria federação e sombras de eleições)
    local_umps = db.query(LocalUmp).filter(
        LocalUmp.federation_id == current_user.organization_id,
        LocalUmp.id != current_user.organization_id,
        ~LocalUmp.name.ilike('%eleiç%'),
        ~LocalUmp.name.ilike('%eleic%'),
        LocalUmp.is_active == True
    ).order_by(LocalUmp.name).all()

    # Todas as credenciais já cadastradas para este congresso
    credentials_map = {
        cred.local_ump_id: cred
        for cred in congress.credentials
    }

    results = []
    total_delegates = 0
    total_submitted = 0
    total_pastor_approved = 0
    total_pending = 0

    for lump in local_umps:
        cred = credentials_map.get(lump.id)
        if cred:
            serialized = _serialize_credential(cred, include_token=True)
            delegates_count = len(cred.delegates)
            total_delegates += delegates_count
            if cred.status in ("enviada", "homologada"):
                total_submitted += 1
            elif cred.status == "aprovado_pastor":
                total_pastor_approved += 1
            else:
                total_pending += 1
        else:
            serialized = {
                "id": None,
                "congress_id": str(congress.id),
                "local_ump_id": str(lump.id),
                "local_ump_name": lump.name,
                "church_name": lump.church_name,
                "status": "nao_iniciada",
                "city": lump.cidade,
                "document_date": None,
                "pastor_name": lump.pastor_name,
                "pastor_token": None,
                "pastor_selfie_url": None,
                "pastor_approved_at": None,
                "president_name": None,
                "president_signed_at": None,
                "submitted_at": None,
                "validation_code": None,
                "homologated_at": None,
                "notes": None,
                "delegates_count": 0,
                "delegates": []
            }
            total_pending += 1

        results.append(serialized)

    return {
        "congress_id": str(congress.id),
        "congress_title": congress.title,
        "fiscal_year": congress.fiscal_year,
        "min_delegates": congress.min_delegates or 1,
        "max_delegates": congress.max_delegates or 5,
        "summary": {
            "total_local_umps": len(local_umps),
            "total_submitted": total_submitted,
            "total_pastor_approved": total_pastor_approved,
            "total_pending": total_pending,
            "total_delegates": total_delegates
        },
        "credentials": results
    }


@router.post("/credentials/{credential_id}/homologate")
def homologate_credential(
    credential_id: UUID,
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """Homologa oficialmente a credencial de uma UMP Local pela diretoria da federação."""
    cred = db.query(CongressCredential).join(Congress).filter(
        CongressCredential.id == credential_id,
        Congress.federation_id == current_user.organization_id
    ).first()

    if not cred:
        raise HTTPException(status_code=404, detail="Credencial não encontrada.")

    cred.status = "homologada"
    cred.homologated_at = datetime.utcnow()
    cred.homologated_by = current_user.id
    db.commit()
    db.refresh(cred)

    return {
        "message": "Credencial homologada com sucesso!",
        "credential": _serialize_credential(cred, include_token=True)
    }


# ── ROTAS PÚBLICAS (ACESSO PASTORAL POR TOKEN - SEM LOGIN) ──

@router.get("/public/credential/{token}")
def get_public_credential(
    token: str,
    db: Session = Depends(get_db)
):
    """Retorna os dados da credencial para conferência pública do pastor."""
    cred = db.query(CongressCredential).filter(
        CongressCredential.pastor_token == token
    ).first()

    if not cred:
        raise HTTPException(status_code=404, detail="Link de credencial inválido ou não encontrado.")

    congress = cred.congress
    local_ump = cred.local_ump
    fed = db.query(Federation).filter(Federation.id == congress.federation_id).first() if congress else None

    return {
        "credential": _serialize_credential(cred, include_token=False),
        "congress": {
            "id": str(congress.id) if congress else None,
            "title": congress.title if congress else "Congresso",
            "fiscal_year": congress.fiscal_year if congress else None,
            "status": congress.status if congress else "aberto",
            "min_delegates": congress.min_delegates or 1,
            "max_delegates": congress.max_delegates or 5
        },
        "federation": {
            "name": fed.name if fed else "Federação",
            "presbytery_name": fed.presbytery_name if fed else "",
            "synodal_name": fed.synodal_name if fed else "",
        },
        "local_ump": {
            "name": local_ump.name if local_ump else "",
            "church_name": local_ump.church_name if local_ump else "",
            "cidade": local_ump.cidade if local_ump else "",
        }
    }


@router.post("/public/credential/{token}/approve")
async def approve_public_credential(
    token: str,
    pastor_name: Optional[str] = Form(None),
    selfie_file: Optional[UploadFile] = File(None),
    selfie_base64: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Recebe a aprovação do pastor com a selfie (via arquivo multipart ou base64).
    Faz o upload da foto para o Cloudflare R2 e marca a credencial como 'aprovado_pastor'.
    """
    cred = db.query(CongressCredential).filter(
        CongressCredential.pastor_token == token
    ).first()

    if not cred:
        raise HTTPException(status_code=404, detail="Link de credencial inválido.")

    if cred.status in ("enviada", "homologada"):
        return {
            "message": "Esta credencial já foi homologada e enviada.",
            "credential": _serialize_credential(cred, include_token=False)
        }

    # Obter os bytes da imagem
    image_bytes = None
    if selfie_file and selfie_file.filename:
        image_bytes = await selfie_file.read()
    elif selfie_base64 and selfie_base64.strip():
        raw_b64 = selfie_base64.split(",")[-1]
        try:
            image_bytes = base64.b64decode(raw_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail="Formato de imagem base64 inválido.")

    if not image_bytes or len(image_bytes) < 100:
        raise HTTPException(status_code=400, detail="A foto selfie é obrigatória para aprovar a credencial.")

    # Redimensiona imagem se necessário
    resized_bytes = resize_image_max_size(image_bytes, max_size=1000)

    # Upload para o Cloudflare R2
    file_key = f"congresses/{cred.congress_id}/credentials/{cred.id}/pastor_selfie_{_uuid.uuid4().hex[:6]}.jpg"
    selfie_url = upload_file(resized_bytes, file_key, "image/jpeg")

    cred.pastor_selfie_url = selfie_url
    cred.pastor_approved_at = datetime.utcnow()
    if pastor_name and pastor_name.strip():
        cred.pastor_name = pastor_name.strip()
    cred.status = "aprovado_pastor"

    db.commit()
    db.refresh(cred)

    return {
        "message": "Credencial aprovada com sucesso pelo Pastor!",
        "credential": _serialize_credential(cred, include_token=False)
    }


# ── ROTA DE PDF DA CREDENCIAL ──

@router.get("/credentials/{credential_id}/pdf")
def get_credential_pdf(
    credential_id: UUID,
    db: Session = Depends(get_db)
):
    """Gera e retorna o PDF oficial formatado da Credencial de Delegados."""
    cred = db.query(CongressCredential).filter(
        CongressCredential.id == credential_id
    ).first()

    if not cred:
        raise HTTPException(status_code=404, detail="Credencial não encontrada.")

    congress = cred.congress
    local_ump = cred.local_ump
    fed = db.query(Federation).filter(Federation.id == congress.federation_id).first() if congress else None

    delegates_list = [
        {
            "delegate_name": d.delegate_name,
            "is_optional": d.is_optional
        }
        for d in cred.delegates
    ]

    pdf_bytes = generate_credential_pdf(
        congress_title=congress.title if congress else "Congresso Ordinário",
        fiscal_year=congress.fiscal_year if congress else datetime.utcnow().year,
        church_name=local_ump.church_name or local_ump.name if local_ump else "Igreja Local",
        delegates=delegates_list,
        president_name=cred.president_name or (local_ump.name if local_ump else "Presidente"),
        pastor_name=cred.pastor_name or (local_ump.pastor_name if local_ump else "Pastor"),
        city=cred.city or (local_ump.cidade if local_ump else "Patos"),
        document_date=cred.document_date or date.today(),
        federation_name=fed.name if fed else "Federação de UMPs",
        presbytery_name=fed.presbytery_name if fed else "Presbitério",
        synodal_name=fed.synodal_name if fed else "Sínodo Paraíba",
        pastor_approved_at=cred.pastor_approved_at,
        president_signed_at=cred.president_signed_at,
        validation_code=cred.validation_code,
        is_preview=(cred.status not in ("enviada", "homologada"))
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=credencial_{cred.id}.pdf"}
    )

