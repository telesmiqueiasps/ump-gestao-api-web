import secrets
from sqlalchemy import Column, String, Boolean, Integer, Date, ForeignKey, DateTime, JSON, UniqueConstraint, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from app.db.session import Base


class UmpStatisticCollector(Base):
    __tablename__ = "ump_statistic_collectors"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    local_ump_id = Column(UUID(as_uuid=True), ForeignKey("local_umps.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    status = Column(String(20), nullable=False, default='draft')
    report_url = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("local_ump_id", "fiscal_year", name="uq_ump_collector_local_year"),
    )

    local_ump = relationship("LocalUmp")
    creator = relationship("User")
    responses = relationship("UmpStatisticResponse", back_populates="collector", cascade="all, delete-orphan")


class UmpStatisticResponse(Base):
    __tablename__ = "ump_statistic_responses"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    collector_id = Column(UUID(as_uuid=True), ForeignKey("ump_statistic_collectors.id", ondelete="CASCADE"), nullable=False)
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    access_token = Column(String(64), nullable=False, unique=True, index=True)
    has_responded = Column(Boolean, nullable=False, default=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    # Questionário específico da UMP
    birth_date = Column(Date, nullable=True)
    gender = Column(String(20), nullable=True)  # 'Masculino', 'Feminino'
    education_level = Column(String(50), nullable=True)  # 'Ensino Fundamental', 'Ensino Médio', 'Técnico', 'Superior', 'Pós-graduação'
    marital_status = Column(String(50), nullable=True)  # 'Solteiro(a)', 'Casado(a)', 'Divorciado(a)', 'Viúvo(a)'
    has_children = Column(Boolean, nullable=True)  # True / False
    has_disabilities = Column(Boolean, nullable=True)  # True / False
    disabilities = Column(JSON, nullable=True)  # Lista de opções selecionadas
    other_disability = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("collector_id", "member_id", name="uq_ump_response_collector_member"),
    )

    collector = relationship("UmpStatisticCollector", back_populates="responses")
    member = relationship("Member")


def generate_unique_token(existing_tokens: set = None) -> str:
    """Gera um token alfanumérico seguro para acesso ao formulário individual."""
    while True:
        token_candidate = secrets.token_urlsafe(16)
        if not existing_tokens or token_candidate not in existing_tokens:
            return token_candidate
