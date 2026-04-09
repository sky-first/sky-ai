from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class AnalysisContext(BaseModel):
    """
    Contract that defines the analytical intent extracted from the Chat conversation.
    This structure bridges the gap between the Chat Orchestrator (Intent) and 
    the Davinci Agent (Expansion).
    """
    version: int = Field(default=1, description="Schema version for future compatibility")
    
    # 🎯 Primary Analytical Anchor
    primary_entity: str = Field(..., description="The main business entity (e.g., 'invoices', 'customers')")
    primary_metric: str = Field(..., description="The main metric requested (e.g., 'total_amount', 'count')")
    primary_dimension: Optional[str] = Field(None, description="The main grouping dimension (e.g., 'status', 'region')")
    time_column: Optional[str] = Field(None, description="The relevant time column for trends (e.g., 'created_at')")
    
    # 🧠 Intent Classification
    detected_analysis_type: Literal['trend', 'distribution', 'kpi', 'comparison', 'ranking', 'list', 'other'] = Field(
        ..., description="The type of analysis inferred from the question"
    )
    
    # 🔒 Security & Scope Guardrails
    validated_tables: List[str] = Field(..., description="List of logical tables validated by RAG/Specialist")
    validated_columns: List[str] = Field(..., description="List of columns confirmed to exist in the schema")
    
    class Config:
        frozen = True # Context should be immutable once created
