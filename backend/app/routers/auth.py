from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from uuid import UUID
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.user_organization import UserOrganization
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token
import datetime

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    full_name: str
    organization_id: str
    organization_type: str
    roles: list[str]


class RefreshRequest(BaseModel):
    refresh_token: str


class OrgSelectPayload(BaseModel):
    user_id: UUID
    organization_id: UUID


# ── Helpers ──────────────────────────────────────────────────────────────────

def _org_type_str(val) -> str:
    return val.value if hasattr(val, 'value') else str(val)


def _get_org_name(db, org_id, org_type: str) -> str:
    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp
    if org_type == 'federation':
        obj = db.query(Federation).filter(Federation.id == org_id).first()
        return obj.name if obj else 'Federação'
    obj = db.query(LocalUmp).filter(LocalUmp.id == org_id).first()
    return obj.name if obj else 'UMP Local'


def _build_token_response(db, user: User, org_id, org_type: str, roles: list[str]):
    """Monta o TokenResponse para um usuário + org específicos."""
    from app.models.federation import Federation
    from app.models.local_ump import LocalUmp

    token_data = {
        "sub": str(user.id),
        "organization_id": str(org_id),
        "organization_type": org_type,
        "roles": roles,
    }

    if org_type == 'federation':
        obj = db.query(Federation).filter(Federation.id == org_id).first()
        society_type = getattr(obj, 'society_type', 'UMP') or 'UMP'
    else:
        obj = db.query(LocalUmp).filter(LocalUmp.id == org_id).first()
        society_type = getattr(obj, 'society_type', 'UMP') or 'UMP'

    return {
        "access_token":    create_access_token(token_data),
        "refresh_token":   create_refresh_token(token_data),
        "token_type":      "bearer",
        "user_id":         str(user.id),
        "full_name":       user.full_name,
        "organization_id": str(org_id),
        "organization_type": org_type,
        "roles":           roles,
        "society_type":    society_type,
    }


# ── POST /login ───────────────────────────────────────────────────────────────

@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sua conta está inativa. Entre em contato com sua federação.",
        )

    year     = datetime.date.today().year
    org_type = _org_type_str(user.organization_type)

    # Roles da org principal
    active_roles_q = db.query(UserRole).filter(
        UserRole.user_id     == user.id,
        UserRole.is_active   == True,
        UserRole.fiscal_year == year,
    ).all()
    roles_list = [r.role.value for r in active_roles_q]
    main_role  = roles_list[0] if roles_list else 'membro'

    # Busca orgs extras
    extra_orgs = db.query(UserOrganization).filter(
        UserOrganization.user_id   == user.id,
        UserOrganization.is_active == True,
    ).all()

    if extra_orgs:
        orgs = [{
            "organization_id":   str(user.organization_id),
            "organization_type": org_type,
            "org_name":          _get_org_name(db, user.organization_id, org_type),
            "role":              main_role,
        }]
        for eo in extra_orgs:
            orgs.append({
                "organization_id":   str(eo.organization_id),
                "organization_type": eo.organization_type,
                "org_name":          _get_org_name(db, eo.organization_id, eo.organization_type),
                "role":              eo.role,
            })
        return {
            "requires_org_selection": True,
            "user_id":     str(user.id),
            "user_name":   user.full_name,
            "organizations": orgs,
        }

    # Fluxo normal — org única
    return _build_token_response(db, user, user.organization_id, org_type, roles_list)


# ── POST /login/select-org ────────────────────────────────────────────────────

@router.post("/login/select-org")
def login_select_org(
    payload: OrgSelectPayload,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuário inválido")

    year     = datetime.date.today().year
    org_id   = payload.organization_id
    org_type = None
    roles    = []

    if str(user.organization_id) == str(org_id):
        # Org principal
        org_type = _org_type_str(user.organization_type)
        active_roles_q = db.query(UserRole).filter(
            UserRole.user_id     == user.id,
            UserRole.fiscal_year == year,
            UserRole.is_active   == True,
        ).all()
        roles = [r.role.value for r in active_roles_q]
    else:
        # Org extra
        uo = db.query(UserOrganization).filter(
            UserOrganization.user_id         == user.id,
            UserOrganization.organization_id == org_id,
            UserOrganization.is_active       == True,
        ).first()
        if not uo:
            raise HTTPException(status_code=403, detail="Sem acesso a esta organização")
        org_type = uo.organization_type
        roles    = [uo.role]

    return _build_token_response(db, user, org_id, org_type, roles)


# ── POST /refresh ─────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    decoded = decode_token(payload.refresh_token)

    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido ou expirado",
        )

    user = db.query(User).filter(
        User.id       == decoded["sub"],
        User.is_active == True
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")

    year = datetime.date.today().year
    active_roles = db.query(UserRole).filter(
        UserRole.user_id     == user.id,
        UserRole.is_active   == True,
        UserRole.fiscal_year == year,
    ).all()
    roles_list = [r.role.value for r in active_roles]

    # Usa a org que estava no token, caso seja uma org extra
    token_org_id   = decoded.get("organization_id", str(user.organization_id))
    token_org_type = decoded.get("organization_type", _org_type_str(user.organization_type))

    token_data = {
        "sub":               str(user.id),
        "organization_id":   token_org_id,
        "organization_type": token_org_type,
        "roles":             roles_list,
    }

    return TokenResponse(
        access_token     = create_access_token(token_data),
        refresh_token    = create_refresh_token(token_data),
        user_id          = str(user.id),
        full_name        = user.full_name,
        organization_id  = token_org_id,
        organization_type= token_org_type,
        roles            = roles_list,
    )


# ── GET /me ───────────────────────────────────────────────────────────────────

@router.get("/me")
def me(db: Session = Depends(get_db),
       current_user: User = Depends(
           __import__('app.core.dependencies', fromlist=['get_current_user']).get_current_user
       )):
    year = datetime.date.today().year
    active_roles = db.query(UserRole).filter(
        UserRole.user_id     == current_user.id,
        UserRole.is_active   == True,
        UserRole.fiscal_year == year,
    ).all()
    return {
        "id":                str(current_user.id),
        "full_name":         current_user.full_name,
        "email":             current_user.email,
        "organization_id":   str(current_user.organization_id),
        "organization_type": current_user.organization_type.value,
        "roles":             [r.role.value for r in active_roles],
    }
