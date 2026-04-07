from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class ReportSignature(Base):
    __tablename__ = "report_signatures"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    fiscal_year     = Column(Integer, nullable=False)
    period_id       = Column(UUID(as_uuid=True), ForeignKey("financial_periods.id"), nullable=True)

    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())

    status           = Column(String(20), nullable=False, default='pending')
    reviewed_by      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at      = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    validation_code = Column(String(64), nullable=False, unique=True)
    report_url      = Column(Text, nullable=True)
    data_hash       = Column(Text, nullable=False)
    snapshot_data   = Column(JSONB, nullable=True)

    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    invalidated_at    = Column(DateTime(timezone=True), nullable=True)
    invalidated_reason = Column(Text, nullable=True)

    requester = relationship("User", foreign_keys=[requested_by])
    reviewer  = relationship("User", foreign_keys=[reviewed_by])
    period    = relationship("FinancialPeriod", foreign_keys=[period_id])
