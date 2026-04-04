from sqlalchemy import Column, Date, Numeric, Boolean, ForeignKey, Text, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class MemberMonthlyFee(Base):
    __tablename__ = "member_monthly_fees"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    local_ump_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=False)
    reference_month = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    paid_at = Column(Date, nullable=True)
    is_paid = Column(Boolean, default=False)
    receipt_url = Column(Text, nullable=True)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("financial_transactions.id"), nullable=True)
    created_at = Column(Date, server_default=func.current_date())

    __table_args__ = (
        UniqueConstraint("member_id", "reference_month", name="uq_member_month"),
    )

    member = relationship("Member")
    transaction = relationship("FinancialTransaction", foreign_keys=[transaction_id])


class MemberAciContribution(Base):
    __tablename__ = "member_aci_contributions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    local_ump_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    payment_date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    receipt_url = Column(Text, nullable=True)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("financial_transactions.id"), nullable=True)
    created_at = Column(Date, server_default=func.current_date())

    member = relationship("Member")
    transaction = relationship("FinancialTransaction", foreign_keys=[transaction_id])
