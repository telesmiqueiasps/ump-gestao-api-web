from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class UserOrganization(Base):
    __tablename__ = "user_organizations"

    id                = Column(UUID(as_uuid=True), primary_key=True,
                               server_default=text("gen_random_uuid()"))
    user_id           = Column(UUID(as_uuid=True),
                               ForeignKey("users.id", ondelete="CASCADE"),
                               nullable=False)
    organization_id   = Column(UUID(as_uuid=True), nullable=False)
    organization_type = Column(String(20), nullable=False)
    role              = Column(String(50), nullable=False)
    fiscal_year       = Column(Integer, nullable=False)
    is_active         = Column(Boolean, default=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])
