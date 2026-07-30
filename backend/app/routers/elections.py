from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
import secrets
import io
import os

from app.db.session import get_db
from app.models.user import User
from app.models.member import Member
from app.models.local_ump import LocalUmp
from app.models.enums import MemberType
from app.models.election import ElectionSession, ElectionVoter, ElectionVote
from app.core.dependencies import require_local_ump
from app.services.pdf_generator import generate_election_report

router = APIRouter()

class ElectionCreatePayload(BaseModel):
    title: str
    roles_to_dispute: List[str]
    ineligible_member_ids: List[UUID]

class PublicVotePayload(BaseModel):
    code: str
    candidate_member_id: Optional[UUID] = None

# Helper to generate alphanumeric voter access codes
def generate_voter_codes(db: Session, count: int) -> List[str]:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Exclude: 0, O, 1, I
    codes = set()
    # Fetch existing codes to avoid collisions
    existing = db.query(ElectionVoter.access_code).all()
    existing_codes = {c[0] for c in existing}
    
    while len(codes) < count:
        code = "".join(secrets.choice(chars) for _ in range(6))
        if code not in existing_codes and code not in codes:
            codes.add(code)
    return list(codes)

# Helper to compute list of eligible candidates
def get_eligible_candidates(db: Session, session: ElectionSession) -> List[Member]:
    # 1. Get member IDs of already elected positions
    elected_member_ids = list(session.elected_positions.values()) if session.elected_positions else []
    
    # 2. Get member IDs of ineligible voters
    ineligible_voters = db.query(ElectionVoter.member_id).filter(
        ElectionVoter.election_session_id == session.id,
        ElectionVoter.can_be_voted == False
    ).all()
    ineligible_member_ids = [v[0] for v in ineligible_voters]
    
    exclude_ids = set(elected_member_ids + ineligible_member_ids)
    
    # If 3rd round, restrict to the top 2 candidates from the 2nd round
    if session.current_round == 3:
        votes_r2 = db.query(
            ElectionVote.candidate_member_id,
            func.count(ElectionVote.id).label('vote_count')
        ).filter(
            ElectionVote.election_session_id == session.id,
            ElectionVote.role == session.current_role,
            ElectionVote.round == 2,
            ElectionVote.candidate_member_id.isnot(None)
        ).group_by(ElectionVote.candidate_member_id).order_by(text('vote_count DESC')).all()
        
        # Filter out excluded candidates and take top 2
        top_candidates = [v[0] for v in votes_r2 if v[0] not in exclude_ids][:2]
        
        if len(top_candidates) >= 2:
            candidates = db.query(Member).filter(
                Member.id.in_(top_candidates),
                Member.is_active == True
            ).all()
            # Maintain the order of top_candidates
            candidates_dict = {c.id: c for c in candidates}
            return [candidates_dict[cid] for cid in top_candidates if cid in candidates_dict]
            
    # Default: active members who are marked as eligible and not excluded
    query = db.query(Member).join(
        ElectionVoter, Member.id == ElectionVoter.member_id
    ).filter(
        ElectionVoter.election_session_id == session.id,
        ElectionVoter.can_be_voted == True,
        Member.is_active == True,
        Member.member_type == MemberType.ativo
    )
    if exclude_ids:
        query = query.filter(Member.id.not_in(list(exclude_ids)))
        
    return query.order_by(Member.full_name).all()

# Create Election Session
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_election(
    payload: ElectionCreatePayload,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    # Validate roles
    valid_roles = {'presidente', 'vice_presidente', '1_secretario', '2_secretario', 'secretario_executivo', 'tesoureiro'}
    for r in payload.roles_to_dispute:
        if r not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Cargo inválido: {r}")
            
    if not payload.roles_to_dispute:
        raise HTTPException(status_code=400, detail="Selecione pelo menos um cargo para disputa.")

    # Check for active session
    active_session = db.query(ElectionSession).filter(
        ElectionSession.local_ump_id == current_user.organization_id,
        ElectionSession.status != 'completed'
    ).first()
    if active_session:
        raise HTTPException(status_code=400, detail="Já existe uma sessão eleitoral ativa.")

    # Get active members
    active_members = db.query(Member).filter(
        Member.local_ump_id == current_user.organization_id,
        Member.member_type == MemberType.ativo,
        Member.is_active == True
    ).all()
    if not active_members:
        raise HTTPException(status_code=400, detail="Não há sócios ativos cadastrados para participar da eleição.")

    # Create session
    session = ElectionSession(
        local_ump_id=current_user.organization_id,
        title=payload.title,
        status="config",
        current_role=payload.roles_to_dispute[0],
        current_round=1,
        roles_to_dispute=payload.roles_to_dispute,
        elected_positions={}
    )
    db.add(session)
    db.flush()

    # Generate codes
    codes = generate_voter_codes(db, len(active_members))
    
    # Save voters
    for idx, member in enumerate(active_members):
        can_be_voted = member.id not in payload.ineligible_member_ids
        voter = ElectionVoter(
            election_session_id=session.id,
            member_id=member.id,
            access_code=codes[idx],
            can_be_voted=can_be_voted,
            has_voted_current_round=False
        )
        db.add(voter)

    db.commit()
    return {"id": str(session.id), "title": session.title}

# Get Active Election Session
@router.get("/active")
def get_active_election(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.local_ump_id == current_user.organization_id,
        ElectionSession.status != 'completed'
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Nenhuma eleição ativa encontrada.")
        
    return {
        "id": str(session.id),
        "title": session.title,
        "status": session.status,
        "current_role": session.current_role,
        "current_round": session.current_round,
        "roles_to_dispute": session.roles_to_dispute,
        "elected_positions": session.elected_positions,
    }

# Start Voting
@router.post("/active/start")
def start_voting(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.local_ump_id == current_user.organization_id,
        ElectionSession.status == 'config'
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Nenhuma eleição em configuração encontrada.")

    session.status = "voting"
    db.commit()
    return {"status": session.status}

# Get Voting Status
@router.get("/active/status")
def get_voting_status(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.local_ump_id == current_user.organization_id,
        ElectionSession.status != 'completed'
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Nenhuma eleição ativa encontrada.")

    # Get voters
    voters = db.query(ElectionVoter).filter(
        ElectionVoter.election_session_id == session.id
    ).all()

    # Get current votes count
    votes_count = db.query(ElectionVote).filter(
        ElectionVote.election_session_id == session.id,
        ElectionVote.role == session.current_role,
        ElectionVote.round == session.current_round
    ).count()

    voters_list = [
        {
            "id": str(v.id),
            "member_id": str(v.member_id),
            "full_name": v.member.full_name,
            "access_code": v.access_code,
            "can_be_voted": v.can_be_voted,
            "has_voted": v.has_voted_current_round,
        }
        for v in voters
    ]
    
    # Sort voters list alphabetically by name
    voters_list.sort(key=lambda x: x["full_name"])

    return {
        "session_id": str(session.id),
        "title": session.title,
        "status": session.status,
        "current_role": session.current_role,
        "current_round": session.current_round,
        "total_voters": len(voters),
        "votes_cast": votes_count,
        "voters": voters_list,
    }

# Close Round and Calculate Results
@router.post("/active/close-round")
def close_round(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.local_ump_id == current_user.organization_id,
        ElectionSession.status == 'voting'
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Nenhuma eleição em votação encontrada.")

    # Fetch votes
    votes = db.query(ElectionVote).filter(
        ElectionVote.election_session_id == session.id,
        ElectionVote.role == session.current_role,
        ElectionVote.round == session.current_round
    ).all()

    total_votes = len(votes)
    results = {}
    
    # Count votes per candidate
    for v in votes:
        cid = v.candidate_member_id
        results[cid] = results.get(cid, 0) + 1

    # Format results list with member names
    results_list = []
    for cid, count in results.items():
        if cid is None:
            name = "Branco/Nulo"
            cid_str = "blank"
        else:
            m = db.query(Member).filter(Member.id == cid).first()
            name = m.full_name if m else "Desconhecido"
            cid_str = str(cid)
        results_list.append({"candidate_id": cid_str, "name": name, "votes": count})
    
    results_list.sort(key=lambda x: x["votes"], reverse=True)

    # Determine winner
    elected = False
    winner_name = None
    next_step = ""

    if total_votes > 0:
        majority_threshold = total_votes / 2
        # Check if first candidate has majority
        top_candidate = results_list[0]
        
        # Absolute majority required for round 1 and 2
        if session.current_round in (1, 2):
            if top_candidate["candidate_id"] != "blank" and top_candidate["votes"] > majority_threshold:
                elected = True
        else: # Round 3: highest votes wins (no absolute majority required)
            if top_candidate["candidate_id"] != "blank":
                elected = True

        if elected:
            winner_id = top_candidate["candidate_id"]
            winner_name = top_candidate["name"]
            
            # Save elected candidate
            new_elected = {**(session.elected_positions or {})}
            new_elected[session.current_role] = winner_id
            session.elected_positions = new_elected
            
            # Find next role
            roles = session.roles_to_dispute
            current_idx = roles.index(session.current_role)
            if current_idx + 1 < len(roles):
                session.current_role = roles[current_idx + 1]
                session.current_round = 1
                next_step = f"Iniciar votação para {session.current_role.replace('_', ' ').title()}"
            else:
                session.status = "completed"
                session.current_role = None
                session.current_round = 1
                next_step = "Eleição concluída"
        else:
            # Not elected, advance round
            if session.current_round == 1:
                session.current_round = 2
                next_step = "Iniciar 2º Escrutínio (todos os candidatos continuam)"
            elif session.current_round == 2:
                session.current_round = 3
                next_step = "Iniciar 3º Escrutínio (apenas os 2 mais votados)"
            else:
                # Should not normally happen if round 3 resolves, but if all blank or strict tie:
                # Let's say if round 3 has a strict tie, we stay in round 3 and re-vote
                next_step = "Empate no 3º Escrutínio. Uma nova votação da rodada 3 foi configurada."

        # Reset has_voted_current_round for next round/role
        db.query(ElectionVoter).filter(
            ElectionVoter.election_session_id == session.id
        ).update({"has_voted_current_round": False}, synchronize_session=False)

    else:
        # 0 votes cast
        next_step = "Nenhum voto registrado. Repetindo a rodada atual."
        db.query(ElectionVoter).filter(
            ElectionVoter.election_session_id == session.id
        ).update({"has_voted_current_round": False}, synchronize_session=False)

    db.commit()
    
    return {
        "elected": elected,
        "winner_name": winner_name,
        "next_step": next_step,
        "results": results_list,
        "total_votes": total_votes,
    }

# Cancel Active Election Session
@router.post("/active/cancel")
def cancel_election(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.local_ump_id == current_user.organization_id,
        ElectionSession.status != 'completed'
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Nenhuma eleição ativa encontrada.")

    db.delete(session)
    db.commit()
    return {"detail": "Sessão eleitoral cancelada com sucesso."}

# Get Completed Elections History
@router.get("/history")
def get_history(
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    sessions = db.query(ElectionSession).filter(
        ElectionSession.local_ump_id == current_user.organization_id,
        ElectionSession.status == 'completed'
    ).order_by(ElectionSession.created_at.desc()).all()

    result = []
    for s in sessions:
        # Load elected members details
        elected_details = {}
        elected_positions = s.elected_positions or {}
        for role, member_id in elected_positions.items():
            try:
                m = db.query(Member).filter(Member.id == UUID(member_id)).first()
                name = m.full_name if m else "Desconhecido"
            except Exception:
                name = "Desconhecido"
            elected_details[role] = name

        result.append({
            "id": str(s.id),
            "title": s.title,
            "created_at": s.created_at.isoformat(),
            "elected_positions": elected_details,
        })
    return result

# ── Public Voting Endpoints ─────────────────────────────────

# Validate Access Code and Get Current Session Info
@router.get("/public/session")
def get_public_session(
    code: str,
    db: Session = Depends(get_db),
):
    voter = db.query(ElectionVoter).filter(
        func.upper(ElectionVoter.access_code) == code.upper().strip()
    ).first()
    if not voter:
        raise HTTPException(status_code=404, detail="Código de acesso inválido.")

    session = voter.election_session
    if session.status == 'completed':
        raise HTTPException(status_code=400, detail="Esta eleição já foi finalizada.")
    if session.status == 'config':
        raise HTTPException(status_code=400, detail="A votação ainda não foi iniciada pelo administrador.")

    # Get eligible candidates
    candidates = get_eligible_candidates(db, session)

    candidates_list = [
        {"id": str(c.id), "full_name": c.full_name}
        for c in candidates
    ]

    return {
        "session_id": str(session.id),
        "title": session.title,
        "current_role": session.current_role,
        "current_round": session.current_round,
        "has_voted": voter.has_voted_current_round,
        "candidates": candidates_list,
    }

# Cast Anonymous Vote
@router.post("/public/vote")
def cast_public_vote(
    payload: PublicVotePayload,
    db: Session = Depends(get_db),
):
    voter = db.query(ElectionVoter).filter(
        func.upper(ElectionVoter.access_code) == payload.code.upper().strip()
    ).first()
    if not voter:
        raise HTTPException(status_code=404, detail="Código de acesso inválido.")

    session = voter.election_session
    if session.status != 'voting':
        raise HTTPException(status_code=400, detail="A votação não está ativa no momento.")

    if voter.has_voted_current_round:
        raise HTTPException(status_code=400, detail="Você já votou nesta rodada.")

    # Validate candidate selection
    if payload.candidate_member_id:
        eligible_candidates = get_eligible_candidates(db, session)
        eligible_ids = {c.id for c in eligible_candidates}
        if payload.candidate_member_id not in eligible_ids:
            raise HTTPException(status_code=400, detail="O candidato selecionado não é elegível para esta rodada.")

    # Save vote anonymously
    vote = ElectionVote(
        election_session_id=session.id,
        role=session.current_role,
        round=session.current_round,
        candidate_member_id=payload.candidate_member_id
    )
    db.add(vote)
    
    # Mark voter as voted
    voter.has_voted_current_round = True
    db.commit()

    return {"detail": "Voto registrado com sucesso!"}


def _get_session_report_data(db: Session, session: ElectionSession) -> dict:
    ROLE_LABELS = {
        'presidente': 'Presidente',
        'vice_presidente': 'Vice-Presidente',
        '1_secretario': '1º Secretário(a)',
        '2_secretario': '2º Secretário(a)',
        'secretario_executivo': 'Secretário Executivo',
        'tesoureiro': 'Tesoureiro(a)',
    }

    # Fetch all votes for this session
    votes = db.query(ElectionVote).filter(
        ElectionVote.election_session_id == session.id
    ).all()

    # Load elected names
    elected_positions_names = {}
    elected_positions = session.elected_positions or {}
    for role, member_id in elected_positions.items():
        try:
            m = db.query(Member).filter(Member.id == UUID(member_id)).first()
            elected_positions_names[role] = m.full_name if m else "Desconhecido"
        except Exception:
            elected_positions_names[role] = "Desconhecido"

    # Group votes by role and round
    # votes_map = { role: { round: { candidate_id: count } } }
    votes_map = {}
    for v in votes:
        role = v.role
        r = v.round
        cid = v.candidate_member_id # UUID or None (blank)
        
        if role not in votes_map:
            votes_map[role] = {}
        if r not in votes_map[role]:
            votes_map[role][r] = {}
            
        votes_map[role][r][cid] = votes_map[role][r].get(cid, 0) + 1

    roles_disputed = []
    for role in session.roles_to_dispute:
        role_label = ROLE_LABELS.get(role, role.replace('_', ' ').title())
        winner_name = elected_positions_names.get(role)

        rounds_list = []
        role_votes = votes_map.get(role, {})
        for r_num in sorted(role_votes.keys()):
            r_votes = role_votes[r_num]
            total_r_votes = sum(r_votes.values())

            results_list = []
            for cid, count in r_votes.items():
                if cid is None:
                    name = "Branco/Nulo"
                    cid_str = "blank"
                else:
                    m = db.query(Member).filter(Member.id == cid).first()
                    name = m.full_name if m else "Desconhecido"
                    cid_str = str(cid)
                
                pct = (count / total_r_votes * 100) if total_r_votes > 0 else 0
                results_list.append({
                    "candidate_id": cid_str,
                    "name": name,
                    "votes": count,
                    "percentage": pct
                })
            
            results_list.sort(key=lambda x: x["votes"], reverse=True)
            rounds_list.append({
                "round": r_num,
                "total_votes": total_r_votes,
                "results": results_list
            })

        roles_disputed.append({
            "role": role,
            "role_label": role_label,
            "winner_name": winner_name,
            "rounds": rounds_list
        })

    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "status": session.status,
        "elected_positions": elected_positions_names,
        "roles_disputed": roles_disputed
    }


@router.get("/session/{session_id}/details")
def get_election_details(
    session_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.id == session_id,
        ElectionSession.local_ump_id == current_user.organization_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Eleição não encontrada.")
    return _get_session_report_data(db, session)


@router.get("/session/{session_id}/pdf")
def get_election_pdf(
    session_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.id == session_id,
        ElectionSession.local_ump_id == current_user.organization_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Eleição não encontrada.")
    
    election_data = _get_session_report_data(db, session)
    
    local_ump = db.query(LocalUmp).filter(LocalUmp.id == current_user.organization_id).first()
    org_data = {
        "name": local_ump.name if local_ump else "UMP Local",
        "theme_color": local_ump.theme_color if local_ump and local_ump.theme_color else "#1a2a6c"
    }
    
    ipb_logo_bytes = None
    try:
        ipb_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'ipb_logo.png')
        if os.path.exists(ipb_path):
            with open(ipb_path, 'rb') as f:
                ipb_logo_bytes = f.read()
    except Exception:
        pass

    logo_bytes = None
    
    pdf_bytes = generate_election_report(
        election_data=election_data,
        org_data=org_data,
        logo_bytes=logo_bytes,
        ipb_logo_bytes=ipb_logo_bytes,
        theme_color=org_data["theme_color"],
    )
    
    safe_title = session.title.replace('/', '-').replace(' ', '_')
    filename = f"Relatorio_Eleicao_{safe_title}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.delete("/session/{session_id}")
def delete_election(
    session_id: UUID,
    current_user: User = Depends(require_local_ump),
    db: Session = Depends(get_db),
):
    session = db.query(ElectionSession).filter(
        ElectionSession.id == session_id,
        ElectionSession.local_ump_id == current_user.organization_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Eleição não encontrada.")
        
    db.delete(session)
    db.commit()
    return {"detail": "Eleição excluída com sucesso."}
