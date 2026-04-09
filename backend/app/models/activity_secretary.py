from sqlalchemy import Column, String, Boolean, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.db.session import Base


class ActivitySecretary(Base):
    __tablename__ = "activity_secretaries"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    organization_id   = Column(UUID(as_uuid=True), nullable=False)
    organization_type = Column(String(20), nullable=False)
    member_name       = Column(String(200), nullable=False)
    activity_name     = Column(String(200), nullable=False)
    contact           = Column(String(20), nullable=True)
    fiscal_year       = Column(Integer, nullable=False)
    is_active         = Column(Boolean, default=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
