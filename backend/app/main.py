import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from app.core.config import get_settings
from app.routers import auth, federations, local_umps, users, finances, members, board, member_fees, notices

settings = get_settings()

app = FastAPI(
    title="Plataforma de Gestão UMP",
    description="API para gestão da União de Mocidade Presbiteriana v2",
    version="1.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,         prefix="/api/auth",        tags=["Autenticação"])
app.include_router(federations.router,  prefix="/api/federations", tags=["Federações"])
app.include_router(local_umps.router,   prefix="/api/local-umps",  tags=["UMPs Locais"])
app.include_router(users.router,        prefix="/api/users",       tags=["Usuários"])
app.include_router(finances.router,     prefix="/api/finances",    tags=["Financeiro"])
app.include_router(members.router,      prefix="/api/members",     tags=["Sócios"])
app.include_router(board.router,        prefix="/api/board",       tags=["Diretoria"])
app.include_router(member_fees.router,  prefix="/api/member-fees", tags=["Mensalidades e ACI"])
app.include_router(notices.router,      prefix="/api/notices",     tags=["Avisos"])


@app.get("/health")
def health_check():
    return {"status": "ok", "env": settings.app_env}