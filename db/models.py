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
)
from sqlalchemy.dialects.postgresql import UUID
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
    name = Column(String, nullable=False)
    # type removed (connector_id is used instead in real schema)

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
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=False)
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

    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=False)
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

class Checkpoint(Base):
    __tablename__ = "checkpoints"

    thread_id = Column(String, primary_key=True)
    checkpoint_id = Column(String, primary_key=True)
    parent_id = Column(String, nullable=True)
    checkpoint = Column(JSON, nullable=False)  # Binary serialized state
    metadata_ = Column("metadata", JSON, nullable=True)  # Renamed to avoid reserved word conflict if needed, or mapped

    created_at = Column(DateTime, default=datetime.utcnow)


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


