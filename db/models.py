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

from config.settings import settings

# Pgvector column dimension — driven by the active embedding model.
# Bedrock Titan v2 = 1024, Cohere v3 = 1024, OpenAI text-embedding-3-*
# can target 1024 via the ``dimensions`` param, Ollama mxbai-embed-large
# = 1024. Keep this in sync with settings.embedding_dim (default 1024).
EMBEDDING_DIM = settings.embedding_dim

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

    # Vetor de embedding — dimensão controlada por settings.embedding_dim
    # (default 1024; matches Bedrock Titan v2 / Cohere v3 / mxbai-large).
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)

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

    Scope axes (all nullable, combined at lookup-time for isolation):
    - space_id / crew_id → Space/Crew collaborative hits (existing rule)
    - user_id            → Personal-mode hits. Populated only for
                           is_personal queries so user A never sees
                           user B's cached answer, even when both
                           are scoped to the same Space/connection.
    """
    __tablename__ = "semantic_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    connection_id = Column(String, nullable=False, index=True)
    space_id = Column(String, nullable=True, index=True)
    crew_id = Column(String, nullable=True, index=True)
    # Personal-mode cache isolation: NULL for Space/Crew rows,
    # populated for is_personal rows so another user's cached answer
    # never surfaces on a Personal query.
    user_id = Column(String, nullable=True, index=True)

    question = Column(Text, nullable=False)
    # Dim controlled by settings.embedding_dim (default 1024).
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)

    # Full serialized QueryResponse Dict
    response_json = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


# ========== KNOWLEDGE LIBRARY (shared schema with sky-poc-backend) ==========

class KnowledgeFile(Base):
    """Mirror of sky-poc-backend's knowledge_files table. Read-only from the AI service."""
    __tablename__ = "knowledge_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    blob_path = Column(Text, nullable=True)
    sha256_hash = Column(String(64), nullable=True)
    scope = Column(String(16), nullable=False, default="personal")
    scope_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    processing_error = Column(Text, nullable=True)
    chunks_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    chunks = relationship("KnowledgeFileChunk", back_populates="file", lazy="select")


class KnowledgeFileChunk(Base):
    """Chunks from knowledge files — embeddings written by the Celery worker."""
    __tablename__ = "knowledge_file_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    file_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_files.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    tokens = Column(Integer, nullable=False, default=0)
    # Dim controlled by settings.embedding_dim (default 1024).
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("KnowledgeFile", back_populates="chunks")

