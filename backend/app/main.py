import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from app.core.config import get_settings
from app.routers import auth, federations, local_umps, users, finances, members, board, member_fees, notices, signatures, meetings, activity_reports, uph_statistics, admin, member_portal, push_notifications, elections, calendar
from app.db.session import engine, Base
import app.models # Ensure all models are loaded

# Create missing database tables automatically on start
try:
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS cep VARCHAR(9);"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS logradouro VARCHAR(150);"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS numero VARCHAR(20);"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS bairro VARCHAR(100);"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS cidade VARCHAR(100);"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS estado VARCHAR(2);"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS latitude FLOAT;"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS longitude FLOAT;"))
        conn.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);"))

        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS cep VARCHAR(9);"))
        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS logradouro VARCHAR(150);"))
        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS numero VARCHAR(20);"))
        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS bairro VARCHAR(100);"))
        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS cidade VARCHAR(100);"))
        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS estado VARCHAR(2);"))
        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS latitude FLOAT;"))
        conn.execute(text("ALTER TABLE local_umps ADD COLUMN IF NOT EXISTS longitude FLOAT;"))
except Exception as e:
    import logging
    logging.getLogger("uvicorn").error(f"Error creating database tables or migrating columns: {e}")

settings = get_settings()

app = FastAPI(
    title="Plataforma de Gestão UMP",
    description="API para gestão da União de Mocidade Presbiteriana v2",
    version="1.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
)

from fastapi import Request
from fastapi.responses import JSONResponse

app.add_middleware(GZipMiddleware, minimum_size=1000)
ALLOWED_ORIGINS = [
    "https://umpgestao.netlify.app",
    "https://ump-socio.netlify.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5500",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Type", "Content-Length"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger("uvicorn.error").exception(f"Unhandled error: {exc}")
    origin = request.headers.get("origin")
    response_headers = {}
    if origin and origin in ALLOWED_ORIGINS:
        response_headers["Access-Control-Allow-Origin"] = origin
        response_headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erro interno no servidor: {str(exc)}"},
        headers=response_headers,
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
app.include_router(signatures.router,   prefix="/api/signatures",  tags=["Assinaturas"])
app.include_router(meetings.router,          prefix="/api/meetings",         tags=["Reuniões"])
app.include_router(activity_reports.router,  prefix="/api/activity-reports",  tags=["Relatório de Atividades"])
app.include_router(uph_statistics.router,    prefix="/api/uph-statistics",    tags=["Estatística UPH"])
app.include_router(admin.router,             prefix="/api/admin",             tags=["Admin"])
app.include_router(member_portal.router,      prefix="/api/member-portal",      tags=["Portal do Socio"])
app.include_router(push_notifications.router, prefix="/api/push",          tags=["Push Notifications"])
app.include_router(elections.router,          prefix="/api/elections",     tags=["Eleições"])
app.include_router(calendar.router,           prefix="/api/calendar",      tags=["Calendário"])



@app.get("/health")
def health_check():
    return {"status": "ok", "env": settings.app_env}