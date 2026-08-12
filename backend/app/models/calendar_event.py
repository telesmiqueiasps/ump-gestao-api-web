from sqlalchemy import Column, String, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    federation_id = Column(UUID(as_uuid=True), ForeignKey("federations.id"), nullable=False)
    local_ump_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=True)  # Null if it is a federation event
    
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(200), nullable=True)
    
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    federation = relationship("Federation")
    local_ump = relationship("LocalUmp")
    creator = relationship("User")
