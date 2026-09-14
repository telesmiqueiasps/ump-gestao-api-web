import uuid
import secrets
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, Boolean, DateTime, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.session import Base


class Congress(Base):
    """Representa um Congresso da Federação (Ordinário ou Extraordinário)."""
    __tablename__ = "congresses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    federation_id = Column(UUID(as_uuid=True), ForeignKey("federations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    fiscal_year = Column(Integer, nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="aberto")  # aberto, encerrado
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    commissions = relationship("CongressCommission", back_populates="congress", cascade="all, delete-orphan", order_by="CongressCommission.name")


class CongressCommission(Base):
    """Representa uma Comissão Temática dentro de um Congresso."""
    __tablename__ = "congress_commissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    congress_id = Column(UUID(as_uuid=True), ForeignKey("congresses.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    relator_id = Column(UUID(as_uuid=True), ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    relator_name = Column(String(200), nullable=True)
    
    # Token único de acesso público para relator e membros
    access_token = Column(String(64), unique=True, nullable=False, index=True, default=lambda: secrets.token_urlsafe(24))

    # Parecer/Relatório da comissão redigido com formatação
    opinion_report = Column(Text, nullable=False, default="")
    opinion_updated_at = Column(DateTime, nullable=True)

    # Status e Aprovação Oficial pela Diretoria
    status = Column(String(30), nullable=False, default="em_andamento")  # em_andamento, aprovado
    approval_date = Column(Date, nullable=True)
    final_report_url = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    congress = relationship("Congress", back_populates="commissions")
    members = relationship("CongressCommissionMember", back_populates="commission", cascade="all, delete-orphan", order_by="CongressCommissionMember.delegate_name")
    documents = relationship("CongressCommissionDocument", back_populates="commission", cascade="all, delete-orphan", order_by="CongressCommissionDocument.created_at")


class CongressCommissionMember(Base):
    """Representa um membro (delegado) participante da comissão."""
    __tablename__ = "congress_commission_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commission_id = Column(UUID(as_uuid=True), ForeignKey("congress_commissions.id", ondelete="CASCADE"), nullable=False, index=True)
    delegate_id = Column(UUID(as_uuid=True), ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    delegate_name = Column(String(200), nullable=False)
    is_relator = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    commission = relationship("CongressCommission", back_populates="members")


class CongressCommissionDocument(Base):
    """Representa um documento disponibilizado para a comissão analisar."""
    __tablename__ = "congress_commission_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commission_id = Column(UUID(as_uuid=True), ForeignKey("congress_commissions.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(250), nullable=False)
    category = Column(String(50), nullable=False, default="avulso")  # financeiro, comprovantes, atividades, estatistica, avulso
    origin_name = Column(String(150), nullable=True)  # ex: UMP Patos, Federação
    document_url = Column(Text, nullable=False)
    external_reference_id = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    commission = relationship("CongressCommission", back_populates="documents")
