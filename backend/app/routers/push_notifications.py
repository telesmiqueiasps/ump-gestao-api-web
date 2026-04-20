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

        if 'BEGIN EC PRIVATE KEY' in private_key:
            import re
            content = re.sub(
                r'-----BEGIN EC PRIVATE KEY-----|-----END EC PRIVATE KEY-----|\\n|\s',
                '', private_key
            )
            private_key = (
                '-----BEGIN EC PRIVATE KEY-----\n' +
                '\n'.join(content[i:i+64] for i in range(0, len(content), 64)) +
                '\n-----END EC PRIVATE KEY-----'
            )

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
        print(f"Push error: {e}")
        return False


@router.post("/send-reminders")
def send_reminders(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Chamado pelo cron job — envia lembretes para orgs cujo dia+hora bate agora"""
    import datetime as dt
    from app.models.member_fees import MemberMonthlyFee

    now_utc   = dt.datetime.now(dt.timezone.utc)
    now_br    = now_utc - dt.timedelta(hours=3)
    today_day = now_br.day
    now_hour  = now_br.hour

    locals_ = db.query(LocalUmp).filter(
        LocalUmp.is_active == True,
        LocalUmp.member_portal_enabled == True,
        LocalUmp.reminder_day == today_day,
    ).all()

    sent = 0
    for local in locals_:
        reminder_hour = getattr(local, 'reminder_hour', 9) or 9
        if reminder_hour != now_hour:
            continue

        current_month = dt.date(now_br.year, now_br.month, 1)
        pending_fees = db.query(MemberMonthlyFee).filter(
            MemberMonthlyFee.local_ump_id == local.id,
            MemberMonthlyFee.reference_month == current_month,
            MemberMonthlyFee.is_paid == False,
        ).all()

        member_ids_pending = {str(f.member_id) for f in pending_fees}
        if not member_ids_pending:
            continue

        subs = db.query(PushSubscription).filter(
            PushSubscription.local_ump_id == local.id,
        ).all()

        for sub in subs:
            if str(sub.member_id) not in member_ids_pending:
                continue
            message = {
                "title": f"Lembrete — {local.name}",
                "body":  f"Sua mensalidade de {now_br.strftime('%B/%Y')} "
                          f"está pendente. Acesse o portal para ver detalhes.",
                "url":   f"https://umpgestao.netlify.app/socio.html?org={local.id}",
            }
            background_tasks.add_task(
                send_push_to_subscription,
                {"endpoint": sub.endpoint,
                 "p256dh":   sub.p256dh,
                 "auth":     sub.auth},
                message,
            )
            sent += 1

    return {"detail": f"{sent} notificações enfileiradas"}