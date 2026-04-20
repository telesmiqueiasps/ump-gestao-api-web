from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Security
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID
import datetime, json

from app.db.session import get_db
from app.models.member import Member
from app.models.local_ump import LocalUmp
from app.core.config import get_settings
from app.core.security import decode_token

router = APIRouter()

from sqlalchemy import Column, String, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func, text
from app.db.session import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id           = Column(PGUUID(as_uuid=True), primary_key=True,
                          server_default=text("gen_random_uuid()"))
    member_id    = Column(PGUUID(as_uuid=True),
                          ForeignKey("members.id", ondelete="CASCADE"),
                          nullable=False)
    local_ump_id = Column(PGUUID(as_uuid=True), nullable=False)
    endpoint     = Column(Text, nullable=False)
    p256dh       = Column(Text, nullable=False)
    auth         = Column(Text, nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now())


bearer_scheme = HTTPBearer()


def _get_portal_member(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: Session = Depends(get_db),
):
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    member_id = payload.get("sub")
    org_id    = payload.get("org_id")

    if not member_id or not org_id:
        raise HTTPException(status_code=401, detail="Token inválido para o portal")

    member = db.query(Member).filter(Member.id == member_id).first()
    if not member or not member.is_active:
        raise HTTPException(status_code=401, detail="Sócio inativo")
    return member


class SubscriptionPayload(BaseModel):
    endpoint: str
    p256dh:   str
    auth:     str


@router.post("/subscribe")
def subscribe_push(
    payload: SubscriptionPayload,
    member: Member = Depends(_get_portal_member),
    db: Session = Depends(get_db),
):
    existing = db.query(PushSubscription).filter(
        PushSubscription.member_id == member.id,
        PushSubscription.endpoint  == payload.endpoint,
    ).first()

    if existing:
        existing.p256dh     = payload.p256dh
        existing.auth       = payload.auth
        existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
    else:
        sub = PushSubscription(
            member_id    = member.id,
            local_ump_id = member.local_ump_id,
            endpoint     = payload.endpoint,
            p256dh       = payload.p256dh,
            auth         = payload.auth,
        )
        db.add(sub)

    db.commit()
    return {"detail": "Inscrição salva"}


@router.delete("/unsubscribe")
def unsubscribe_push(
    member: Member = Depends(_get_portal_member),
    db: Session = Depends(get_db),
):
    db.query(PushSubscription).filter(
        PushSubscription.member_id == member.id
    ).delete()
    db.commit()
    return {"detail": "Inscrições removidas"}


@router.post("/test-push")
def test_push(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    member: Member = Depends(_get_portal_member),
):
    """Envia notificação de teste para o sócio logado"""
    subs = db.query(PushSubscription).filter(
        PushSubscription.member_id == member.id
    ).all()

    if not subs:
        raise HTTPException(
            status_code=404,
            detail="Nenhuma subscription encontrada. "
                   "Certifique-se de ter dado permissão de notificação no portal."
        )

    message = {
        "title": "Teste de Notificação",
        "body":  "Se você está vendo isso, as notificações estão funcionando!",
        "url":   "/socio.html",
    }

    for sub in subs:
        background_tasks.add_task(
            send_push_to_subscription,
            {"endpoint": sub.endpoint,
             "p256dh":   sub.p256dh,
             "auth":     sub.auth},
            message,
        )

    return {"detail": f"Notificação de teste enfileirada para {len(subs)} dispositivo(s)"}


@router.get("/vapid-public-key")
def get_vapid_public_key():
    settings = get_settings()
    return {"public_key": settings.vapid_public_key}


def send_push_to_subscription(sub_data: dict, message: dict):
    try:
        from pywebpush import webpush, WebPushException
        settings = get_settings()

        private_key = settings.vapid_private_key.strip()
        private_key = private_key.replace('-----BEGIN EC PRIVATE KEY-----', '')
        private_key = private_key.replace('-----END EC PRIVATE KEY-----', '')
        private_key = private_key.replace('\n', '').replace('\r', '').replace(' ', '').strip()

        webpush(
            subscription_info={
                "endpoint": sub_data["endpoint"],
                "keys": {
                    "p256dh": sub_data["p256dh"],
                    "auth":   sub_data["auth"],
                },
            },
            data=json.dumps(message),
            vapid_private_key=private_key,
            vapid_claims={
                "sub": f"mailto:{settings.vapid_email}",
            },
        )
        return True
    except Exception as e:
        err_str = str(e)
        print(f"Push error: {err_str}")

        if '410' in err_str or '404' in err_str or 'Gone' in err_str:
            try:
                from app.db.session import SessionLocal
                db = SessionLocal()
                db.query(PushSubscription).filter(
                    PushSubscription.endpoint == sub_data["endpoint"]
                ).delete()
                db.commit()
                db.close()
                print(f"Subscription expirada removida: {sub_data['endpoint'][:50]}...")
            except Exception as db_err:
                print(f"Erro ao remover subscription: {db_err}")

        return False


@router.post("/send-reminders")
def send_reminders(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    import datetime as dt

    now_utc    = dt.datetime.now(dt.timezone.utc)
    now_br     = now_utc - dt.timedelta(hours=3)
    today_day  = now_br.day
    now_hour   = now_br.hour
    now_minute = now_br.minute

    print(f"[CRON] Executando: UTC={now_utc.strftime('%H:%M')} "
          f"BR={now_br.strftime('%d/%m %H:%M')} "
          f"dia={today_day} hora={now_hour} min={now_minute}")

    locals_ = db.query(LocalUmp).filter(
        LocalUmp.is_active == True,
        LocalUmp.member_portal_enabled == True,
    ).all()

    print(f"[CRON] {len(locals_)} local(is) ativa(s) com portal habilitado")

    sent = 0
    for local in locals_:
        reminder_day    = getattr(local, 'reminder_day', 5) or 5
        reminder_hour   = getattr(local, 'reminder_hour', 9) or 9
        reminder_minute = getattr(local, 'reminder_minute', 0) or 0

        print(f"[CRON] Local '{local.name}': "
              f"dia={reminder_day} hora={reminder_hour} min={reminder_minute} | "
              f"hoje={today_day} agora={now_hour}:{now_minute:02d} | "
              f"bate_dia={reminder_day==today_day} "
              f"bate_hora={reminder_hour==now_hour} "
              f"bate_min={reminder_minute==now_minute}")

        if reminder_day != today_day:
            continue
        if reminder_hour != now_hour:
            continue
        if reminder_minute != now_minute:
            continue

        print(f"[CRON] ✅ Horário bate para '{local.name}' — buscando sócios...")

        subs = db.query(PushSubscription).filter(
            PushSubscription.local_ump_id == local.id,
        ).all()

        print(f"[CRON] {len(subs)} subscription(s) encontrada(s)")

        if not subs:
            print(f"[CRON] Sem subscriptions, pulando.")
            continue

        month_name = [
            'Janeiro','Fevereiro','Março','Abril','Maio','Junho',
            'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'
        ][now_br.month - 1]

        for sub in subs:
            member = db.query(Member).filter(
                Member.id == sub.member_id
            ).first()

            first_name = ''
            if member and member.full_name:
                first_name = member.full_name.split()[0]

            message = {
                "title": "💰 Mensalidade — " + local.name,
                "body": (
                    f"Olá{', ' + first_name if first_name else ''}! "
                    f"Lembrete de contribuição referente a "
                    f"{month_name} de {now_br.year}. "
                    f"Toque para acessar o portal."
                ),
                "url":   f"https://umpgestao.netlify.app/socio.html?org={local.id}",
                "icon":  "/assets/img/logo.png",
                "badge": "/assets/img/logo.png",
            }
            background_tasks.add_task(
                send_push_to_subscription,
                {"endpoint": sub.endpoint,
                 "p256dh":   sub.p256dh,
                 "auth":     sub.auth},
                message,
            )
            sent += 1
            print(f"[CRON] 📤 Notificação enfileirada para membro {sub.member_id}")

    print(f"[CRON] Total enfileirado: {sent}")
    return {
        "detail": f"{sent} notificações enfileiradas",
        "debug": {
            "now_br": now_br.strftime('%d/%m/%Y %H:%M'),
            "day":    today_day,
            "hour":   now_hour,
            "minute": now_minute,
        },
    }


@router.get("/send-reminders")
def send_reminders_get(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Versão GET para testes manuais — mesma lógica do POST"""
    return send_reminders(background_tasks, db)


@router.get("/debug-time")
def debug_time():
    import datetime as dt
    now_utc = dt.datetime.now(dt.timezone.utc)
    now_br  = now_utc - dt.timedelta(hours=3)
    return {
        "utc":    now_utc.strftime('%d/%m/%Y %H:%M:%S'),
        "br":     now_br.strftime('%d/%m/%Y %H:%M:%S'),
        "day":    now_br.day,
        "hour":   now_br.hour,
        "minute": now_br.minute,
    }