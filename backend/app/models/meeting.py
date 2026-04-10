from sqlalchemy import Column, String, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id                   = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id      = Column(UUID(as_uuid=True), nullable=False)
    organization_type    = Column(String(20), nullable=False)
    record_number        = Column(String(20), nullable=False)
    meeting_type         = Column(String(50), nullable=False)
    title                = Column(String(200), nullable=True)
    started_at           = Column(DateTime(timezone=True), nullable=False)
    ended_at             = Column(DateTime(timezone=True), nullable=True)
    location_name        = Column(String(200), nullable=True)
    city                 = Column(String(100), nullable=True)
    state                = Column(String(2), default='PB')
    address              = Column(Text, nullable=True)
    meeting_president      = Column(String(200), nullable=True)
    meeting_president_role = Column(String(100), nullable=True)
    meeting_secretary      = Column(String(200), nullable=True)
    meeting_secretary_role = Column(String(100), nullable=True)
    status               = Column(String(20), nullable=False, default='draft')
    section_devotional   = Column(Text, nullable=True)
    section_agenda       = Column(Text, nullable=True)
    section_resolutions  = Column(Text, nullable=True)
    section_observations = Column(Text, nullable=True)
    section_closing      = Column(Text, nullable=True)
    created_by           = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    attendees = relationship("MeetingAttendee", back_populates="meeting",
                             cascade="all, delete-orphan")
    creator   = relationship("User", foreign_keys=[created_by])


class MeetingAttendee(Base):
    __tablename__ = "meeting_attendees"

    id            = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id    = Column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    attendee_type = Column(String(30), nullable=False)
    name          = Column(String(200), nullable=False)
    local_name    = Column(String(200), nullable=True)
    observation   = Column(String(300), nullable=True)
    is_present    = Column(Boolean, default=True)
    source_id     = Column(UUID(as_uuid=True), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    meeting = relationship("Meeting", back_populates="attendees")
