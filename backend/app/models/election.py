import enum
from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base

class ElectionSession(Base):
    __tablename__ = "election_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    local_ump_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=False)
    title = Column(String(200), nullable=False)
    status = Column(String(50), nullable=False, default="config")  # 'config', 'voting', 'completed'
    current_role = Column(String(50), nullable=True)  # e.g., 'presidente', 'vice_presidente'
    current_round = Column(Integer, nullable=False, default=1)
    roles_to_dispute = Column(JSON, nullable=False)  # e.g., ['presidente', 'vice_presidente']
    elected_positions = Column(JSON, nullable=False, default=dict)  # e.g., {"presidente": "member_id"}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    local_ump = relationship("LocalUmp")
    voters = relationship("ElectionVoter", back_populates="election_session", cascade="all, delete-orphan")
    votes = relationship("ElectionVote", back_populates="election_session", cascade="all, delete-orphan")


class ElectionVoter(Base):
    __tablename__ = "election_voters"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    election_session_id = Column(UUID(as_uuid=True), ForeignKey("election_sessions.id", ondelete="CASCADE"), nullable=False)
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    access_code = Column(String(50), nullable=False)
    can_be_voted = Column(Boolean, nullable=False, default=True)
    has_voted_current_round = Column(Boolean, nullable=False, default=False)

    election_session = relationship("ElectionSession", back_populates="voters")
    member = relationship("Member")


class ElectionVote(Base):
    __tablename__ = "election_votes"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    election_session_id = Column(UUID(as_uuid=True), ForeignKey("election_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False)
    round = Column(Integer, nullable=False)
    candidate_member_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=True)

    election_session = relationship("ElectionSession", back_populates="votes")
    candidate = relationship("Member")
