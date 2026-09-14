import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status, Response
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
from app.services.pdf_generator import generate_commission_report
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
    approval_date: Optional[str] = None


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
        "approval_date": comm.approval_date,
        "validation_code": comm.validation_code,
        "status": comm.status or "em_elaboracao",
        "final_report_url": _presign_url_if_needed(comm.final_report_url),
        "approved_at": comm.approved_at.isoformat() if comm.approved_at else None,
        "approved_by": str(comm.approved_by) if comm.approved_by else None,
        "is_locked": (comm.status == "aprovado"),
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

    content = await file.read()
    if len(content) > 25 * 1024 * 1024:  # 25 MB max
        raise HTTPException(status_code=400, detail="Arquivo muito grande. O limite máximo é 25MB.")

    key = f"congresses/{comm.congress_id}/commissions/{comm.id}/{file.filename}"
    uploaded_url = upload_file(content, key, file.content_type or "application/pdf")

    doc = CongressCommissionDocument(
        commission_id=comm.id,
        title=title.strip(),
        category=category,
        origin_name=origin_name.strip() if origin_name else "Avulso",
        document_url=uploaded_url.split('?')[0].strip()
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

    pdf_bytes = generate_commission_report(
        congress_title=congress.title if congress else "Congresso Ordinário",
        commission_name=comm.name,
        relator_name=comm.relator_name,
        members_list=[m.delegate_name for m in comm.members],
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
    pdf_bytes = generate_commission_report(
        congress_title=congress.title if congress else "Congresso Ordinário",
        commission_name=comm.name,
        relator_name=comm.relator_name,
        members_list=[m.delegate_name for m in comm.members],
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

    pdf_bytes = generate_commission_report(
        congress_title=congress.title if congress else "Congresso Ordinário",
        commission_name=comm.name,
        relator_name=comm.relator_name,
        members_list=[m.delegate_name for m in comm.members],
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
