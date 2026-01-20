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
    is_active = Column(Boolean, default=True)
    # Pode ter mais colunas: owner_id, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    crews = relationship("Crew", back_populates="space", cascade="all, delete-orphan")
    data_connections = relationship("DataConnection", back_populates="space", cascade="all, delete-orphan")


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


# ========== DATA CONNECTIONS ==========

class DataConnection(Base):
    __tablename__ = "data_connections"

    id = Column(UUID(as_uuid=True), primary_key=True)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=False)

    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # ex: "bigquery", "postgres", "mysql", "redshift"

    config = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    space = relationship("Space", back_populates="data_connections")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])

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
    embedding = Column(Vector(3072), nullable=False)

    # Texto original embedado (metadado, chunk de doc, query, etc)
    text = Column(Text, nullable=False)

    # ⚠️ IMPORTANTE:
    # - Nome do atributo Python: extra_metadata
    # - Nome da coluna no banco: "metadata"
    extra_metadata = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    space = relationship("Space")
    crew = relationship("Crew")
    user = relationship("User")
    table_metadata = relationship("TableMetadata")
