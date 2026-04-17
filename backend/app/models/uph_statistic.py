from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.db.session import Base


class UphStatistic(Base):
    __tablename__ = "uph_statistics"

    id                = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id   = Column(UUID(as_uuid=True), nullable=False)
    organization_type = Column(String(20), nullable=False)
    fiscal_year       = Column(Integer, nullable=False)
    item1_current     = Column(Integer, default=0)
    item1_previous    = Column(Integer, default=0)
    item2_current     = Column(Integer, default=0)
    item2_previous    = Column(Integer, default=0)
    item3_current     = Column(Integer, default=0)
    item3_previous    = Column(Integer, default=0)
    item4_current     = Column(Integer, default=0)
    item4_previous    = Column(Integer, default=0)
    item5_current     = Column(Integer, default=0)
    item5_previous    = Column(Integer, default=0)
    item6_current     = Column(Integer, default=0)
    item6_previous    = Column(Integer, default=0)
    item7_current     = Column(Integer, default=0)
    item7_previous    = Column(Integer, default=0)
    created_by        = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at        = Column(func.now().__class__, server_default=func.now())
    updated_at        = Column(func.now().__class__, server_default=func.now(), onupdate=func.now())
