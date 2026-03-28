from sqlalchemy import Column, String, Boolean, Date, Enum as SAEnum, ForeignKey, Numeric, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.enums import MemberType


class Member(Base):
    __tablename__ = "members"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    local_ump_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=False)
    full_name = Column(String(200), nullable=False)
    member_type = Column(SAEnum(MemberType, name="member_type"), nullable=False, default=MemberType.ativo)
    email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    birth_date = Column(Date, nullable=True)
    join_date = Column(Date, server_default=func.current_date())
    is_active = Column(Boolean, default=True)

    local_ump = relationship("LocalUmp", back_populates="members")
    fees = relationship("MembershipFee", back_populates="member")


class MembershipFee(Base):
    __tablename__ = "membership_fees"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    local_ump_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=False)
    reference_month = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    paid_at = Column(DateTime(timezone=True), server_default=func.now())
    receipt_url = Column(Text, nullable=True)

    member = relationship("Member", back_populates="fees")