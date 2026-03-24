from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.db.session import get_db
from app.models.user import User, UserRole
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


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.email == payload.email,
        User.is_active == True
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )

    current_year = datetime.date.today().year
    active_roles = db.query(UserRole).filter(
        UserRole.user_id == user.id,
        UserRole.is_active == True,
        UserRole.fiscal_year == current_year,
    ).all()

    roles_list = [r.role.value for r in active_roles]

    token_data = {
        "sub": str(user.id),
        "organization_id": str(user.organization_id),
        "organization_type": user.organization_type.value,
        "roles": roles_list,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user_id=str(user.id),
        full_name=user.full_name,
        organization_id=str(user.organization_id),
        organization_type=user.organization_type.value,
        roles=roles_list,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    decoded = decode_token(payload.refresh_token)

    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido ou expirado",
        )

    user = db.query(User).filter(
        User.id == decoded["sub"],
        User.is_active == True
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")

    current_year = datetime.date.today().year
    active_roles = db.query(UserRole).filter(
        UserRole.user_id == user.id,
        UserRole.is_active == True,
        UserRole.fiscal_year == current_year,
    ).all()

    roles_list = [r.role.value for r in active_roles]

    token_data = {
        "sub": str(user.id),
        "organization_id": str(user.organization_id),
        "organization_type": user.organization_type.value,
        "roles": roles_list,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user_id=str(user.id),
        full_name=user.full_name,
        organization_id=str(user.organization_id),
        organization_type=user.organization_type.value,
        roles=roles_list,
    )


@router.get("/me")
def me(db: Session = Depends(get_db), current_user: User = Depends(__import__('app.core.dependencies', fromlist=['get_current_user']).get_current_user)):
    current_year = datetime.date.today().year
    active_roles = db.query(UserRole).filter(
        UserRole.user_id == current_user.id,
        UserRole.is_active == True,
        UserRole.fiscal_year == current_year,
    ).all()
    return {
        "id": str(current_user.id),
        "full_name": current_user.full_name,
        "email": current_user.email,
        "organization_id": str(current_user.organization_id),
        "organization_type": current_user.organization_type.value,
        "roles": [r.role.value for r in active_roles],
    }