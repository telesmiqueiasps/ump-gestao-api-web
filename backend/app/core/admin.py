from fastapi import HTTPException, Depends
from app.core.dependencies import get_current_user
from app.core.config import get_settings
from app.models.user import User


def require_admin(current_user: User = Depends(get_current_user)):
    settings = get_settings()
    admin_id = settings.admin_federation_id
    if not admin_id:
        raise HTTPException(status_code=403, detail="Painel admin não configurado")
    if str(current_user.organization_id) != str(admin_id):
        raise HTTPException(status_code=403, detail="Acesso restrito")
    return current_user