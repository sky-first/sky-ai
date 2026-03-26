# db/models.py
from __future__ import annotations

from typing import Any, Dict, Optional

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
    Integer,
    Text,
    Float,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import (
    declarative_base,
    relationship,
)
from pgvector.sqlalchemy import Vector

Base = declarative_base()


def generate_uuid():
    return uuid4()


# ========== ENTIDADES DE CONTEXTO ==========

class Space(Base):
    __tablename__ = "spaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    # is_active removed
    # Pode ter mais colunas: owner_id, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    crews = relationship("Crew", back_populates="space", cascade="all, delete-orphan")
    crews = relationship("Crew", back_populates="space", cascade="all, delete-orphan")
    data_connections = relationship("DataConnection", secondary="space_connections", back_populates="space")


class Crew(Base):
    __tablename__ = "crews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space", back_populates="crews")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # No futuro: tabelas de associação user_space, user_crew, etc.


class UserPermission(Base):
    __tablename__ = "user_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id"), nullable=True)
    permission = Column(String, nullable=False)  # "read", "write", "admin"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")
    crew = relationship("Crew")


class Planet(Base):
    __tablename__ = "planets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    required_scopes = Column(JSON, nullable=True)  # List[str] stored as JSON
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    space = relationship("Space")


class SpaceConnection(Base):
    """Bridge table between Spaces and DataConnections"""
    __tablename__ = "space_connections"
    
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), primary_key=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("data_connections.id"), primary_key=True)


# ========== DATA CONNECTIONS ==========

class DataConnection(Base):
    __tablename__ = "data_connections"

    id = Column(UUID(as_uuid=True), primary_key=True)
    id = Column(UUID(as_uuid=True), primary_key=True)
    # space_id removido (agora usa tabela de associação space_connections)

    name = Column(String, nullable=False)
    connector_id = Column(String, nullable=True) # "bigquery", "postgres", etc.

    config = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    # created_by_user_id removed

    space = relationship("Space", secondary="space_connections", back_populates="data_connections")
    # created_by_user removed

    table_metadata = relationship("TableMetadata", back_populates="data_connection", cascade="all, delete-orphan")


# ========== METADADOS DE TABELAS ==========

class TableMetadata(Base):
    __tablename__ = "table_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)

    data_connection_id = Column(UUID(as_uuid=True), ForeignKey("data_connections.id"), nullable=False)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=True)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id"), nullable=True)

    table_name = Column(String, nullable=False)
    column_name = Column(String, nullable=False)
    data_type = Column(String, nullable=True)
    is_nullable = Column(Boolean, default=True)

    description = Column(Text, nullable=True)
    extra = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    data_connection = relationship("DataConnection", back_populates="table_metadata")
    space = relationship("Space")
    crew = relationship("Crew", uselist=False)


# ========== EMBEDDINGS (pgvector) ==========

class EmbeddingRecord(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)

    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=True)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    table_metadata_id = Column(UUID(as_uuid=True), ForeignKey("table_metadata.id"), nullable=True)
    document_id = Column(String, nullable=True)

    # Vetor de embedding (dimensão depende do modelo)
    embedding = Column(Vector(768), nullable=False)  # Ollama nomic-embed-text: 768 dims

    # Texto original embedado (metadado, chunk de doc, query, etc)
    text = Column(Text, nullable=False)

    # ⚠️ IMPORTANTE:
    # - Nome do atributo Python: extra_metadata
    # - Nome da coluna no banco: "metadata"
    extra_metadata = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    table_metadata = relationship("TableMetadata")


# ========== LANGGRAPH CHECKPOINTS ==========

# LangGraph checkpoints are managed by core.agents.checkpoint_manager (native tables)


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    thread_id = Column(String, nullable=False, index=True)
    
    # role: user / assistant
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    
    # Metadata extra (ex: sql gerado, steps, tokens)
    extra = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


# ========== PIPELINE JOBS ==========

class PipelineJob(Base):
    """Stores the state of asynchronous pipeline executions."""
    __tablename__ = "pipeline_jobs"

    id = Column(String, primary_key=True)  # UUID string
    status = Column(String, nullable=False, default="pending")  # pending, running, completed, failed
    
    # Store the full result or error detail
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    logs = Column(JSON, nullable=True, default=list)
    
    # Metadata for filtering/ownership
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("data_connections.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



# ========== SEMANTIC CACHE ==========
class SemanticCacheRecord(Base):
    """
    Stores semantic hits for incoming queries.
    Prevents duplicate pipeline runs on questions that are semantically identical.

    crew_id is nullable:
    - NULL  → personal mode (all crews) or no crew restriction
    - <uuid> → collaborative mode (only return this record when the same crew is active)
    """
    __tablename__ = "semantic_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    connection_id = Column(String, nullable=False, index=True)
    space_id = Column(String, nullable=True, index=True)
    # FIX 2: crew isolation for collaborative mode
    crew_id = Column(String, nullable=True, index=True)

    question = Column(Text, nullable=False)
    # The dimension is typically 768 for nomic or forced OpenAI 768.
    embedding = Column(Vector(768), nullable=False)

    # Full serialized QueryResponse Dict
    response_json = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

# ========== UNIVERSE INTELLIGENCE ==========

class UniverseInsight(Base):
    """
    Armazena insights gerados proativamente pelos agentes do Universe Intelligence.
    Serve para histórico do usuário e para o Agente Juiz evitar duplicidade.
    """
    __tablename__ = "universe_insights"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=True)
    data_connection_id = Column(UUID(as_uuid=True), ForeignKey("data_connections.id"), nullable=True)
    
    # "general" para Universe Intelligence amplo, "mission" para monitoramento específico
    insight_type = Column(String, nullable=False, default="general")
    mission_id = Column(String, nullable=True)   # Referência à missão se for do tipo mission

    # Classificação tripla — alimenta os 3 cards da UI
    # "insight" | "opportunity" | "risk"
    category = Column(String(20), nullable=False, default="insight")

    title = Column(String, nullable=False)
    insight = Column(Text, nullable=False)
    impact_level = Column(String, nullable=False)  # low | medium | high
    suggested_action = Column(Text, nullable=True)
    source_tables = Column(JSON, nullable=True)   # Lista de nomes das tabelas utilizadas

    # Dados estruturados para gráfico no modo "mix"
    # Formato: [{"label": "Jan", "value": 1200}, ...] — null se não houver série
    chart_data = Column(JSON, nullable=True)

    # Hash para busca rápida de duplicatas (ex: hash(title + insight))
    content_hash = Column(String, nullable=True, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space")
    data_connection = relationship("DataConnection")


# ========== CONFIGURAÇÃO GLOBAL DO UNIVERSE ==========

class UniverseGlobalConfig(Base):
    """
    Configuração global do Universe Intelligence.
    Define escopo (Spaces/Crews), cadência, formato de saída e estado ativo.
    No MVP existe uma única configuração ativa para toda a plataforma.
    """
    __tablename__ = "universe_global_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)

    # Escopo — quais Spaces e Crews o agente deve investigar
    # Formato JSON: List[str] de UUIDs
    target_spaces = Column(JSON, nullable=False, default=list)
    target_crews  = Column(JSON, nullable=False, default=list)
    # Regra: se target_crews == [] → considera todos os crews do Space selecionado

    # Cadência — frequência de execução em dias
    # 1=Daily | 3=Every 3 days | 7=Weekly | 14=Bi-weekly
    frequency_days = Column(Integer, nullable=False, default=7)
    last_run_at    = Column(DateTime, nullable=True)

    # Formato de entrega na UI
    # "text"  → texto curto apenas
    # "mix"   → texto curto + chart_data (quando disponível)
    output_format = Column(String(10), nullable=False, default="text")

    # Controle
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ========== SECURITY AUDIT MODELS ==========

class QueryAuditLog(Base):
    """
    Logs every query processed by the AI system for auditing and security analysis.
    """
    __tablename__ = "query_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    
    connection_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    user_id = Column(String(255), index=True)
    space_id = Column(UUID(as_uuid=True), index=True)
    crew_ids = Column(ARRAY(Text))
    thread_id = Column(String(255), index=True)
    
    platform_role = Column(String(50))
    crew_role = Column(String(50))
    
    question = Column(Text, nullable=False)
    sql_generated = Column(Text)
    sql_executed = Column(Text)
    sql_validated = Column(Boolean)
    validation_error = Column(Text)
    
    num_rows = Column(Integer)
    execution_time_ms = Column(Integer)
    has_error = Column(Boolean)
    error_message = Column(Text)
    
    was_rate_limited = Column(Boolean, default=False)
    prompt_injection_detected = Column(Boolean, default=False, index=True)
    prompt_injection_pattern = Column(Text)
    
    progressive_escalation_score = Column(Integer, default=0)
    progressive_escalation_detected = Column(Boolean, default=False, index=True)
    
    detected_language = Column(String(10))
    chosen_tables = Column(ARRAY(Text))
    answer_preview = Column(Text)
    
    # PII Fields
    pii_detected_in_prompt = Column(Boolean, default=False, index=True)
    pii_detected_in_response = Column(Boolean, default=False, index=True)
    pii_types = Column(ARRAY(Text))
    pii_severity = Column(String(10))
    pii_patterns_matched = Column(ARRAY(Text))
    pii_blocked = Column(Boolean, default=False, index=True)


class SecurityAlert(Base):
    """
    Stores security alerts (e.g., PII detection, prompt injection).
    """
    __tablename__ = "security_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    
    user_id = Column(String(255), index=True)
    connection_id = Column(UUID(as_uuid=True))
    alert_type = Column(String(50), index=True)
    severity = Column(String(20), index=True)
    details = Column(JSONB)


class PromptSecurityAudit(Base):
    """
    Detailed audit for prompt security scans.
    """
    __tablename__ = "prompt_security_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    
    connection_id = Column(UUID(as_uuid=True), index=True)
    user_id = Column(String(255), index=True)
    prompt_text_redacted = Column(Text)
    security_status = Column(String(20), index=True)
    blocked_by = Column(String(50))
    risk_score = Column(Float)
    scan_details = Column(JSONB)
