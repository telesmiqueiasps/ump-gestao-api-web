from sqlalchemy import Column, String, Boolean, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class Federation(Base):
    __tablename__ = "federations"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(200), nullable=False)
    presbytery_name = Column(String(200))
    logo_url = Column(Text)
    address = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    local_umps = relationship("LocalUmp", back_populates="federation")