# api/schemas.py
from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# Import SecurityConfig para uso no QueryRequest
from core.security.security_config import SecurityConfig, TableSecurityConfig


class QueryRequest(BaseModel):
    question: str = Field(..., description="User question in natural language.")
    user_id: Optional[str] = Field(None, description="User ID (optional).")
    space_id: Optional[str] = Field(None, description="Space atual (opcional).")
    crew_ids: Optional[List[str]] = Field(
        default=None, description="List of crews the user belongs to."
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Conversation thread ID, if multiple question context is desired.",
    )
    is_personal: Optional[bool] = Field(
        default=False,
        description="Indicates if query is in personal mode, granting access to all user's crews and spaces."
    )
    # AI Behavior Configuration
    instructions: Optional[str] = Field(
        default=None,
        description="General instructions on how the AI should behave."
    )
    creativity: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Creativity level (0-100). Controls LLM temperature."
    )
    length: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Response length level (0-100). Controls LLM max_tokens."
    )
    response_format: Optional[str] = Field(
        default=None,
        description="Formato desejado da resposta (ex: 'text', 'json', 'markdown')."
    )
    sql_instructions: Optional[str] = Field(
        default=None,
        description="Specific instructions for SQL generation."
    )
    selected_datasets: Optional[List[str]] = Field(
        default=None,
        description="List of datasets/tables manually selected by the user. If provided, the orchestrator will use only these tables instead of choosing automatically."
    )
    
    # ✅ NEW: Strictly authorized tables by the backend
    authorized_tables: Optional[List[str]] = Field(
        default=None,
        description="List of strictly authorized tables computed by the backend. If provided, the AI Engine will completely ignore any table not in this list."
    )
    
    # ✅ NEW: Dynamic security configuration (sent by backend)
    security_config: Optional[SecurityConfig] = Field(
        default=None,
        description="Security configuration sent by backend. Includes row_filters (RLS), "
                    "allowed/blocked columns, and other table-level security rules."
    )

    # ✅ NEW: Chat history for conversational memory
    chat_history: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="List of previous messages in the conversation to support follow-up questions."
    )


class QueryResultMeta(BaseModel):
    detected_language: Optional[str] = None
    chosen_table: Optional[str] = None
    chosen_datasets: Optional[List[str]] = None  # List of tables used by AI
    sql: Optional[str] = None
    title: Optional[str] = None  # New: dynamically generated title
    num_rows: int = 0
    error: Optional[str] = None
    rag_context: Optional[List[str]] = None # Debug info
    plan: Optional[str] = None # AI reasoning/rationale (Chain of Thought)
    # ✅ NEW: Dashboard plan for direct generation (Phase 1)
    dashboard_plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dashboard plan when direct generation is triggered via intent detection"
    )


class QueryResponse(BaseModel):
    answer: str
    data_sample: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Sample of returned data (max 15 rows).",
    )
    meta: QueryResultMeta
    recommended_widget_type: Optional[str] = Field(
        default=None,
        description="Suggested widget type (kpi/chart/table/text). Populated when response_format is present.",
    )


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
    
    # ✅ NEW: Original user question (70-80% weight on suggestions)
    # AI will only be called when this endpoint is invoked (on clicking 'Create Dashboard')
    original_question: Optional[str] = Field(
        default=None,
        description="Original user question to be included as first widget. Remaining widgets will be strongly related (70-80% weight) to this question. Only used when creating dashboard from starred question."
    )
    
    # ✅ NEW: Generation Mode
    mode: Optional[str] = Field(
        default="mix",
        description="Dashboard generation mode: 'textual' (more text, fewer charts), 'visual' (max charts, min text), or 'mix' (balanced)."
    )
    
    # ✅ NEW: Rich context for better suggestions
    initial_ai_response: Optional[str] = Field(
        default=None,
        description="The text content of the last AI answer the user saw. Use this to suggest specific titles."
    )
    context_spaces: Optional[List[str]] = Field(
        default=None,
        description="List of available spaces names to give situational awareness."
    )
    context_crews: Optional[List[str]] = Field(
        default=None,
        description="List of available crews names to give situational awareness."
    )
    context_tables: Optional[List[str]] = Field(
        default=None,
        description="List of all table names accessible to user to give situational awareness."
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
    title: str = Field(..., description="Same as dashboard_name, but explicit for frontend usage.")
    description: Optional[str] = None
    widgets: List[DashboardPlanWidget]
    meta: Optional[Dict[str, Any]] = None
    full_results: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw structured findings from Davinci (verdict, diagnostic, etc.)"
    )


# Schemas for DataConnections (used in other modules)
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
    user_id: str = Field(..., description="User ID.")
    space_id: str = Field(..., description="Space atual.")
    sql: str = Field(..., min_length=1, description="SQL to validate (cannot be empty).")
    crew_ids: Optional[List[str]] = Field(
        default=None, description="List of crews the user belongs to."
    )
    is_personal: Optional[bool] = Field(
        default=False,
        description="Indicates if in personal mode."
    )
    # ✅ NEW: Dynamic security configuration (sent by backend)
    security_config: Optional[SecurityConfig] = Field(
        default=None,
        description="Security configuration to validate SQL against RLS rules and columns."
    )
    # ✅ NEW: Ask for AI explanation
    question: Optional[str] = Field(
        default=None,
        description="User's original question (context for explanation)."
    )
    include_explanation: Optional[bool] = Field(
        default=False,
        description="If True, generates a textual explanation of results using AI."
    )


class ValidateSQLResponse(BaseModel):
    """SQL validation response."""
    is_valid: bool = Field(..., description="Whether SQL is valid and returns data.")
    error: Optional[str] = Field(None, description="Error message if invalid.")
    preview_data: Optional[List[Dict[str, Any]]] = Field(
        None, description="Data preview (max 5 rows) if valid."
    )
    num_rows: Optional[int] = Field(None, description="Number of returned rows.")
    execution_time_ms: Optional[float] = Field(None, description="Execution time in ms.")
    columns: Optional[List[str]] = Field(None, description="Colunas retornadas.")
    explanation: Optional[str] = Field(
        None, description="Textual explanation generated by AI (if requested)."
    )

# =========================
# Knowledge Graph Ingestion
# =========================

class KnowledgeIngestRequest(BaseModel):
    id: str
    entity_type: str  # strategic_pillar, strategic_objective, strategy_okr, signal_event, etc.
    name: Optional[str] = None
    description: Optional[str] = None
    space_id: Optional[str] = None
    crew_id: Optional[str] = None
    entity_details: Optional[Dict[str, Any]] = None
    
    # Optional fields for Signal Events
    category: Optional[str] = None
    sub_type: Optional[str] = None
    nature: Optional[str] = None
    start_date: Optional[str] = None
    impact_date: Optional[str] = None
    confidence: Optional[str] = None
