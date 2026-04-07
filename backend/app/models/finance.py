from sqlalchemy import Column, Date, Text, Numeric, Boolean, ForeignKey, Enum as SAEnum, Integer, UniqueConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.enums import OrgType, TransactionType


class FinancialPeriod(Base):
    __tablename__ = "financial_periods"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    organization_type = Column(SAEnum(OrgType, name="org_type", values_callable=lambda x: [e.value for e in x]), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    initial_balance = Column(Numeric(12, 2), default=0)
    is_closed = Column(Boolean, default=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    report_url = Column(Text, nullable=True)
    receipts_report_url = Column(Text, nullable=True)
    is_locked = Column(Boolean, default=False)
    signature_id = Column(UUID(as_uuid=True), ForeignKey("report_signatures.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "fiscal_year", name="uq_period_org_year"),
    )

    transactions = relationship("FinancialTransaction", back_populates="period")


class FinancialTransaction(Base):
    __tablename__ = "financial_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    period_id = Column(UUID(as_uuid=True), ForeignKey("financial_periods.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    transaction_date = Column(Date, nullable=False)
    transaction_type = Column(SAEnum(TransactionType, name="transaction_type", values_callable=lambda x: [e.value for e in x]), nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    receipt_url = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    period = relationship("FinancialPeriod", back_populates="transactions")
    creator = relationship("User")