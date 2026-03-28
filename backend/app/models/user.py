from sqlalchemy import Column, String, Boolean, Enum as SAEnum, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.enums import OrgType, BoardRole


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    organization_type = Column(SAEnum(OrgType, name="org_type", values_callable=lambda x: [e.value for e in x]), nullable=False)
    full_name = Column(String(200), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    roles = relationship("UserRole", back_populates="user")


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role = Column(SAEnum(BoardRole, name="board_role", values_callable=lambda x: [e.value for e in x]), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="roles")