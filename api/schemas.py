# api/schemas.py
from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# Import SecurityConfig para uso no QueryRequest
from core.security.security_config import SecurityConfig, TableSecurityConfig


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
    is_personal: Optional[bool] = Field(
        default=False,
        description="Indica se a query está no modo personal, concedendo acesso a todos os crews e spaces do usuário."
    )
    # Configurações de comportamento da IA
    instructions: Optional[str] = Field(
        default=None,
        description="Instruções gerais sobre como a IA deve se comportar."
    )
    creativity: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Nível de criatividade (0-100). Controla a temperatura do LLM."
    )
    length: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Nível de comprimento da resposta (0-100). Controla max_tokens do LLM."
    )
    response_format: Optional[str] = Field(
        default=None,
        description="Formato desejado da resposta (ex: 'text', 'json', 'markdown')."
    )
    sql_instructions: Optional[str] = Field(
        default=None,
        description="Instruções específicas para geração de SQL."
    )
    selected_datasets: Optional[List[str]] = Field(
        default=None,
        description="Lista de datasets/tabelas selecionados manualmente pelo usuário. Se fornecido, o orchestrator usará apenas essas tabelas ao invés de escolher automaticamente."
    )
    
    # ✅ NOVO: Configuração de segurança dinâmica (enviada pelo backend)
    security_config: Optional[SecurityConfig] = Field(
        default=None,
        description="Configuração de segurança enviada pelo backend. Inclui row_filters (RLS), "
                    "allowed/blocked columns, e outras regras de segurança por tabela."
    )


class QueryResultMeta(BaseModel):
    detected_language: Optional[str] = None
    chosen_table: Optional[str] = None
    chosen_datasets: Optional[List[str]] = None  # List of tables used by AI
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


class ChatBootstrapSuggestion(BaseModel):
    title: str = Field(..., description="Short title for the suggestion card.")
    kind: str = Field(default="question", description="question|action")
    question: Optional[str] = Field(default=None, description="Suggested question to send to chat.")
    action_id: Optional[str] = Field(default=None, description="Action identifier when kind='action'.")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Optional action payload.")


class ChatBootstrapRequest(BaseModel):
    user_id: str = Field(..., description="User ID (required).")
    space_id: str = Field(..., description="Space ID (required).")
    crew_ids: Optional[List[str]] = Field(
        default=None, description="Crew IDs resolved by product backend (optional)."
    )
    is_personal: Optional[bool] = Field(
        default=False,
        description="If True, suggestions can use all crews/spaces the user belongs to (personal mode). If False, only data from the specific space/crew (collaborative mode).",
    )
    language: Optional[str] = Field(
        default=None, description="Language hint (e.g. en, pt, es)."
    )
    max_suggestions: int = Field(
        default=4, ge=1, le=8, description="How many suggestion cards to generate."
    )


class ChatBootstrapResponse(BaseModel):
    greeting: str
    suggestions: List[ChatBootstrapSuggestion]
    meta: Optional[Dict[str, Any]] = None


# =========================
# Dashboard generation (Davinci)
# =========================


class DashboardPlanWidget(BaseModel):
    """A single widget specification for a generated dashboard."""

    widget_key: str = Field(..., description="Stable key within the plan (e.g., w1, w2).")
    type: str = Field(..., description="Widget type (chart|kpi|table|text).")
    title: str = Field(..., description="Widget title.")
    question: str = Field(..., description="Question that will be executed to generate query_id.")
    viz: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Visualization spec (frontend maps this to Tremor charts).",
    )


class DashboardPlanRequest(BaseModel):
    """Request to generate a dashboard plan based on accessible metadata."""

    user_id: str = Field(..., description="User ID (required).")
    space_id: str = Field(..., description="Space ID (required).")
    crew_ids: Optional[List[str]] = Field(default=None, description="Crew IDs (optional).")
    is_personal: Optional[bool] = Field(
        default=False,
        description="If True, planner can use all crews/spaces the user belongs to (personal mode).",
    )
    language: Optional[str] = Field(default="en", description="Language hint (e.g., en).")
    goal: str = Field(..., description="Dashboard goal (e.g., Billing overview).")
    # Temporarily keep dashboard creation fully automatic with a fixed cap.
    max_widgets: int = Field(default=8, ge=1, le=8)
    
    # ✅ NOVO: Pergunta original do usuário (70-80% de peso nas sugestões)
    # A IA só será chamada quando este endpoint for invocado (ao clicar em "Criar Dashboard")
    original_question: Optional[str] = Field(
        default=None,
        description="Original user question to be included as first widget. Remaining widgets will be strongly related (70-80% weight) to this question. Only used when creating dashboard from starred question."
    )

    # Backend-override fields (allows the product backend to pass catalog directly)
    logical_tables_override: Optional[List[str]] = Field(
        default=None,
        description="Optional explicit list of logical tables (e.g. schema.table) to use for planning.",
    )
    schema_summary_override: Optional[str] = Field(
        default=None,
        description="Optional explicit schema summary to use for planning (table + key columns).",
    )

    # Backend-override fields (allows the product backend to pass catalog directly)
    logical_tables_override: Optional[List[str]] = Field(
        default=None,
        description="Optional explicit list of logical tables (e.g. schema.table) to use for planning.",
    )
    schema_summary_override: Optional[str] = Field(
        default=None,
        description="Optional explicit schema summary to use for planning (table + key columns).",
    )


class DashboardPlanResponse(BaseModel):
    """Response containing a dashboard plan."""

    dashboard_name: str
    description: Optional[str] = None
    widgets: List[DashboardPlanWidget]
    meta: Optional[Dict[str, Any]] = None


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


# Schemas para Spaces
class SpaceCreate(BaseModel):
    name: str
    description: Optional[str] = None


class SpaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SpaceResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    is_active: Optional[bool] = True

    class Config:
        from_attributes = True


# Schemas para Planets
class PlanetCreate(BaseModel):
    space_id: str
    name: str
    description: Optional[str] = None
    required_scopes: Optional[List[str]] = None


class PlanetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    required_scopes: Optional[List[str]] = None
    is_active: Optional[bool] = None


class PlanetResponse(BaseModel):
    id: str
    space_id: str
    name: str
    description: Optional[str] = None
    required_scopes: Optional[List[str]] = None
    created_at: Optional[str] = None
    is_active: Optional[bool] = True

    class Config:
        from_attributes = True


# Schemas para Crews
class CrewCreate(BaseModel):
    space_id: str
    name: str
    description: Optional[str] = None


class CrewUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class CrewResponse(BaseModel):
    id: str
    space_id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    is_active: Optional[bool] = True

    class Config:
        from_attributes = True


# Schemas para Connections (CRUD)
class ConnectionCreate(BaseModel):
    space_id: str
    name: str
    connection_type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class ConnectionResponse(BaseModel):
    id: str
    space_id: str
    name: str
    connection_type: str
    config: Dict[str, Any]
    created_at: Optional[str] = None
    is_active: Optional[bool] = True

    class Config:
        from_attributes = True


# =========================
# SQL Validation
# =========================


class ValidateSQLRequest(BaseModel):
    """Request para validar SQL."""
    user_id: str = Field(..., description="ID do usuário.")
    space_id: str = Field(..., description="Space atual.")
    sql: str = Field(..., min_length=1, description="SQL a ser validado (não pode ser vazio).")
    crew_ids: Optional[List[str]] = Field(
        default=None, description="Lista de crews aos quais o usuário pertence."
    )
    is_personal: Optional[bool] = Field(
        default=False,
        description="Indica se está no modo personal."
    )
    # ✅ NOVO: Configuração de segurança dinâmica (enviada pelo backend)
    security_config: Optional[SecurityConfig] = Field(
        default=None,
        description="Configuração de segurança para validar o SQL contra regras de RLS e colunas."
    )


class ValidateSQLResponse(BaseModel):
    """Response da validação de SQL."""
    is_valid: bool = Field(..., description="Se o SQL é válido e retorna dados.")
    error: Optional[str] = Field(None, description="Mensagem de erro se inválido.")
    preview_data: Optional[List[Dict[str, Any]]] = Field(
        None, description="Preview dos dados (máx. 5 linhas) se válido."
    )
    num_rows: Optional[int] = Field(None, description="Número de linhas retornadas.")
    execution_time_ms: Optional[float] = Field(None, description="Tempo de execução em ms.")
    columns: Optional[List[str]] = Field(None, description="Colunas retornadas.")
