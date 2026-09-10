import datetime
from uuid import UUID
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.models.user import User
from app.models.enums import OrgType, BoardRole, MemberType
from app.models.local_ump import LocalUmp
from app.models.member import Member
from app.models.ump_statistic import (
    UmpStatisticCollector,
    UmpStatisticResponse,
    generate_unique_token
)
from app.core.dependencies import require_local_or_federation, get_current_user

router = APIRouter()

# ── SCHEMAS ──

class SurveyAnswerPayload(BaseModel):
    birth_date: Optional[datetime.date] = None
    gender: Optional[str] = None
    education_level: Optional[str] = None
    marital_status: Optional[str] = None
    has_children: Optional[bool] = None
    has_disabilities: Optional[bool] = None
    disabilities: Optional[List[str]] = None
    other_disability: Optional[str] = None


class ManualAnswerPayload(SurveyAnswerPayload):
    response_id: UUID


VALID_GENDERS = ["Masculino", "Feminino"]
VALID_EDUCATION = [
    "Ensino Fundamental",
    "Ensino Médio",
    "Técnico",
    "Superior",
    "Pós-graduação"
]
VALID_MARITAL_STATUS = [
    "Solteiro(a)",
    "Casado(a)",
    "Divorciado(a)",
    "Viúvo(a)"
]
VALID_DISABILITIES = [
    "surdo",
    "deficiente_auditivo",
    "cego",
    "baixa_visao",
    "deficiencia_fisica_membro_inferior",
    "deficiencia_fisica_membro_superior",
    "transtorno_neurologico",
    "deficiencia_intelectual",
    "outros"
]


# ── HELPERS ──

def _resolve_local_ump_id(current_user: User, db: Session, requested_local_id: Optional[UUID] = None) -> UUID:
    """Identifica a UMP Local a ser consultada com base no usuário autenticado."""
    if current_user.organization_type == OrgType.local_ump:
        return current_user.organization_id
    
    # Federação: pode especificar o local_ump_id ou usa a primeira UMP local pertencente a ela
    if requested_local_id:
        local = db.query(LocalUmp).filter(
            LocalUmp.id == requested_local_id,
            LocalUmp.federation_id == current_user.organization_id
        ).first()
        if not local:
            raise HTTPException(status_code=404, detail="UMP Local não encontrada nesta Federação")
        return local.id
    
    first_local = db.query(LocalUmp).filter(
        LocalUmp.federation_id == current_user.organization_id
    ).order_by(LocalUmp.name.asc()).first()
    
    if not first_local:
        raise HTTPException(status_code=404, detail="Nenhuma UMP Local cadastrada nesta Federação")
    return first_local.id


def _get_or_create_collector_with_sync(local_ump_id: UUID, year: int, db: Session, user_id: Optional[UUID] = None) -> UmpStatisticCollector:
    collector = db.query(UmpStatisticCollector).filter(
        UmpStatisticCollector.local_ump_id == local_ump_id,
        UmpStatisticCollector.fiscal_year == year
    ).first()

    if not collector:
        local_ump = db.query(LocalUmp).filter(LocalUmp.id == local_ump_id).first()
        ump_name = local_ump.name if local_ump else "UMP Local"
        collector = UmpStatisticCollector(
            local_ump_id=local_ump_id,
            fiscal_year=year,
            title=f"Censo Estatístico {year} — {ump_name}",
            created_by=user_id
        )
        db.add(collector)
        db.commit()
        db.refresh(collector)

    # Sincroniza membros ativos e cooperadores
    members = db.query(Member).filter(
        Member.local_ump_id == local_ump_id,
        Member.is_active == True,
        Member.member_type.in_([MemberType.ativo, MemberType.cooperador])
    ).all()

    existing_responses = db.query(UmpStatisticResponse).filter(
        UmpStatisticResponse.collector_id == collector.id
    ).all()
    existing_member_ids = {r.member_id for r in existing_responses}
    existing_tokens = {r.access_token for r in existing_responses}

    new_responses = []
    for m in members:
        if m.id not in existing_member_ids:
            token = generate_unique_token(existing_tokens)
            existing_tokens.add(token)
            resp = UmpStatisticResponse(
                collector_id=collector.id,
                member_id=m.id,
                access_token=token,
                has_responded=False,
                birth_date=m.birth_date
            )
            new_responses.append(resp)

    if new_responses:
        db.add_all(new_responses)
        db.commit()

    return collector


def _calculate_age(birth_date: datetime.date, ref_date: datetime.date = None) -> Optional[int]:
    if not birth_date:
        return None
    if not ref_date:
        ref_date = datetime.date.today()
    age = ref_date.year - birth_date.year
    if (ref_date.month, ref_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


# ── ROTAS DE GESTÃO (DIRETORIA) ──

@router.get("/collector")
def get_collector_status(
    year: int = Query(default=None),
    local_ump_id: Optional[UUID] = None,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db)
):
    """Retorna o estado do coletor de dados para o ano especificado, incluindo lista de sócios."""
    target_year = year or datetime.date.today().year
    resolved_local_id = _resolve_local_ump_id(current_user, db, local_ump_id)

    collector = _get_or_create_collector_with_sync(resolved_local_id, target_year, db, current_user.id)

    # Busca respostas com dados dos membros associados
    responses = db.query(UmpStatisticResponse, Member).join(
        Member, UmpStatisticResponse.member_id == Member.id
    ).filter(
        UmpStatisticResponse.collector_id == collector.id
    ).order_by(Member.full_name.asc()).all()

    total_voters = len(responses)
    responded_count = sum(1 for r, _ in responses if r.has_responded)
    pending_count = total_voters - responded_count
    pct_complete = round((responded_count / total_voters) * 100) if total_voters > 0 else 0

    local_obj = db.query(LocalUmp).filter(LocalUmp.id == resolved_local_id).first()

    voters_data = []
    for resp, memb in responses:
        voters_data.append({
            "response_id": str(resp.id),
            "member_id": str(memb.id),
            "full_name": memb.full_name,
            "member_type": memb.member_type.value if memb.member_type else "ativo",
            "phone": memb.phone,
            "access_token": resp.access_token,
            "has_responded": resp.has_responded,
            "responded_at": resp.responded_at.isoformat() if resp.responded_at else None,
            "answers": {
                "birth_date": resp.birth_date.isoformat() if resp.birth_date else None,
                "gender": resp.gender,
                "education_level": resp.education_level,
                "marital_status": resp.marital_status,
                "has_children": resp.has_children,
                "has_disabilities": resp.has_disabilities,
                "disabilities": resp.disabilities or [],
                "other_disability": resp.other_disability
            } if resp.has_responded else None
        })

    # Lista de UMPs locais caso o usuário logado seja federação
    available_locals = []
    if current_user.organization_type == OrgType.federation:
        locals_in_fed = db.query(LocalUmp).filter(
            LocalUmp.federation_id == current_user.organization_id
        ).order_by(LocalUmp.name.asc()).all()
        available_locals = [{"id": str(l.id), "name": l.name} for l in locals_in_fed]

    return {
        "collector_id": str(collector.id),
        "local_ump_id": str(resolved_local_id),
        "local_ump_name": local_obj.name if local_obj else "UMP Local",
        "fiscal_year": collector.fiscal_year,
        "title": collector.title,
        "total_members": total_voters,
        "responded_count": responded_count,
        "pending_count": pending_count,
        "percent_complete": pct_complete,
        "available_locals": available_locals,
        "voters": voters_data
    }


@router.post("/collector/sync")
def sync_collector_members(
    year: int = Query(default=None),
    local_ump_id: Optional[UUID] = None,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db)
):
    """Sincroniza os membros da UMP Local no coletor do ano."""
    target_year = year or datetime.date.today().year
    resolved_local_id = _resolve_local_ump_id(current_user, db, local_ump_id)
    _get_or_create_collector_with_sync(resolved_local_id, target_year, db, current_user.id)
    return {"message": "Sócios sincronizados com sucesso."}


@router.get("/metrics")
def get_ump_statistics_metrics(
    year: int = Query(default=None),
    local_ump_id: Optional[UUID] = None,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db)
):
    """Retorna os quantitativos e percentuais consolidados para o painel de estatísticas."""
    target_year = year or datetime.date.today().year
    resolved_local_id = _resolve_local_ump_id(current_user, db, local_ump_id)

    collector = db.query(UmpStatisticCollector).filter(
        UmpStatisticCollector.local_ump_id == resolved_local_id,
        UmpStatisticCollector.fiscal_year == target_year
    ).first()

    if not collector:
        collector = _get_or_create_collector_with_sync(resolved_local_id, target_year, db, current_user.id)

    responses = db.query(UmpStatisticResponse).filter(
        UmpStatisticResponse.collector_id == collector.id
    ).all()

    total_registered = len(responses)
    responded_list = [r for r in responses if r.has_responded]
    total_responded = len(responded_list)

    # 1. Faixas Etárias
    age_groups = {
        "15_18": 0,
        "19_23": 0,
        "24_29": 0,
        "30_35": 0,
        "36_plus": 0,
        "not_informed": 0
    }
    ages_list = []
    for r in responded_list:
        age = _calculate_age(r.birth_date)
        if age is None:
            age_groups["not_informed"] += 1
        else:
            ages_list.append(age)
            if age <= 18:
                age_groups["15_18"] += 1
            elif 19 <= age <= 23:
                age_groups["19_23"] += 1
            elif 24 <= age <= 29:
                age_groups["24_29"] += 1
            elif 30 <= age <= 35:
                age_groups["30_35"] += 1
            else:
                age_groups["36_plus"] += 1

    average_age = round(sum(ages_list) / len(ages_list), 1) if ages_list else 0

    # 2. Sexo
    gender_counts = {"Masculino": 0, "Feminino": 0, "Outro/Não informado": 0}
    for r in responded_list:
        if r.gender == "Masculino":
            gender_counts["Masculino"] += 1
        elif r.gender == "Feminino":
            gender_counts["Feminino"] += 1
        else:
            gender_counts["Outro/Não informado"] += 1

    # 3. Escolaridade
    education_counts = {level: 0 for level in VALID_EDUCATION}
    education_counts["Não informado"] = 0
    for r in responded_list:
        if r.education_level in education_counts:
            education_counts[r.education_level] += 1
        else:
            education_counts["Não informado"] += 1

    # 4. Estado Civil
    marital_counts = {status: 0 for status in VALID_MARITAL_STATUS}
    marital_counts["Não informado"] = 0
    for r in responded_list:
        if r.marital_status in marital_counts:
            marital_counts[r.marital_status] += 1
        else:
            marital_counts["Não informado"] += 1

    # 5. Filhos
    children_counts = {"com_filhos": 0, "sem_filhos": 0, "nao_informado": 0}
    for r in responded_list:
        if r.has_children is True:
            children_counts["com_filhos"] += 1
        elif r.has_children is False:
            children_counts["sem_filhos"] += 1
        else:
            children_counts["nao_informado"] += 1

    # 6. Deficiências e Acessibilidade
    disabilities_general = {"com_deficiencia": 0, "sem_deficiencia": 0, "nao_informado": 0}
    disabilities_breakdown = {
        "surdo": 0,
        "deficiente_auditivo": 0,
        "cego": 0,
        "baixa_visao": 0,
        "deficiencia_fisica_membro_inferior": 0,
        "deficiencia_fisica_membro_superior": 0,
        "transtorno_neurologico": 0,
        "deficiencia_intelectual": 0,
        "outros": 0
    }
    other_descriptions = []

    for r in responded_list:
        if r.has_disabilities is True:
            disabilities_general["com_deficiencia"] += 1
            if r.disabilities and isinstance(r.disabilities, list):
                for dis in r.disabilities:
                    if dis in disabilities_breakdown:
                        disabilities_breakdown[dis] += 1
            if r.other_disability:
                other_descriptions.append(r.other_disability)
        elif r.has_disabilities is False:
            disabilities_general["sem_deficiencia"] += 1
        else:
            disabilities_general["nao_informado"] += 1

    local_obj = db.query(LocalUmp).filter(LocalUmp.id == resolved_local_id).first()

    return {
        "fiscal_year": target_year,
        "local_ump_id": str(resolved_local_id),
        "local_ump_name": local_obj.name if local_obj else "UMP Local",
        "total_registered": total_registered,
        "total_responded": total_responded,
        "response_rate_percent": round((total_responded / total_registered) * 100, 1) if total_registered > 0 else 0,
        "age_metrics": {
            "groups": age_groups,
            "average_age": average_age
        },
        "gender_metrics": gender_counts,
        "education_metrics": education_counts,
        "marital_status_metrics": marital_counts,
        "children_metrics": children_counts,
        "disabilities_metrics": {
            "general": disabilities_general,
            "breakdown": disabilities_breakdown,
            "other_descriptions": other_descriptions
        }
    }


@router.post("/collector/manual-response")
def submit_manual_response(
    payload: ManualAnswerPayload,
    current_user: User = Depends(require_local_or_federation),
    db: Session = Depends(get_db)
):
    """Permite à diretoria cadastrar ou atualizar manualmente a resposta de um sócio."""
    response = db.query(UmpStatisticResponse).filter(
        UmpStatisticResponse.id == payload.response_id
    ).first()

    if not response:
        raise HTTPException(status_code=404, detail="Registro do sócio não encontrado no coletor")

    # Verifica permissão da organização
    collector = response.collector
    if current_user.organization_type == OrgType.local_ump and collector.local_ump_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Acesso não autorizado a este coletor")

    response.birth_date = payload.birth_date
    response.gender = payload.gender
    response.education_level = payload.education_level
    response.marital_status = payload.marital_status
    response.has_children = payload.has_children
    response.has_disabilities = payload.has_disabilities
    response.disabilities = payload.disabilities or []
    response.other_disability = payload.other_disability if payload.has_disabilities else None
    response.has_responded = True
    response.responded_at = datetime.datetime.now(datetime.timezone.utc)

    db.commit()
    db.refresh(response)
    return {"message": "Respostas registradas com sucesso."}


# ── ROTAS PÚBLICAS (FORMULÁRIO DO SÓCIO) ──

@router.get("/survey/{token}")
def get_public_survey_info(token: str, db: Session = Depends(get_db)):
    """Rota pública acessada pelo sócio via link para carregar seus dados e o formulário."""
    response = db.query(UmpStatisticResponse).filter(
        UmpStatisticResponse.access_token == token
    ).first()

    if not response:
        raise HTTPException(status_code=404, detail="Link de formulário inválido ou expirado.")

    collector = response.collector
    member = response.member
    local_ump = collector.local_ump

    return {
        "member_name": member.full_name,
        "society_name": local_ump.name if local_ump else "UMP Local",
        "fiscal_year": collector.fiscal_year,
        "title": collector.title,
        "has_responded": response.has_responded,
        "responded_at": response.responded_at.isoformat() if response.responded_at else None,
        "answers": {
            "birth_date": response.birth_date.isoformat() if response.birth_date else (member.birth_date.isoformat() if member.birth_date else None),
            "gender": response.gender,
            "education_level": response.education_level,
            "marital_status": response.marital_status,
            "has_children": response.has_children,
            "has_disabilities": response.has_disabilities,
            "disabilities": response.disabilities or [],
            "other_disability": response.other_disability
        }
    }


@router.post("/survey/{token}")
def submit_public_survey(token: str, payload: SurveyAnswerPayload, db: Session = Depends(get_db)):
    """Recebe e valida as respostas enviadas pelo sócio através do link público."""
    response = db.query(UmpStatisticResponse).filter(
        UmpStatisticResponse.access_token == token
    ).first()

    if not response:
        raise HTTPException(status_code=404, detail="Link de formulário inválido ou expirado.")

    # Validações básicas
    if payload.gender and payload.gender not in VALID_GENDERS:
        raise HTTPException(status_code=400, detail=f"Gênero inválido. Opções: {', '.join(VALID_GENDERS)}")
    
    if payload.education_level and payload.education_level not in VALID_EDUCATION:
        raise HTTPException(status_code=400, detail=f"Escolaridade inválida. Opções: {', '.join(VALID_EDUCATION)}")

    if payload.marital_status and payload.marital_status not in VALID_MARITAL_STATUS:
        raise HTTPException(status_code=400, detail=f"Estado civil inválido. Opções: {', '.join(VALID_MARITAL_STATUS)}")

    # Atualiza as respostas do censo
    response.birth_date = payload.birth_date
    response.gender = payload.gender
    response.education_level = payload.education_level
    response.marital_status = payload.marital_status
    response.has_children = payload.has_children
    response.has_disabilities = payload.has_disabilities
    response.disabilities = payload.disabilities or []
    response.other_disability = payload.other_disability if payload.has_disabilities else None
    response.has_responded = True
    response.responded_at = datetime.datetime.now(datetime.timezone.utc)

    # Se a data de nascimento foi informada e o cadastro do sócio ainda não tinha, atualiza também
    if payload.birth_date and response.member and not response.member.birth_date:
        response.member.birth_date = payload.birth_date

    db.commit()
    db.refresh(response)

    return {
        "success": True,
        "message": "Formulário estatístico enviado com sucesso! Suas respostas foram computadas.",
        "responded_at": response.responded_at.isoformat()
    }
