from sqlalchemy import Column, String, Boolean, Text, Integer, Numeric, ForeignKey, DateTime, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class LocalUmp(Base):
    __tablename__ = "local_umps"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    federation_id = Column(UUID(as_uuid=True), ForeignKey("federations.id"), nullable=False)
    name = Column(String(200), nullable=False)
    church_name = Column(String(200))
    pastor_name = Column(String(200))
    presbytery_name = Column(String(200))
    address = Column(Text)
    logo_url = Column(Text)
    theme_color = Column(String(7), nullable=True, default='#1a2a6c')
    society_type = Column(String(10), nullable=True, default='UMP')
    pastor_contact = Column(String(100), nullable=True)
    organization_date = Column(Date, nullable=True)
    fiscal_year = Column(Integer)
    initial_balance = Column(Numeric(12, 2), default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    federation = relationship("Federation", back_populates="local_umps")
    members = relationship("Member", back_populates="local_ump")