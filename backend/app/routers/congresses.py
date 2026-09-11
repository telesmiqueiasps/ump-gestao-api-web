import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.session import get_db
from app.core.dependencies import get_current_user, require_federation
from app.models.user import User
from app.models.federation import Federation
from app.models.local_ump import LocalUmp
from app.models.member import Member
from app.models.finance import FinancialPeriod
from app.models.activity_report import ActivityReport
from app.models.ump_statistic import UmpStatisticCollector
from app.models.congress import Congress, CongressCommission, CongressCommissionMember, CongressCommissionDocument
from app.services.storage import get_presigned_url, upload_file
from app.core.config import get_settings

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


# ── HELPERS ──

def _presign_url_if_needed(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    # Se já for URL absoluta externa http/https, tenta extrair caminho ou retorna como está
    match = re.search(r'(?:/file/[^/]+/|/)(activities/.+|receipts/.+|logos/.+|reports/.+|pix-qr/.+|signatures/.+|congresses/.+)$', url)
    if match:
        return get_presigned_url(match.group(1), expires_in=7200)
    return url


def _serialize_commission(comm: CongressCommission) -> dict:
    return {
        "id": str(comm.id),
        "congress_id": str(comm.congress_id),
        "name": comm.name,
        "description": comm.description,
        "relator_id": str(comm.relator_id) if comm.relator_id else None,
        "relator_name": comm.relator_name,
        "access_token": comm.access_token,
        "opinion_report": comm.opinion_report or "",
        "opinion_updated_at": comm.opinion_updated_at.isoformat() if comm.opinion_updated_at else None,
        "has_opinion": bool(comm.opinion_report and comm.opinion_report.strip()),
        "created_at": comm.created_at.isoformat() if comm.created_at else None,
        "members": [
            {
                "id": str(m.id),
                "delegate_id": str(m.delegate_id) if m.delegate_id else None,
                "delegate_name": m.delegate_name,
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


def _serialize_congress(c: Congress, include_commissions: bool = True) -> dict:
    data = {
        "id": str(c.id),
        "federation_id": str(c.federation_id),
        "title": c.title,
        "fiscal_year": c.fiscal_year,
        "description": c.description,
        "status": c.status,
        "created_by": str(c.created_by) if c.created_by else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "commissions_count": len(c.commissions) if c.commissions else 0,
        "total_documents_count": sum(len(comm.documents) for comm in c.commissions) if c.commissions else 0
    }
    if include_commissions and c.commissions:
        data["commissions"] = [_serialize_commission(comm) for comm in c.commissions]
    else:
        data["commissions"] = []
    return data


# ── ROTAS AUTENTICADAS (FEDERAÇÃO) ──

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
        congress.status = payload.status

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

    comm.relator_id = payload.relator_id
    comm.relator_name = payload.relator_name.strip() if payload.relator_name else None

    # Remove membros antigos e adiciona os novos
    db.query(CongressCommissionMember).filter(CongressCommissionMember.commission_id == comm.id).delete()

    for m in payload.members:
        member_obj = CongressCommissionMember(
            commission_id=comm.id,
            delegate_id=m.delegate_id,
            delegate_name=m.delegate_name.strip(),
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
    current_user: User = Depends(require_federation),
    db: Session = Depends(get_db)
):
    """
    Retorna todos os documentos do sistema gerados pelas UMPs Locais e pela própria Federação,
    prontos para serem selecionados e disponibilizados para as comissões.
    """
    fed_id = current_user.organization_id
    fed_obj = db.query(Federation).filter(Federation.id == fed_id).first()
    fed_name = fed_obj.name if fed_obj else "Federação"

    locals_in_fed = db.query(LocalUmp).filter(
        LocalUmp.federation_id == fed_id,
        LocalUmp.id != fed_id
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
                    "document_url": _presign_url_if_needed(p.report_url),
                    "fiscal_year": p.fiscal_year,
                    "external_reference_id": str(p.id)
                })
            if p.receipts_report_url:
                documents.append({
                    "id": f"rec_{p.id}",
                    "title": f"Comprovantes Financeiros {p.fiscal_year} — {loc.name}",
                    "category": "comprovantes",
                    "origin_name": loc.name,
                    "document_url": _presign_url_if_needed(p.receipts_report_url),
                    "fiscal_year": p.fiscal_year,
                    "external_reference_id": str(p.id)
                })

        # B. Relatórios de Atividades Publicados
        act_query = db.query(ActivityReport).filter(
            ActivityReport.organization_id == loc.id,
            ActivityReport.status == "publicado"
        )
        if year:
            act_query = act_query.filter(ActivityReport.fiscal_year == year)
        act_reports = act_query.order_by(desc(ActivityReport.fiscal_year)).all()

        for a in act_reports:
            if a.pdf_url:
                documents.append({
                    "id": f"act_{a.id}",
                    "title": f"Relatório de Atividades {a.fiscal_year} — {loc.name}",
                    "category": "atividades",
                    "origin_name": loc.name,
                    "document_url": _presign_url_if_needed(a.pdf_url),
                    "fiscal_year": a.fiscal_year,
                    "external_reference_id": str(a.id)
                })

        # C. Levantamentos Estatísticos Concluídos
        stat_query = db.query(UmpStatisticCollector).filter(
            UmpStatisticCollector.local_ump_id == loc.id
        )
        if year:
            stat_query = stat_query.filter(UmpStatisticCollector.fiscal_year == year)
        collectors = stat_query.all()
        for col in collectors:
            documents.append({
                "id": f"stat_{col.id}",
                "title": f"Dados Estatísticos {col.fiscal_year} — {loc.name}",
                "category": "estatistica",
                "origin_name": loc.name,
                "document_url": f"/pages/ump-statistics.html?local_id={loc.id}&year={col.fiscal_year}",
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
                "document_url": _presign_url_if_needed(fp.report_url),
                "fiscal_year": fp.fiscal_year,
                "external_reference_id": str(fp.id)
            })
        if fp.receipts_report_url:
            documents.append({
                "id": f"rec_fed_{fp.id}",
                "title": f"Comprovantes Financeiros {fp.fiscal_year} — {fed_name}",
                "category": "comprovantes",
                "origin_name": fed_name,
                "document_url": _presign_url_if_needed(fp.receipts_report_url),
                "fiscal_year": fp.fiscal_year,
                "external_reference_id": str(fp.id)
            })

    # Relatório de atividades da Federação
    fed_act_query = db.query(ActivityReport).filter(
        ActivityReport.organization_id == fed_id,
        ActivityReport.status == "publicado"
    )
    if year:
        fed_act_query = fed_act_query.filter(ActivityReport.fiscal_year == year)
    fed_acts = fed_act_query.order_by(desc(ActivityReport.fiscal_year)).all()

    for fa in fed_acts:
        if fa.pdf_url:
            documents.append({
                "id": f"act_fed_{fa.id}",
                "title": f"Relatório de Atividades {fa.fiscal_year} — {fed_name}",
                "category": "atividades",
                "origin_name": fed_name,
                "document_url": _presign_url_if_needed(fa.pdf_url),
                "fiscal_year": fa.fiscal_year,
                "external_reference_id": str(fa.id)
            })

    # Dados estatísticos consolidados da Federação
    if year:
        documents.append({
            "id": f"stat_fed_{year}",
            "title": f"Dados Estatísticos Consolidados {year} — {fed_name}",
            "category": "estatistica",
            "origin_name": fed_name,
            "document_url": f"/pages/ump-statistics.html?year={year}",
            "fiscal_year": year,
            "external_reference_id": f"fed_{year}"
        })

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

    new_docs = []
    for item in payload:
        # Evita duplicidade por URL e título
        exists = db.query(CongressCommissionDocument).filter(
            CongressCommissionDocument.commission_id == comm.id,
            CongressCommissionDocument.document_url == item.document_url
        ).first()
        if not exists:
            doc = CongressCommissionDocument(
                commission_id=comm.id,
                title=item.title.strip(),
                category=item.category,
                origin_name=item.origin_name.strip() if item.origin_name else None,
                document_url=item.document_url,
                external_reference_id=item.external_reference_id
            )
            db.add(doc)
            new_docs.append(doc)

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

    content = await file.read()
    if len(content) > 25 * 1024 * 1024:  # 25 MB max
        raise HTTPException(status_code=400, detail="Arquivo muito grande. O limite máximo é 25MB.")

    key = f"congresses/{comm.congress_id}/commissions/{comm.id}/{file.filename}"
    uploaded_url = upload_file(key, content, content_type=file.content_type or "application/pdf")

    doc = CongressCommissionDocument(
        commission_id=comm.id,
        title=title.strip(),
        category=category,
        origin_name=origin_name.strip() if origin_name else "Avulso",
        document_url=uploaded_url
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
    """Remove um documento vinculado à comissão."""
    comm = db.query(CongressCommission).join(Congress).filter(
        CongressCommission.id == commission_id,
        Congress.federation_id == current_user.organization_id
    ).first()
    if not comm:
        raise HTTPException(status_code=404, detail="Comissão não encontrada.")

    doc = db.query(CongressCommissionDocument).filter(
        CongressCommissionDocument.id == doc_id,
        CongressCommissionDocument.commission_id == comm.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

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

    comm.opinion_report = payload.opinion_report
    comm.opinion_updated_at = datetime.utcnow()
    db.commit()
    return {
        "message": "Parecer salvo com sucesso.",
        "opinion_updated_at": comm.opinion_updated_at.isoformat()
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

    comm.opinion_report = payload.opinion_report
    comm.opinion_updated_at = datetime.utcnow()
    db.commit()

    return {
        "message": "Parecer salvo com sucesso.",
        "saved_at": comm.opinion_updated_at.strftime("%H:%M:%S")
    }
