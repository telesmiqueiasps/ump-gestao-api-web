from sqlalchemy import Column, String, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class FederationNotice(Base):
    __tablename__ = "federation_notices"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    federation_id   = Column(UUID(as_uuid=True), ForeignKey("federations.id"), nullable=False)
    title           = Column(String(200), nullable=False)
    content         = Column(Text, nullable=False)
    target_type     = Column(String(10), nullable=False, default='all')
    target_local_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=True)
    is_active       = Column(Boolean, default=True)
    created_by      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    expires_at      = Column(DateTime(timezone=True), nullable=True)

    federation   = relationship("Federation")
    target_local = relationship("LocalUmp")
    creator      = relationship("User")