from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from uuid import UUID
from app.db.session import get_db
from app.core.security import decode_token
from app.models.user import User
from app.models.enums import OrgType, BoardRole

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token malformado")

    user = db.query(User).filter(User.id == UUID(user_id), User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")

    return user


def require_federation(current_user: User = Depends(get_current_user)) -> User:
    if current_user.organization_type != OrgType.federation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a usuários de Federação",
        )
    return current_user


def require_local_ump(current_user: User = Depends(get_current_user)) -> User:
    if current_user.organization_type != OrgType.local_ump:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a usuários de UMP Local",
        )
    return current_user


def require_roles(*roles: BoardRole):
    def checker(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        from app.models.user import UserRole
        import datetime
        active_role = db.query(UserRole).filter(
            UserRole.user_id == current_user.id,
            UserRole.role.in_(roles),
            UserRole.is_active == True,
            UserRole.fiscal_year == datetime.date.today().year,
        ).first()
        if not active_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cargo insuficiente para esta operação",
            )
        return current_user
    return checker