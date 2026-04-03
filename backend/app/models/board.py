from sqlalchemy import Column, String, Boolean, Integer, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.enums import OrgType, BoardRole


class BoardMember(Base):
    __tablename__ = "board_members"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    organization_type = Column(SAEnum(OrgType, name="org_type", values_callable=lambda x: [e.value for e in x]), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    member_name = Column(String(200), nullable=False)
    role = Column(SAEnum(BoardRole, name="board_role", values_callable=lambda x: [e.value for e in x]), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    contact = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)

    user = relationship("User")