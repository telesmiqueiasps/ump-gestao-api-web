from sqlalchemy import Column, String, Text, Integer, ForeignKey, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class ActivityReport(Base):
    __tablename__ = "activity_reports"

    id                          = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id             = Column(UUID(as_uuid=True), nullable=False)
    fiscal_year                 = Column(Integer, nullable=False)
    status                      = Column(String(20), nullable=False, default='draft')
    section_intro               = Column(Text, nullable=True)
    section_raio_x_strong       = Column(Text, nullable=True)
    section_raio_x_weak         = Column(Text, nullable=True)
    section_raio_x_achieved     = Column(Text, nullable=True)
    section_raio_x_not_achieved = Column(Text, nullable=True)
    section_final_word          = Column(Text, nullable=True)
    report_url                  = Column(Text, nullable=True)
    created_by                  = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at                  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at                  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])


class Activity(Base):
    __tablename__ = "activities"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    fiscal_year     = Column(Integer, nullable=False)
    title           = Column(String(200), nullable=False)
    description     = Column(Text, nullable=True)
    start_date      = Column(Date, nullable=False)
    end_date        = Column(Date, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    photos = relationship("ActivityPhoto", back_populates="activity",
                          cascade="all, delete-orphan",
                          order_by="ActivityPhoto.display_order")


class ActivityPhoto(Base):
    __tablename__ = "activity_photos"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    activity_id     = Column(UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    photo_url       = Column(Text, nullable=False)
    photo_key       = Column(Text, nullable=False)
    display_order   = Column(Integer, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    activity = relationship("Activity", back_populates="photos")
