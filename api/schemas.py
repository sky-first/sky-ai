# api/schemas.py
from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., description="Pergunta do usuário em linguagem natural.")
    user_id: Optional[str] = Field(None, description="ID do usuário (opcional).")
    space_id: Optional[str] = Field(None, description="Space atual (opcional).")
    crew_ids: Optional[List[str]] = Field(
        default=None, description="Lista de crews aos quais o usuário pertence."
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="ID do thread de conversa, se quiser contexto de múltiplas perguntas.",
    )


class QueryResultMeta(BaseModel):
    detected_language: Optional[str] = None
    chosen_table: Optional[str] = None
    sql: Optional[str] = None
    num_rows: int = 0
    error: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    data_sample: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Amostra dos dados retornados (máx. 15 linhas).",
    )
    meta: QueryResultMeta


# Schemas para DataConnections (usados em outros módulos)
class DataConnectionCreate(BaseModel):
    id: str
    name: str
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class DataConnectionResponse(BaseModel):
    id: str
    name: str
    type: str
    config: Dict[str, Any]
    created_at: Optional[str] = None


class IngestMetadataRequest(BaseModel):
    crew_id: Optional[str] = None


class GenerateEmbeddingsRequest(BaseModel):
    crew_id: Optional[str] = None
